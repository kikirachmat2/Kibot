#!/usr/bin/env python3
"""
Cleanup Script: Archive 12 Corrupted Records from 2026-08-07 and Recalculate True Equity Curves
KiBot Sovereign Trinity Mesh
"""

import json
import glob
from pathlib import Path
from datetime import datetime, timezone

def run_cleanup():
    root = Path("/home/ubuntu/KiBot") if Path("/home/ubuntu/KiBot").exists() else Path(".")
    history_dir = root / "state" / "trade_history"
    archive_dir = history_dir / "archive_equity_corruption_2026-08-18"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_file = archive_dir / "corrupted_trades_2026-08-07.jsonl"

    corrupted_records = []
    target_files = [
        history_dir / "paper_2026-08-07.jsonl",
        history_dir / "paper_aggressive_2026-08-07.jsonl",
        history_dir / "paper_conservative_2026-08-07.jsonl"
    ]

    for p in target_files:
        if not p.exists():
            continue
        valid_lines = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    pnl_pct = abs(float(rec.get("realized_pnl_pct", 0.0) or 0.0))
                    # The 12 corrupt records all have absurd pnl_pct > 10,000%
                    if pnl_pct > 10000.0:
                        corrupted_records.append(rec)
                    else:
                        valid_lines.append(line)
                except Exception:
                    valid_lines.append(line)

        # Rewrite cleaned file atomically
        tmp_path = p.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for l in valid_lines:
                f.write(l)
        tmp_path.replace(p)

    print(f"Archived {len(corrupted_records)} corrupted records to {archive_file}.")

    # Write archive file
    with open(archive_file, "w", encoding="utf-8") as f:
        for rec in corrupted_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Write README.md in archive directory
    readme_file = archive_dir / "README.md"
    readme_content = """# Archive: Corrupted Paper Trades from 2026-08-07

## Overview
This archive contains 12 paper trade records (4 pairs x 3 variants) generated on 2026-08-07 at ~23:30 WIB.

## Root Cause
- Core/Scanner/engine.py mapped expected_net_pct (yield percentage values like 4.422%, 82.6%, 129.7%, 97.2%) to the generic price field in LEADLAG_ALPHA signals.
- autonomous_director.py and paper_trade_tracker.py accepted these generic percentage numbers as entry prices in IDR.
- When trades closed, exit prices were fetched from real Indodax IDR tickers (e.g. BTC=Rp1,153,838,000), producing astronomical PnL (+Rp 65.2 Trillion) that contaminated paper_equity.json, paper_equity_conservative.json, and paper_equity_aggressive.json.

## Resolution
- Root cause fixed in commit 758d91b (engine.py, leadlag_alpha.py, paper_trade_tracker.py, autonomous_director.py).
- Valuation sanity checks and circuit breaker (>500% PnL) added.
- These 12 corrupted records are preserved here for historical audit and excluded from active trade history.
- Cumulative equity curves recalculated from all remaining valid trades.
"""
    readme_file.write_text(readme_content, encoding="utf-8")

    # 2. Recompute accurate cumulative statistics from all remaining valid records
    bankrolls = {
        "DEFAULT": 10_000_000.0,
        "CONSERVATIVE": 10_000_000.0,
        "AGGRESSIVE": 10_000_000.0,
        "AI_ASSISTED": 10_000_000.0,
        "AI_RANKER": 5_000_000.0
    }

    totals = {var: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0} for var in bankrolls}

    for fn in sorted(glob.glob(str(history_dir / "*.jsonl"))):
        if "archive" in fn:
            continue
        with open(fn, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    var = rec.get("variant_id", "DEFAULT")
                    if var not in totals:
                        totals[var] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0}

                    # Check for invalid valuation
                    is_invalid = bool(rec.get("is_invalid_valuation")) or rec.get("exit_reason") == "TIMEOUT_PRICE_UNAVAILABLE"
                    if is_invalid:
                        continue

                    pnl = float(rec.get("realized_pnl_idr", 0.0) or 0.0)
                    totals[var]["trades"] += 1
                    totals[var]["pnl"] += pnl
                    if pnl > 0:
                        totals[var]["wins"] += 1
                    elif pnl < 0:
                        totals[var]["losses"] += 1
                except Exception:
                    pass

    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    state_dir = root / "state"

    # 3. Update the equity files
    equity_files = {
        "DEFAULT": state_dir / "paper_equity.json",
        "CONSERVATIVE": state_dir / "paper_equity_conservative.json",
        "AGGRESSIVE": state_dir / "paper_equity_aggressive.json",
    }

    print("\n=== RECALCULATED TRUE EQUITY CURVES ===")
    for var, eq_file in equity_files.items():
        stats = totals[var]
        tot_trades = stats["trades"]
        wins = stats["wins"]
        losses = stats["losses"]
        tot_pnl = round(stats["pnl"], 2)
        bankroll = bankrolls.get(var, 10_000_000.0)
        cur_equity = round(bankroll + tot_pnl, 2)
        win_rate = round((wins / tot_trades) * 100.0, 2) if tot_trades > 0 else 0.0

        eq_payload = {
            "variant_id": var,
            "initial_bankroll_idr": bankroll,
            "current_equity_idr": cur_equity,
            "total_pnl_idr": tot_pnl,
            "total_paper_trades": tot_trades,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate_pct": win_rate,
            "updated_at": now_iso,
            "_corrected_at": now_iso,
            "_correction_reason": "Recalculated true cumulative PnL from all valid trade_history records after archiving 12 corrupted records from 2026-08-07 (commit 758d91b)"
        }

        eq_file.write_text(json.dumps(eq_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[{var:12s}] Trades: {tot_trades:6,d} | Wins: {wins:5,d} | Losses: {losses:5,d} | WinRate: {win_rate:5.2f}% | PnL: Rp{tot_pnl:+14,.2f} | Equity: Rp{cur_equity:14,.2f}")

if __name__ == "__main__":
    run_cleanup()
