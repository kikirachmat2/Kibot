"""
Orchestrator untuk menjalankan 3 skenario × 3 pair × 4 strategi.
Output: dict hasil per (scenario, pair, strategy) + JSON dump.
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import json
import logging
from typing import Dict, Any, Optional
import pandas as pd

from backtest.data_loader import fetch_indodax_ohlcv, fetch_binance_ohlcv, align_indodax_binance
from backtest.engine import run_backtest
from backtest.friction import OrderType
from backtest.report import generate_markdown_report

logger = logging.getLogger("KiBotV2.Backtest.ScenarioRunner")

SCENARIOS = {
    "S1_2023_full": (
        int(datetime(2023, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
        int(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
    ),
    "S2_Q3_2024": (
        int(datetime(2024, 7, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
        int(datetime(2024, 10, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
    ),
    "S3_2025_to_now": (
        int(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()),
        int(datetime.now(timezone.utc).timestamp()),
    ),
}

PAIRS = ["BTCIDR", "ETHIDR", "SOLIDR"]  # AVAXIDR excluded
STRATEGIES = ["D1", "D2", "D3", "C_prime"]
BINANCE_MAP = {"BTCIDR": "BTCUSDT", "ETHIDR": "ETHUSDT", "SOLIDR": "SOLUSDT"}

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"


def run_all_scenarios(
    order_type: OrderType = OrderType.MAKER,
    initial_capital_idr: float = 10_000_000.0,
    position_size_idr: float = 5_000_000.0,
    results_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Runs full matrix of 3 scenarios × 3 pairs × 4 strategies.
    Saves JSON summary to results/all_scenarios.json.
    Saves individual trade logs to results/trades/{scenario}_{pair}_{strategy}.json.
    Generates Markdown report to results/REPORT_YYYYMMDD.md.
    """
    base_res_dir = results_dir or DEFAULT_RESULTS_DIR
    trades_dir = base_res_dir / "trades"
    trades_dir.mkdir(parents=True, exist_ok=True)

    all_results: Dict[str, Dict[str, Dict[str, Any]]] = {}

    print("\n" + "=" * 90)
    print("🚀 MEMULAI BACKTEST ORCHESTRATOR KIBOT V2 (3 Skenario × 3 Pair × 4 Strategi)")
    print(f"💰 Initial Capital: Rp {initial_capital_idr:,.0f} | Slot: Rp {position_size_idr:,.0f} | OrderType: {order_type.value}")
    print("=" * 90 + "\n")

    for sc_name, (from_ts, to_ts) in SCENARIOS.items():
        all_results[sc_name] = {}
        print(f"\n📂 Menjalankan Skenario: {sc_name} (from: {from_ts} to: {to_ts})")

        for pair in PAIRS:
            all_results[sc_name][pair] = {}
            binance_sym = BINANCE_MAP[pair]

            print(f"   ⏳ Loading & aligning data for {pair} ({binance_sym})...")
            # Fetch Indodax and Binance historical data
            indo_df = fetch_indodax_ohlcv(symbol=pair, tf="60", from_ts=from_ts, to_ts=to_ts)
            bina_df = fetch_binance_ohlcv(symbol=binance_sym, tf="1h", from_ts=from_ts, to_ts=to_ts)

            # Inner-join alignment
            aligned_df = align_indodax_binance(indo_df, bina_df)

            for strat in STRATEGIES:
                res = run_backtest(
                    aligned_df=aligned_df,
                    strategy_name=strat,
                    pair=pair,
                    initial_capital_idr=initial_capital_idr,
                    position_size_idr=position_size_idr,
                    order_type=order_type,
                    random_seed=42,
                )

                # Save trade log to separate file
                trades_log = res.pop("trades_log", [])
                trade_log_file = trades_dir / f"{sc_name}_{pair}_{strat}.json"
                with open(trade_log_file, "w", encoding="utf-8") as tf:
                    json.dump(trades_log, tf, indent=2)

                all_results[sc_name][pair][strat] = res

                # Console log one-liner
                net_nom = res["net_pnl_idr"]
                net_p = res["net_pnl_pct"]
                wr = res["win_rate"]
                nt = res["n_trades"]
                mdd = res["max_drawdown_pct"]
                pf = res["profit_factor"]
                print(
                    f"      [{sc_name}] [{pair:7s}] [{strat:7s}] -> "
                    f"Trades: {nt:3d} | WR: {wr:5.1f}% | Net: Rp {net_nom:>11,.0f} ({net_p:>+6.2f}%) | "
                    f"MaxDD: {mdd:4.1f}% | PF: {pf:4.2f}"
                )

    # Save summary JSON
    output_json = base_res_dir / "all_scenarios.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n💾 Summary JSON disimpan ke: {output_json}")

    # Generate Markdown Report
    today_str = datetime.now().strftime("%Y%m%d")
    report_file = base_res_dir / f"REPORT_{today_str}.md"
    generate_markdown_report(all_results, report_file)
    print(f"📄 Markdown Report dibuat di: {report_file}\n")

    return all_results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_all_scenarios()
