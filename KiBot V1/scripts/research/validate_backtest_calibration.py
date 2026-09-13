"""Sanity Check Script: Calibrating Backtest Engine against Live Baseline (~26% Win Rate).

Tests the enhanced backtest_engine (with max_hold_bars=8 and trailing ratchet)
against real Indodax historical 15m candles using:
1. Ground-Truth signals from decision_journal (Option 3)
2. Line-by-line KiBot scanner replica signals (Option 2)
3. Walk-forward testing across rolling folds
"""

import json
import time
import requests
from typing import Dict, List
from Core.Research.backtest_engine import (
    Bar,
    run_backtest,
    load_ground_truth_signals,
    create_ground_truth_signal_fn,
    kibot_scanner_signal_fn,
)
from Core.Research.walk_forward import run_walk_forward


def fetch_indodax_candles(symbol: str, days: int = 45) -> List[Bar]:
    now = int(time.time())
    from_ts = now - (days * 86400)
    clean_sym = symbol.replace("/", "").replace("_", "").upper()
    url = f"https://indodax.com/tradingview/history_v2?symbol={clean_sym}&tf=15&from={from_ts}&to={now}"
    try:
        r = requests.get(url, timeout=12)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return [
            Bar(
                timestamp=float(d["Time"]),
                open=float(d["Open"]),
                high=float(d["High"]),
                low=float(d["Low"]),
                close=float(d["Close"]),
                volume=float(d.get("Volume") or 0.0),
            )
            for d in data
            if d.get("Close") is not None
        ]
    except Exception as e:
        print(f"Failed to fetch candles for {symbol}: {e}")
        return []


def main():
    print("=" * 70)
    print("KIBOT BACKTEST ENGINE CALIBRATION & SANITY CHECK")
    print("=" * 70)

    # 1. Load Ground Truth signals
    signals_map = load_ground_truth_signals("state/ground_truth_signals.json")
    print(f"Loaded {sum(len(v) for v in signals_map.values())} ground truth signals across {len(signals_map)} pairs.")

    test_pairs = [
        "SUI/IDR",
        "DOGE/IDR",
        "ADA/IDR",
        "ONDO/IDR",
        "BNB/IDR",
        "PEPE/IDR",
        "BEAT/IDR",
        "SYN/IDR",
    ]

    print("\n--- TEST 1: Ground Truth Signals + max_hold_bars=8 (Live Parity) ---")
    total_trades = 0
    total_wins = 0
    all_exit_reasons = {}

    for pair in test_pairs:
        pair_signals = signals_map.get(pair, [])
        bars = fetch_indodax_candles(pair, days=45)
        if len(bars) < 50:
            print(f"Skipping {pair}: insufficient candle data ({len(bars)} bars)")
            continue

        if pair_signals:
            sig_fn = create_ground_truth_signal_fn(pair_signals, tolerance_seconds=900.0)
        else:
            sig_fn = kibot_scanner_signal_fn

        res = run_backtest(
            bars,
            strategy_id=f"GT_{pair}",
            take_profit_pct=0.035,   # +3.5%
            stop_loss_pct=0.010,     # -1.0%
            fee_pct=0.00305,         # 0.61% roundtrip
            max_hold_bars=8,         # 2h timeout
            trailing_schedule=[(1.2, 0.6), (2.0, 0.8), (4.0, 1.5)],
            entry_signal_fn=sig_fn,
        )

        total_trades += res.total_trades
        total_wins += res.winning_trades
        for r, cnt in res.exit_reasons.items():
            all_exit_reasons[r] = all_exit_reasons.get(r, 0) + cnt

        print(f"  {pair:10s}: {res.total_trades:3d} trades, {res.winning_trades:3d} wins ({res.win_rate*100:5.1f}% WR), EV: {res.expectancy_pct*100:+.3f}%, exits: {res.exit_reasons}")

    overall_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print(f"\n>> Ground Truth Aggregate: {total_trades} trades, {total_wins} wins, Win Rate: {overall_wr:.2f}%")
    print(f">> Exit breakdown: {all_exit_reasons}")

    print("\n--- TEST 2: Line-by-Line Scanner Replica (kibot_scanner_signal_fn) ---")
    replica_trades = 0
    replica_wins = 0
    replica_exits = {}

    for pair in test_pairs:
        bars = fetch_indodax_candles(pair, days=45)
        if len(bars) < 50:
            continue

        res_rep = run_backtest(
            bars,
            strategy_id=f"REPLICA_{pair}",
            take_profit_pct=0.035,
            stop_loss_pct=0.010,
            fee_pct=0.00305,
            max_hold_bars=8,
            trailing_schedule=[(1.2, 0.6), (2.0, 0.8), (4.0, 1.5)],
            entry_signal_fn=lambda bar, hist: kibot_scanner_signal_fn(bar, hist, min_confidence=0.70),
        )

        replica_trades += res_rep.total_trades
        replica_wins += res_rep.winning_trades
        for r, cnt in res_rep.exit_reasons.items():
            replica_exits[r] = replica_exits.get(r, 0) + cnt

        print(f"  {pair:10s}: {res_rep.total_trades:3d} trades, {res_rep.winning_trades:3d} wins ({res_rep.win_rate*100:5.1f}% WR), EV: {res_rep.expectancy_pct*100:+.3f}%, exits: {res_rep.exit_reasons}")

    rep_wr = replica_wins / replica_trades * 100 if replica_trades > 0 else 0
    print(f"\n>> Scanner Replica Aggregate: {replica_trades} trades, {replica_wins} wins, Win Rate: {rep_wr:.2f}%")
    print(f">> Exit breakdown: {replica_exits}")

    print("\n--- TEST 3: Walk-Forward Testing (OOS Validation) ---")
    wf_wins = []
    wf_trades = 0
    for pair in ["SUI/IDR", "ADA/IDR", "DOGE/IDR", "BNB/IDR"]:
        bars = fetch_indodax_candles(pair, days=45)
        if len(bars) < 100:
            continue
        wf_res = run_walk_forward(
            bars,
            strategy_id=f"WF_{pair}",
            n_folds=4,
            take_profit_pct=0.035,
            stop_loss_pct=0.010,
            fee_pct=0.00305,
            max_hold_bars=8,
            trailing_schedule=[(1.2, 0.6), (2.0, 0.8)],
            entry_signal_fn=lambda bar, hist: kibot_scanner_signal_fn(bar, hist, min_confidence=0.70),
        )
        print(f"  {pair:10s}: OOS Win Rate: {wf_res.oos_win_rate*100:5.1f}%, OOS Exp: {wf_res.oos_expectancy_pct*100:+.3f}%, Viable: {wf_res.viable}")
        if wf_res.oos_win_rate > 0:
            wf_wins.append(wf_res.oos_win_rate)

    avg_oos_wr = sum(wf_wins) / len(wf_wins) * 100 if wf_wins else 0
    print(f"\n>> Average Walk-Forward OOS Win Rate: {avg_oos_wr:.2f}%")


if __name__ == "__main__":
    main()
