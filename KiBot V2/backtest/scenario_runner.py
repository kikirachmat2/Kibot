"""
Orchestrator untuk menjalankan skenario backtest KiBot V2.
Mendukung:
1. Baseline backtest (3 skenario × 3 pair × 4 strategi)
2. Broad Universe backtest (--broad: 3 skenario × top 30 pair × 7 strategi)
"""
from __future__ import annotations

import argparse
from pathlib import Path
from datetime import datetime, timezone
import json
import logging
from typing import Dict, Any, Optional, List
import pandas as pd

from backtest.data_loader import fetch_indodax_ohlcv, fetch_binance_ohlcv, align_indodax_binance
from backtest.engine import run_backtest
from backtest.friction import OrderType
from backtest.report import generate_markdown_report
from backtest.report_universe import generate_universe_report
from backtest.universe_scanner import select_tradable_universe

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

PAIRS = ["BTCIDR", "ETHIDR", "SOLIDR"]  # Baseline pairs
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
    Runs baseline matrix of 3 scenarios × 3 pairs × 4 strategies.
    Saves JSON summary to results/all_scenarios.json.
    Saves individual trade logs to results/trades/{scenario}_{pair}_{strategy}.json.
    Generates Markdown report to results/REPORT_YYYYMMDD.md.
    """
    base_res_dir = results_dir or DEFAULT_RESULTS_DIR
    trades_dir = base_res_dir / "trades"
    trades_dir.mkdir(parents=True, exist_ok=True)

    all_results: Dict[str, Dict[str, Dict[str, Any]]] = {}

    print("\n" + "=" * 90)
    print("🚀 MEMULAI BACKTEST BASELINE KIBOT V2 (3 Skenario × 3 Pair × 4 Strategi)")
    print(f"💰 Initial Capital: Rp {initial_capital_idr:,.0f} | Slot: Rp {position_size_idr:,.0f} | OrderType: {order_type.value}")
    print("=" * 90 + "\n")

    for sc_name, (from_ts, to_ts) in SCENARIOS.items():
        all_results[sc_name] = {}
        print(f"\n📂 Menjalankan Skenario: {sc_name} (from: {from_ts} to: {to_ts})")

        for pair in PAIRS:
            all_results[sc_name][pair] = {}
            binance_sym = BINANCE_MAP[pair]

            print(f"   ⏳ Loading & aligning data for {pair} ({binance_sym})...")
            indo_df = fetch_indodax_ohlcv(symbol=pair, tf="60", from_ts=from_ts, to_ts=to_ts)
            bina_df = fetch_binance_ohlcv(symbol=binance_sym, tf="1h", from_ts=from_ts, to_ts=to_ts)
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

                trades_log = res.pop("trades_log", [])
                trade_log_file = trades_dir / f"{sc_name}_{pair}_{strat}.json"
                with open(trade_log_file, "w", encoding="utf-8") as tf:
                    json.dump(trades_log, tf, indent=2)

                all_results[sc_name][pair][strat] = res

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

    output_json = base_res_dir / "all_scenarios.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n💾 Summary JSON disimpan ke: {output_json}")

    today_str = datetime.now().strftime("%Y%m%d")
    report_file = base_res_dir / f"REPORT_{today_str}.md"
    generate_markdown_report(all_results, report_file)
    print(f"📄 Markdown Report dibuat di: {report_file}\n")

    return all_results


def run_broad_universe_backtest(
    universe: Optional[List[str]] = None,
    scenarios: Optional[List[str]] = None,
    strategies: Optional[List[str]] = None,
    order_type: OrderType = OrderType.MAKER,
    initial_capital_idr: float = 10_000_000.0,
    position_size_idr: float = 5_000_000.0,
    max_pairs: int = 30,
    results_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run backtest across broad universe (top pairs filtered by volume & spread).
    For each pair, loads Indodax data (+ Binance data if available), and runs each strategy.
    Batasan:
    - Pairs tanpa Binance: jalankan TREND_1D, MR_4H, MR_1D, D1, D2.
    - Pairs dengan Binance: jalankan seluruh strategi termasuk D3 dan C_prime.
    - Dibatasi ke max 30 pairs teratas berdasarkan 24h volume.
    """
    base_res_dir = results_dir or DEFAULT_RESULTS_DIR
    trades_dir = base_res_dir / "universe_trades"
    trades_dir.mkdir(parents=True, exist_ok=True)

    sc_names = scenarios or list(SCENARIOS.keys())
    strat_list = strategies or ["D1", "D2", "D3", "C_prime", "TREND_1D", "MR_4H", "MR_1D"]

    # 1. Resolve Universe & Binance mapping
    qualified_universe = select_tradable_universe(
        min_volume_idr=10_000_000.0,
        max_spread_pct=0.80,
    )

    if universe is not None:
        target_symbols = set(u.upper().replace("_", "") for u in universe)
        universe_items = [u for u in qualified_universe if u["pair"] in target_symbols]
        # Include custom pairs if not in pre-scanned list
        scanned_syms = set(u["pair"] for u in universe_items)
        for s in universe:
            sym = s.upper().replace("_", "")
            if sym not in scanned_syms:
                universe_items.append({
                    "pair": sym,
                    "binance_pair": None,
                    "has_binance": False,
                    "volume_idr": 0.0,
                    "spread_pct": 0.0,
                })
    else:
        universe_items = qualified_universe

    # Cap to top max_pairs
    universe_items = universe_items[:max_pairs]

    print("\n" + "=" * 90)
    print("🌌 MEMULAI BROAD UNIVERSE BACKTEST KIBOT V2")
    print(f"📊 Total Pairs Terpilih: {len(universe_items)} (Max {max_pairs} by Volume)")
    print(f"🎯 Skenario: {', '.join(sc_names)}")
    print(f"⚡ Strategi: {', '.join(strat_list)}")
    print(f"💰 Initial Capital: Rp {initial_capital_idr:,.0f} | Slot: Rp {position_size_idr:,.0f} | OrderType: {order_type.value}")
    print("=" * 90 + "\n")

    all_results: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for sc_name in sc_names:
        if sc_name not in SCENARIOS:
            logger.warning(f"[BroadUniverse] Skenario '{sc_name}' tidak ditemukan di SCENARIOS table. Skipping.")
            continue

        from_ts, to_ts = SCENARIOS[sc_name]
        all_results[sc_name] = {}
        print(f"\n📂 Menjalankan Skenario: {sc_name} ({datetime.fromtimestamp(from_ts, timezone.utc).strftime('%Y-%m-%d')} s/d {datetime.fromtimestamp(to_ts, timezone.utc).strftime('%Y-%m-%d')})")

        for u_item in universe_items:
            pair = u_item["pair"]
            b_sym = u_item.get("binance_pair")
            all_results[sc_name][pair] = {}

            # Fetch Indodax data
            try:
                indo_df = fetch_indodax_ohlcv(symbol=pair, tf="60", from_ts=from_ts, to_ts=to_ts)
                if indo_df is None or len(indo_df) < 2:
                    logger.warning(f"[BroadUniverse] Data Indodax {pair} kosong/terlalu pendek untuk {sc_name}. Skipping.")
                    continue
            except Exception as e:
                logger.warning(f"[BroadUniverse] Gagal fetch Indodax {pair} ({sc_name}): {e}. Skipping.")
                continue

            # Fetch Binance if available and align
            aligned_df = None
            has_binance_active = False

            if b_sym:
                try:
                    bina_df = fetch_binance_ohlcv(symbol=b_sym, tf="1h", from_ts=from_ts, to_ts=to_ts)
                    aligned_df = align_indodax_binance(indo_df, bina_df)
                    has_binance_active = True
                except Exception as e:
                    logger.info(f"[BroadUniverse] Binance {b_sym} tidak tersedia untuk {sc_name}: {e}. Fallback Indodax-only.")

            if aligned_df is None or not has_binance_active:
                # Format Indodax-only DataFrame
                indo_cols = {c: f"indo_{c}" for c in ["open", "high", "low", "close", "volume"]}
                aligned_df = indo_df.copy().rename(columns=indo_cols)
                aligned_df["dislocation_1h"] = 0.0
                aligned_df["corr_24h"] = 0.0
                has_binance_active = False

            # Filter runnable strategies based on Binance availability
            if has_binance_active:
                runnable_strats = strat_list
            else:
                # Exclude lead-lag strategies if no Binance data
                runnable_strats = [s for s in strat_list if s not in ("D3", "C_prime", "C'", "CPRIME")]

            for strat in runnable_strats:
                try:
                    res = run_backtest(
                        aligned_df=aligned_df,
                        strategy_name=strat,
                        pair=pair,
                        initial_capital_idr=initial_capital_idr,
                        position_size_idr=position_size_idr,
                        order_type=order_type,
                        random_seed=42,
                    )

                    trades_log = res.pop("trades_log", [])
                    trade_log_file = trades_dir / f"{sc_name}_{pair}_{strat}.json"
                    with open(trade_log_file, "w", encoding="utf-8") as tf:
                        json.dump(trades_log, tf, indent=2)

                    all_results[sc_name][pair][strat] = res

                    net_nom = res["net_pnl_idr"]
                    wr = res["win_rate"]
                    nt = res["n_trades"]
                    mdd = res["max_drawdown_pct"]
                    pf = res["profit_factor"]
                    print(
                        f"   [{sc_name}] [{pair:7s}] [{strat:8s}] -> "
                        f"N: {nt:3d} | WR: {wr:5.1f}% | Net: Rp {net_nom:>11,.0f} | "
                        f"MDD: {mdd:4.1f}% | PF: {pf:4.2f}"
                    )
                except Exception as e:
                    logger.warning(f"[BroadUniverse] Error executing {strat} on {pair} ({sc_name}): {e}")

    # Compile and save JSON
    summary_output = {
        "scenarios": sc_names,
        "results": all_results,
    }
    json_path = base_res_dir / "universe_all_scenarios.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_output, f, indent=2)
    print(f"\n💾 Universe Summary JSON disimpan ke: {json_path}")

    # Generate Markdown Report
    today_str = datetime.now().strftime("%Y%m%d")
    report_file = base_res_dir / f"REPORT_UNIVERSE_{today_str}.md"
    generate_universe_report(summary_output, report_file)
    print(f"📄 Universe Markdown Report dibuat di: {report_file}\n")

    return summary_output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="KiBot V2 Backtest Scenario Runner")
    parser.add_argument("--broad", action="store_true", help="Run broad universe backtest across top 30 Indodax pairs")
    parser.add_argument("--max-pairs", type=int, default=30, help="Maximum number of pairs to backtest in broad mode")
    args = parser.parse_args()

    if args.broad:
        run_broad_universe_backtest(max_pairs=args.max_pairs)
    else:
        run_all_scenarios()
