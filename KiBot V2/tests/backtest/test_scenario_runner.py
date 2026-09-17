"""
Unit tests for Scenario Runner and Report Generator.
Runs completely offline using synthetic data and mocks.
"""
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest

from backtest.scenario_runner import run_all_scenarios, SCENARIOS
from backtest.report import generate_markdown_report
from backtest.friction import OrderType


@pytest.fixture
def mini_df():
    """Generates 30 bars of dummy OHLCV data."""
    base_ts = 1700000000
    rows = []
    p = 100_000_000.0
    for i in range(30):
        rows.append({
            "timestamp_utc": base_ts + (i * 3600),
            "open": p, "high": p * 1.01, "low": p * 0.99, "close": p, "volume": 5.0,
        })
    return pd.DataFrame(rows)


def test_scenario_runner_execution_and_json_structure(tmp_path, mini_df):
    """Verifies that run_all_scenarios creates proper JSON structure and trade logs."""
    with patch("backtest.scenario_runner.fetch_indodax_ohlcv", return_value=mini_df), \
         patch("backtest.scenario_runner.fetch_binance_ohlcv", return_value=mini_df):

        # Use temporary directory for results
        results = run_all_scenarios(
            order_type=OrderType.MAKER,
            results_dir=tmp_path,
        )

        # Check returned dictionary structure
        for sc in SCENARIOS:
            assert sc in results
            for pair in ["BTCIDR", "ETHIDR", "SOLIDR"]:
                assert pair in results[sc]
                for strat in ["D1", "D2", "D3", "C_prime"]:
                    assert strat in results[sc][pair]
                    res = results[sc][pair][strat]
                    assert "net_pnl_idr" in res
                    assert "trades_log" not in res, "trades_log should be extracted out of summary dict"

        # Check files created on disk
        summary_file = tmp_path / "all_scenarios.json"
        assert summary_file.exists(), "Summary JSON file must exist"

        trades_dir = tmp_path / "trades"
        assert trades_dir.exists()
        trade_files = list(trades_dir.glob("*.json"))
        # 3 scenarios * 3 pairs * 4 strats = 36 trade log files
        assert len(trade_files) == 36


def test_report_generator_markdown_validity(tmp_path):
    """Verifies that generate_markdown_report creates valid Markdown with required sections."""
    dummy_results = {
        "S1_2023_full": {
            "BTCIDR": {
                "D1": {
                    "strategy": "D1", "pair": "BTCIDR", "n_trades": 50, "n_wins": 30, "n_losses": 20,
                    "n_unfilled": 2, "win_rate": 60.0, "avg_win_pct": 1.2, "avg_loss_pct": -1.0,
                    "gross_pnl_idr": 1_000_000.0, "total_friction_idr": 280_000.0,
                    "total_adverse_penalty_idr": 300_000.0, "net_pnl_idr": 420_000.0,
                    "net_pnl_pct": 4.2, "max_drawdown_pct": 2.5, "profit_factor": 1.8,
                    "expectancy_per_trade_pct": 0.084, "fee_to_gross_ratio": 0.58,
                }
            }
        }
    }

    report_path = tmp_path / "test_report.md"
    content = generate_markdown_report(dummy_results, report_path)

    assert report_path.exists()
    assert "# LAPORAN HASIL BACKTEST KUANTITATIF KIBOT V2" in content
    assert "## Skenario: `S1_2023_full`" in content
    assert "## AGGREGATE PERFORMANCE" in content
    assert "## DECISION & EVALUATION GATES" in content
    assert "BTCIDR" in content
    assert "D1" in content


def test_broad_universe_backtest_and_report_validity(tmp_path, mini_df):
    """Verifies that run_broad_universe_backtest runs offline with mocks and writes universe report."""
    from backtest.scenario_runner import run_broad_universe_backtest
    from backtest.report_universe import generate_universe_report

    mock_universe = [
        {"pair": "BTCIDR", "binance_pair": "BTCUSDT", "has_binance": True, "volume_idr": 1e9, "spread_pct": 0.1},
        {"pair": "XYZIDR", "binance_pair": None, "has_binance": False, "volume_idr": 5e8, "spread_pct": 0.2},
    ]

    with patch("backtest.scenario_runner.select_tradable_universe", return_value=mock_universe), \
         patch("backtest.scenario_runner.fetch_indodax_ohlcv", return_value=mini_df), \
         patch("backtest.scenario_runner.fetch_binance_ohlcv", return_value=mini_df):

        res = run_broad_universe_backtest(
            universe=["BTCIDR", "XYZIDR"],
            scenarios=["S1_2023_full"],
            strategies=["D1", "D3", "TREND_1D"],
            results_dir=tmp_path,
            max_pairs=2,
        )

        assert "scenarios" in res
        assert "results" in res
        assert "S1_2023_full" in res["results"]
        assert "BTCIDR" in res["results"]["S1_2023_full"]
        # XYZIDR has no Binance mapping -> D3 (lead-lag) should be excluded, only D1 and TREND_1D run
        assert "XYZIDR" in res["results"]["S1_2023_full"]
        assert "D3" not in res["results"]["S1_2023_full"]["XYZIDR"]
        assert "TREND_1D" in res["results"]["S1_2023_full"]["XYZIDR"]

        # Check universe report markdown
        report_file = tmp_path / "test_universe_report.md"
        md_content = generate_universe_report(res, report_file)
        assert report_file.exists()
        assert "# REPORT EVALUASI BROAD UNIVERSE — KIBOT V2" in md_content
        assert "## 1. Agregasi Kinerja Per Pair" in md_content
        assert "## 2. Agregasi Kinerja Per Strategi" in md_content
        assert "## 3. Top 10 Pairs by Net Profit" in md_content
        assert "## 4. Top 5 Strategies by Net Profit" in md_content
        assert "## 5. Rekomendasi Shadow Ledger" in md_content

