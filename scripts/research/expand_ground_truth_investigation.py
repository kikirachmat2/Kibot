"""Expanded Ground Truth Investigation: Multi-Pair Statistical Validation & Volume Sweep.

Answers:
1. Exact N trades per pair for EV claim verification (marking N < 20-30 as underpowered).
2. Broadened backtest to Top 35 pairs by signal count across full 114-day history.
3. Volatility vs Stagnation correlation check across the larger sample.
4. Empirical sweep of 24h volume threshold (Rp 100jt, 250jt, 500jt, 1M, 2M) on EV.
"""

import os
import json
import time
import requests
from collections import Counter
from pathlib import Path
from typing import Dict, List, Any, Tuple
from Core.Research.backtest_engine import (
    Bar,
    run_backtest,
    load_ground_truth_signals,
    create_ground_truth_signal_fn,
)

CACHE_DIR = Path("scratch/candles_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FROM_TS = 1779000000  # May 15, 2026
TO_TS   = 1788634000  # Sep 06, 2026


def fetch_cached_candles(symbol: str) -> List[Bar]:
    """Fetch 15m candles from Indodax TradingView API v2, with local disk caching."""
    clean_sym = symbol.replace("/", "").replace("_", "").upper()
    cache_file = CACHE_DIR / f"{clean_sym}_15m.json"

    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                rows = json.load(f)
            return [
                Bar(
                    timestamp=float(r["t"]),
                    open=float(r["o"]),
                    high=float(r["h"]),
                    low=float(r["l"]),
                    close=float(r["c"]),
                    volume=float(r["v"]),
                )
                for r in rows
            ]
        except Exception:
            pass

    url = f"https://indodax.com/tradingview/history_v2?symbol={clean_sym}&tf=15&from={FROM_TS}&to={TO_TS}"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        
        bars = []
        cache_data = []
        for d in data:
            if d.get("Close") is None:
                continue
            t = float(d["Time"])
            o = float(d["Open"])
            h = float(d["High"])
            l = float(d["Low"])
            c = float(d["Close"])
            v = float(d.get("Volume") or 0.0)
            bars.append(Bar(timestamp=t, open=o, high=h, low=l, close=c, volume=v))
            cache_data.append({"t": t, "o": o, "h": h, "l": l, "c": c, "v": v})

        with open(cache_file, "w") as f:
            json.dump(cache_data, f)

        return bars
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return []


def main():
    print("=" * 80)
    print("EXPANDED GROUND TRUTH INVESTIGATION ACROSS TOP 35 PAIRS (114 DAYS)")
    print("=" * 80)

    # 1. Load Ground Truth signals
    signals_map = load_ground_truth_signals("state/ground_truth_signals.json")
    pair_counts = Counter(
        str(sig.get("symbol") or "").upper().strip()
        for sigs in signals_map.values()
        for sig in sigs
    )
    
    top_35_pairs = [p for p, _ in pair_counts.most_common(35)]
    print(f"Loaded ground truth signals. Evaluating top {len(top_35_pairs)} pairs...\n")

    # Store results per pair
    results: List[Dict[str, Any]] = []

    for idx, pair in enumerate(top_35_pairs, 1):
        sigs = signals_map.get(pair, [])
        bars = fetch_cached_candles(pair)

        if len(bars) < 100:
            print(f"[{idx:2d}/{len(top_35_pairs)}] {pair:12s}: INSUFFICIENT CANDLES ({len(bars)} bars)")
            continue

        sig_fn = create_ground_truth_signal_fn(sigs, tolerance_seconds=900.0)

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

        # Calculate average 24h volatility (96-bar high-low range %) and daily turnover IDR
        volatilities = []
        turnovers_idr = []
        for i in range(96, len(bars), 24):  # sample every 6 hours
            sub = bars[i - 96 : i]
            sub_high = max(b.high for b in sub)
            sub_low = min(b.low for b in sub)
            sub_close = sub[-1].close
            if sub_low > 0 and sub_close > 0:
                rng_pct = (sub_high - sub_low) / sub_low * 100.0
                volatilities.append(rng_pct)
            sub_turnover = sum(b.volume * b.close for b in sub)
            turnovers_idr.append(sub_turnover)

        avg_volatility_24h = sum(volatilities) / len(volatilities) if volatilities else 0.0
        avg_turnover_24h_idr = sum(turnovers_idr) / len(turnovers_idr) if turnovers_idr else 0.0

        n = res.total_trades
        wr = res.win_rate * 100
        ev = res.expectancy_pct * 100

        # Sample power tag
        if n == 0:
            power_tag = "NO TRADES"
        elif n < 20:
            power_tag = "UNDERPOWERED (N<20)"
        elif n < 30:
            power_tag = "LOW POWER (N<30)"
        else:
            power_tag = "VALID (N>=30)"

        item = {
            "pair": pair,
            "signals": len(sigs),
            "bars": len(bars),
            "trades_N": n,
            "wins": res.winning_trades,
            "losses": res.losing_trades,
            "win_rate_pct": round(wr, 1),
            "ev_pct": round(ev, 3),
            "power_tag": power_tag,
            "avg_volatility_24h_pct": round(avg_volatility_24h, 2),
            "avg_turnover_24h_idr_mil": round(avg_turnover_24h_idr / 1_000_000, 1),
            "exits": res.exit_reasons,
            "trades": res.trades,
            "bars_data": bars,
            "signals_data": sigs,
        }
        results.append(item)

        print(
            f"[{idx:2d}/{len(top_35_pairs)}] {pair:12s}: N={n:3d} | WR={wr:5.1f}% | EV={ev:+6.3f}% | "
            f"Vol={avg_volatility_24h:4.1f}% | Turn={avg_turnover_24h_idr/1e6:7.1f}M | [{power_tag}]"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # REPORT 1: Exact N Breakdown for Positive vs Negative EV Pairs
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ANALYSIS 1: DETAILED SAMPLE SIZE (N) AUDIT FOR ALL TESTED PAIRS")
    print("=" * 80)

    # Sort by EV descending
    sorted_by_ev = sorted(results, key=lambda x: x["ev_pct"], reverse=True)
    pos_ev = [r for r in sorted_by_ev if r["ev_pct"] > 0]
    neg_ev = [r for r in sorted_by_ev if r["ev_pct"] <= 0 and r["trades_N"] > 0]

    print(f"\n--- PAIRS DENGAN EV POSITIF (Total {len(pos_ev)} pairs) ---")
    for r in pos_ev:
        warn = " [!] " if "UNDERPOWERED" in r["power_tag"] else "     "
        print(
            f"{warn}{r['pair']:12s}: N={r['trades_N']:3d} (Wins={r['wins']:2d}, Loss={r['losses']:2d}) | "
            f"WR={r['win_rate_pct']:5.1f}% | EV={r['ev_pct']:+6.3f}% | {r['power_tag']}"
        )

    print(f"\n--- PAIRS DENGAN EV NEGATIF (Total {len(neg_ev)} pairs) ---")
    for r in neg_ev[:15]:
        print(
            f"     {r['pair']:12s}: N={r['trades_N']:3d} (Wins={r['wins']:2d}, Loss={r['losses']:2d}) | "
            f"WR={r['win_rate_pct']:5.1f}% | EV={r['ev_pct']:+6.3f}% | {r['power_tag']}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # REPORT 2: Volatility vs Stagnation Hypothesis Test
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ANALYSIS 2: HIPOTESIS VOLATILE VS STAGNAN (SAMPLE BESAR)")
    print("=" * 80)

    valid_trades = [r for r in results if r["trades_N"] >= 10]
    if valid_trades:
        median_vol = sorted(r["avg_volatility_24h_pct"] for r in valid_trades)[len(valid_trades) // 2]
        high_vol_pairs = [r for r in valid_trades if r["avg_volatility_24h_pct"] >= median_vol]
        low_vol_pairs  = [r for r in valid_trades if r["avg_volatility_24h_pct"] < median_vol]

        hv_n = sum(r["trades_N"] for r in high_vol_pairs)
        hv_wins = sum(r["wins"] for r in high_vol_pairs)
        hv_wr = hv_wins / hv_n * 100 if hv_n else 0
        hv_ev = sum(r["ev_pct"] * r["trades_N"] for r in high_vol_pairs) / hv_n if hv_n else 0

        lv_n = sum(r["trades_N"] for r in low_vol_pairs)
        lv_wins = sum(r["wins"] for r in low_vol_pairs)
        lv_wr = lv_wins / lv_n * 100 if lv_n else 0
        lv_ev = sum(r["ev_pct"] * r["trades_N"] for r in low_vol_pairs) / lv_n if lv_n else 0

        print(f"Median 24h Volatility: {median_vol:.2f}%")
        print(f"High Volatility Group (>={median_vol:.2f}%): {len(high_vol_pairs)} pairs | Total N={hv_n} | Win Rate={hv_wr:.2f}% | Weighted EV={hv_ev:+.3f}%")
        print(f"Low Volatility Group  (< {median_vol:.2f}%): {len(low_vol_pairs)} pairs | Total N={lv_n} | Win Rate={lv_wr:.2f}% | Weighted EV={lv_ev:+.3f}%")

    # ─────────────────────────────────────────────────────────────────────────
    # REPORT 3: Volume 24h Minimum Threshold Sweep (Empirical Testing)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("ANALYSIS 3: SWEEP AMBANG BATAS VOLUME 24H (EMPIRICAL DATA)")
    print("=" * 80)

    thresholds_idr = [
        0,              # No filter (Baseline)
        100_000_000,    # Rp 100 Juta
        250_000_000,    # Rp 250 Juta
        500_000_000,    # Rp 500 Juta
        1_000_000_000,  # Rp 1 Miliar
        2_000_000_000,  # Rp 2 Miliar
        5_000_000_000,  # Rp 5 Miliar
    ]

    # Pre-build signal entries with rolling 24h volume for all pairs
    all_trade_entries = []

    for r in results:
        bars = r["bars_data"]
        sigs = r["signals_data"]
        if len(bars) < 100:
            continue

        sig_ts_set = set(float(s["ts"]) for s in sigs if "ts" in s)

        # Run custom backtest capturing entry volume
        # We simulate with 24h volume attached to each trade
        # Compute rolling 96-bar volume
        rolling_vol_idr = []
        cur_sum = 0.0
        for i, b in enumerate(bars):
            vol_idr = b.volume * b.close
            cur_sum += vol_idr
            if i >= 96:
                cur_sum -= bars[i - 96].volume * bars[i - 96].close
            rolling_vol_idr.append(cur_sum if i >= 96 else cur_sum * (96 / (i + 1)))

        sig_fn = create_ground_truth_signal_fn(sigs, tolerance_seconds=900.0)
        res = run_backtest(
            bars,
            strategy_id=f"SWEEP_{r['pair']}",
            take_profit_pct=0.035,
            stop_loss_pct=0.010,
            fee_pct=0.00305,
            max_hold_bars=8,
            trailing_schedule=[(1.2, 0.6), (2.0, 0.8), (4.0, 1.5)],
            entry_signal_fn=sig_fn,
        )

        for trade in res.trades:
            # Find bar index corresponding to trade.entry_time
            # Binary search
            entry_ts = trade.entry_time
            # Find closest bar
            b_idx = min(range(len(bars)), key=lambda k: abs(bars[k].timestamp - entry_ts))
            entry_vol_24h = rolling_vol_idr[b_idx]
            all_trade_entries.append({
                "pair": r["pair"],
                "pnl_pct": trade.pnl_pct,
                "won": trade.pnl_pct >= 0,
                "vol_24h_idr": entry_vol_24h,
                "exit_reason": trade.exit_reason,
            })

    total_pool = len(all_trade_entries)
    print(f"Total Trade Pool Evaluated across All Pairs: {total_pool} trades\n")
    print(f"{'Threshold (IDR)':22s} | {'Trades N':8s} | {'Wins':6s} | {'Win Rate':9s} | {'EV %':9s} | {'Profit Factor':13s} | {'Filtered Out':12s}")
    print("-" * 95)

    for thresh in thresholds_idr:
        qualified = [t for t in all_trade_entries if t["vol_24h_idr"] >= thresh]
        n_q = len(qualified)
        if n_q == 0:
            continue
        wins_q = sum(1 for t in qualified if t["won"])
        losses_q = n_q - wins_q
        wr_q = wins_q / n_q * 100
        
        gross_wins = sum(t["pnl_pct"] for t in qualified if t["won"])
        gross_losses = sum(abs(t["pnl_pct"]) for t in qualified if not t["won"])
        pf_q = gross_wins / gross_losses if gross_losses > 0 else float("inf")
        
        avg_w = gross_wins / wins_q if wins_q > 0 else 0
        avg_l = gross_losses / losses_q if losses_q > 0 else 0
        ev_q = (wr_q / 100 * avg_w) - ((1 - wr_q / 100) * avg_l)

        filtered_pct = (total_pool - n_q) / total_pool * 100
        thresh_label = "None (Baseline)" if thresh == 0 else f">= Rp {thresh/1e6:,.0f} Juta" if thresh < 1e9 else f">= Rp {thresh/1e9:,.1f} Miliar"

        print(
            f"{thresh_label:22s} | {n_q:8d} | {wins_q:6d} | {wr_q:8.2f}% | {ev_q*100:+8.3f}% | {pf_q:13.2f} | {filtered_pct:10.1f}%"
        )


if __name__ == "__main__":
    main()
