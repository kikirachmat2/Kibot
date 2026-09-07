"""Live Trading Readiness Evaluator for Sovereign KiBot.

Evaluates whether the APPROVED shadow variant has gathered sufficient, statistically
valid paper trading proof across 5 quantitative criteria to safely unlock live capital:
1. Sample Size: N >= 30 closed trades
2. Profit Factor: PF >= 1.50 (Gross Profit / Gross Loss net of fees)
3. Net Win Rate: WR >= 45.0%
4. Max Drawdown: MDD <= 6.0% from peak equity
5. Time Diversity: Spread across >= 10 distinct calendar days

Consequence on passing: Unlocks '🟡 SIAP SOFT LAUNCH' (micro-capital testing)
before any full live deployment is permitted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT_DIR / "state"
TRADE_HISTORY_DIR = STATE_DIR / "trade_history"
PAPER_EQUITY_APPROVED_FILE = STATE_DIR / "paper_equity_approved.json"
READINESS_STATE_FILE = STATE_DIR / "readiness_milestones.json"

WIB = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))
logger = logging.getLogger("KiBot.LiveReadiness")

TARGET_SAMPLE_SIZE = 30
TARGET_PROFIT_FACTOR = 1.50
TARGET_WIN_RATE_PCT = 45.0
MAX_DRAWDOWN_LIMIT_PCT = 6.0
TARGET_CALENDAR_DAYS = 10
MILESTONES = [10, 20, 30, 50]


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Failed reading JSON %s: %s", path, exc)
    return default


def _format_idr(val: Any) -> str:
    try:
        return f"Rp {float(val):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _progress_bar(current: int, target: int, width: int = 15) -> str:
    ratio = min(1.0, max(0.0, float(current) / max(1, target)))
    filled = int(round(ratio * width))
    bar = "█" * filled + "░" * (width - filled)
    pct = ratio * 100.0
    return f"[{bar}] {current}/{target} ({pct:.1f}%)"


def evaluate_approved_readiness() -> Dict[str, Any]:
    """Evaluates APPROVED shadow paper trading performance against the 5 criteria."""
    equity_data = _read_json(PAPER_EQUITY_APPROVED_FILE, {})

    bankroll = float(equity_data.get("initial_bankroll_idr", 5000000.0) or 5000000.0)
    current_equity = float(equity_data.get("current_equity_idr", bankroll) or bankroll)
    peak_equity = float(equity_data.get("peak_equity_idr", max(bankroll, current_equity)) or max(bankroll, current_equity))
    overall_dd_pct = float(equity_data.get("overall_drawdown_pct", 0.0) or 0.0)

    trades: List[Dict[str, Any]] = []
    unique_dates = set()
    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    losses = 0

    if TRADE_HISTORY_DIR.exists():
        for file in sorted(TRADE_HISTORY_DIR.glob("paper_*.jsonl")):
            try:
                for line in file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    var_id = str(row.get("variant_id") or "").upper().strip()
                    if var_id != "APPROVED":
                        continue
                    status = str(row.get("status") or row.get("state") or "").upper()
                    if status not in ("CLOSED", "RECONCILED", "FILLED"):
                        continue

                    pnl_idr = float(row.get("realized_pnl_idr") or row.get("net_realized_pnl_idr") or 0.0)
                    pnl_pct = float(row.get("realized_pnl_pct") or 0.0)
                    date_str = str(row.get("date_wib") or "")
                    if not date_str and row.get("timestamp_wib"):
                        date_str = str(row["timestamp_wib"])[:10]
                    if not date_str and row.get("exit_time_wib"):
                        date_str = str(row["exit_time_wib"])[:10]

                    if date_str:
                        unique_dates.add(date_str)

                    trades.append(row)
                    if pnl_idr > 0 or pnl_pct > 0:
                        wins += 1
                        gross_profit += pnl_idr
                    else:
                        losses += 1
                        gross_loss += abs(pnl_idr)
            except Exception as exc:
                logger.debug("Error scanning trade history %s: %s", file, exc)

    total_trades = len(trades)
    win_rate_pct = round((wins / total_trades) * 100.0, 2) if total_trades > 0 else 0.0

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    elif gross_profit > 0:
        profit_factor = 99.99
    else:
        profit_factor = 0.0

    calendar_days_count = len(unique_dates)
    total_pnl_idr = current_equity - bankroll
    net_drawdown_pct = round(overall_dd_pct, 2)

    # 5 Criteria Checks
    c1_sample = total_trades >= TARGET_SAMPLE_SIZE
    c2_pf = profit_factor >= TARGET_PROFIT_FACTOR
    c3_wr = win_rate_pct >= TARGET_WIN_RATE_PCT
    c4_mdd = net_drawdown_pct <= MAX_DRAWDOWN_LIMIT_PCT
    c5_days = calendar_days_count >= TARGET_CALENDAR_DAYS

    all_passed = c1_sample and c2_pf and c3_wr and c4_mdd and c5_days

    if all_passed:
        verdict = "SIAP_SOFT_LAUNCH"
        verdict_badge = "🟡"
        verdict_title = "SIAP SOFT LAUNCH (FASE 1: MODAL MIKRO)"
        verdict_desc = (
            "Memenuhi 5 syarat kelayakan paper trading! Buka live trading HANYA dengan "
            "modal mikro (Rp 50.000 - Rp 100.000 per posisi) selama 15-20 trade live nyata "
            "untuk menguji slippage dan eksekusi orderbook riil sebelum modal penuh dibuka."
        )
    else:
        verdict = "BELUM_SIAP"
        verdict_badge = "🔴"
        unmet = []
        if not c1_sample:
            unmet.append(f"Sample trade {total_trades}/{TARGET_SAMPLE_SIZE}")
        if not c2_pf:
            unmet.append(f"Profit Factor {profit_factor:.2f}/{TARGET_PROFIT_FACTOR:.2f}")
        if not c3_wr:
            unmet.append(f"Win Rate {win_rate_pct:.1f}%/{TARGET_WIN_RATE_PCT:.1f}%")
        if not c4_mdd:
            unmet.append(f"Max DD {net_drawdown_pct:.1f}%/{MAX_DRAWDOWN_LIMIT_PCT:.1f}%")
        if not c5_days:
            unmet.append(f"Hari kalender {calendar_days_count}/{TARGET_CALENDAR_DAYS}")

        verdict_title = f"BELUM SIAP ({', '.join(unmet[:2])})"
        verdict_desc = (
            f"Kriteria kelayakan belum terpenuhi ({', '.join(unmet)}). "
            "Sistem dilarang membuka live trading. Lanjutkan observasi paper trading."
        )

    criteria_breakdown = {
        "sample_size": {
            "name": "1. Sample Size (N)",
            "target": f">= {TARGET_SAMPLE_SIZE} trades",
            "actual": f"{total_trades} trades",
            "passed": c1_sample,
            "progress_pct": round(min(1.0, total_trades / TARGET_SAMPLE_SIZE) * 100.0, 1),
        },
        "profit_factor": {
            "name": "2. Profit Factor (PF)",
            "target": f">= {TARGET_PROFIT_FACTOR:.2f}",
            "actual": f"{profit_factor:.2f}",
            "passed": c2_pf,
            "progress_pct": round(min(1.0, profit_factor / TARGET_PROFIT_FACTOR) * 100.0, 1),
        },
        "win_rate": {
            "name": "3. Win Rate Net (WR)",
            "target": f">= {TARGET_WIN_RATE_PCT:.1f}%",
            "actual": f"{win_rate_pct:.1f}% ({wins}W / {losses}L)",
            "passed": c3_wr,
            "progress_pct": round(min(1.0, win_rate_pct / TARGET_WIN_RATE_PCT) * 100.0, 1),
        },
        "max_drawdown": {
            "name": "4. Max Drawdown (MDD)",
            "target": f"<= {MAX_DRAWDOWN_LIMIT_PCT:.1f}%",
            "actual": f"{net_drawdown_pct:.2f}%",
            "passed": c4_mdd,
            "progress_pct": 100.0 if c4_mdd else 0.0,
        },
        "calendar_days": {
            "name": "5. Sebaran Hari Kalender",
            "target": f">= {TARGET_CALENDAR_DAYS} hari berbeda",
            "actual": f"{calendar_days_count} hari",
            "passed": c5_days,
            "progress_pct": round(min(1.0, calendar_days_count / TARGET_CALENDAR_DAYS) * 100.0, 1),
        },
    }

    return {
        "evaluated_at": datetime.now(WIB).isoformat(),
        "variant_id": "APPROVED",
        "verdict": verdict,
        "verdict_badge": verdict_badge,
        "verdict_title": verdict_title,
        "verdict_desc": verdict_desc,
        "all_passed": all_passed,
        "metrics": {
            "bankroll_idr": bankroll,
            "current_equity_idr": current_equity,
            "peak_equity_idr": peak_equity,
            "total_pnl_idr": total_pnl_idr,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate_pct,
            "profit_factor": profit_factor,
            "gross_profit_idr": gross_profit,
            "gross_loss_idr": gross_loss,
            "max_drawdown_pct": net_drawdown_pct,
            "calendar_days_count": calendar_days_count,
            "unique_dates": sorted(list(unique_dates)),
        },
        "criteria": criteria_breakdown,
    }


def format_readiness_scorecard(eval_data: Dict[str, Any]) -> str:
    """Formats human-readable terminal / Telegram scorecard."""
    m = eval_data.get("metrics", {})
    crit = eval_data.get("criteria", {})
    badge = eval_data.get("verdict_badge", "⚪")
    title = eval_data.get("verdict_title", "UNKNOWN")
    desc = eval_data.get("verdict_desc", "")

    total = m.get("total_trades", 0)
    pf = m.get("profit_factor", 0.0)
    wr = m.get("win_rate_pct", 0.0)
    mdd = m.get("max_drawdown_pct", 0.0)
    days = m.get("calendar_days_count", 0)

    s1 = "✅" if crit.get("sample_size", {}).get("passed") else "❌"
    s2 = "✅" if crit.get("profit_factor", {}).get("passed") else "❌"
    s3 = "✅" if crit.get("win_rate", {}).get("passed") else "❌"
    s4 = "✅" if crit.get("max_drawdown", {}).get("passed") else "❌"
    s5 = "✅" if crit.get("calendar_days", {}).get("passed") else "❌"

    bar = _progress_bar(total, TARGET_SAMPLE_SIZE, width=15)
    pnl = m.get("total_pnl_idr", 0.0)
    pnl_str = f"+{_format_idr(pnl)}" if pnl > 0 else _format_idr(pnl)

    dates_str = ", ".join(m.get("unique_dates", [])[-5:]) or "Belum ada"

    return f"""========================================================================================
                       KIBOT LIVE TRADING READINESS SCORECARD
========================================================================================
Varian Evaluasi: APPROVED (Simulasi Gerbang Live Nyata)
Status Akhir   : {badge} {title}

PROGRESS 5 KRITERIA KELAYAKAN:
{s1} 1. Sample Size      : {bar}
{s2} 2. Profit Factor    : {pf:.2f} / {TARGET_PROFIT_FACTOR:.2f} target (Gross: {_format_idr(m.get('gross_profit_idr', 0))} / {_format_idr(m.get('gross_loss_idr', 0))})
{s3} 3. Win Rate Net     : {wr:.1f}% / {TARGET_WIN_RATE_PCT:.1f}% target ({m.get('wins', 0)}W / {m.get('losses', 0)}L)
{s4} 4. Max Drawdown     : {mdd:.2f}% / {MAX_DRAWDOWN_LIMIT_PCT:.1f}% batas aman
{s5} 5. Sebaran Hari     : {days} / {TARGET_CALENDAR_DAYS} hari kalender berbeda ({dates_str})

DETAIL EKUITAS & SIMULASI APPROVED:
• Modal Awal        : {_format_idr(m.get('bankroll_idr', 5000000.0))}
• Nilai Saat Ini    : {_format_idr(m.get('current_equity_idr', 5000000.0))} (Net PnL: {pnl_str})
• Rekor Tertinggi   : {_format_idr(m.get('peak_equity_idr', 5000000.0))}

TAHAP BERIKUTNYA SAAT LOLOS:
🟡 SOFT LAUNCH (Alokasi mikro Rp 50.000 - Rp 100.000 / trade selama 15 trade live)
untuk membuktikan ketahanan slippage riil & likuiditas orderbook sebelum modal penuh.

KESIMPULAN OPERATOR:
{desc}
========================================================================================"""


def check_and_notify_milestones(eval_data: Dict[str, Any], send_telegram: bool = False) -> Optional[Dict[str, Any]]:
    """Checks for trade milestone alerts or readiness status transition."""
    state = _read_json(READINESS_STATE_FILE, {
        "last_milestone_n": 0,
        "last_verdict": "BELUM_SIAP",
        "last_alert_at": 0.0,
    })

    m = eval_data.get("metrics", {})
    total_trades = m.get("total_trades", 0)
    current_verdict = eval_data.get("verdict", "BELUM_SIAP")

    last_n = int(state.get("last_milestone_n", 0) or 0)
    last_verdict = str(state.get("last_verdict", "BELUM_SIAP"))

    alert_triggered = False
    alert_title = ""
    alert_msg = ""
    incident_key = ""

    # 1. Milestone checks (N = 10, 20, 30, 50)
    for ms in MILESTONES:
        if total_trades >= ms and last_n < ms:
            alert_triggered = True
            incident_key = f"READINESS_MILESTONE_{ms}"
            state["last_milestone_n"] = ms
            alert_title = f"🎯 KiBot Milestone Tercapai: {ms} Trades Varian APPROVED"
            alert_msg = (
                f"🎯 **KiBot Live Readiness Milestone: {ms} Trades**\n\n"
                f"• Progress Sample : {total_trades} / {TARGET_SAMPLE_SIZE} trades\n"
                f"• Profit Factor   : {m.get('profit_factor', 0.0):.2f} (Target >= {TARGET_PROFIT_FACTOR:.2f})\n"
                f"• Win Rate Net    : {m.get('win_rate_pct', 0.0):.1f}% ({m.get('wins', 0)}W / {m.get('losses', 0)}L)\n"
                f"• Sebaran Hari    : {m.get('calendar_days_count', 0)} / {TARGET_CALENDAR_DAYS} hari\n"
                f"• Status Saat Ini : {eval_data.get('verdict_badge')} {eval_data.get('verdict_title')}\n\n"
                f"_Jalankan `bin/kibotctl live-readiness` untuk audit detail._"
            )
            break

    # 2. Status transition check (e.g. BELUM_SIAP -> SIAP_SOFT_LAUNCH)
    if not alert_triggered and current_verdict != last_verdict and current_verdict == "SIAP_SOFT_LAUNCH":
        alert_triggered = True
        incident_key = f"READINESS_TRANSITION_{current_verdict}"
        state["last_verdict"] = current_verdict
        alert_title = "🚀 KiBot Kelayakan Terpenuhi: Siap Soft Launch!"
        alert_msg = (
            f"🚀 **KiBot Live Readiness: SIAP SOFT LAUNCH!**\n\n"
            f"Varian APPROVED telah memenuhi SEMUA 5 syarat kelayakan paper trading:\n"
            f"✅ Sample Size : {total_trades} >= {TARGET_SAMPLE_SIZE} trades\n"
            f"✅ Profit Factor : {m.get('profit_factor', 0.0):.2f} >= {TARGET_PROFIT_FACTOR:.2f}\n"
            f"✅ Win Rate : {m.get('win_rate_pct', 0.0):.1f}% >= {TARGET_WIN_RATE_PCT:.1f}%\n"
            f"✅ Max Drawdown : {m.get('max_drawdown_pct', 0.0):.2f}% <= {MAX_DRAWDOWN_LIMIT_PCT:.1f}%\n"
            f"✅ Sebaran Hari : {m.get('calendar_days_count', 0)} >= {TARGET_CALENDAR_DAYS} hari\n\n"
            f"📋 **Rekomendasi Tahap Berikutnya:**\n"
            f"Mulai Soft Launch dengan modal mikro (Rp 50.000 - Rp 100.000/order) "
            f"untuk menguji orderbook live nyata sebelum modal penuh dibuka.\n\n"
            f"_Jalankan `bin/kibotctl live-readiness` untuk detail._"
        )

    if alert_triggered:
        state["last_verdict"] = current_verdict
        state["last_alert_at"] = time.time()
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp_file = READINESS_STATE_FILE.with_suffix(".tmp")
            tmp_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp_file.replace(READINESS_STATE_FILE)
        except Exception as exc:
            logger.error("Failed persisting readiness state: %s", exc)

        if send_telegram and alert_msg:
            try:
                from Core.Support.telegram_throttle import telegram_send
                telegram_send(
                    alert_msg,
                    parse_mode="Markdown",
                    incident_key=incident_key,
                    channel="alerts",
                    min_interval_sec=60,
                )
            except Exception as e:
                logger.error("Failed sending milestone alert to Telegram: %s", e)

        return {"alert_sent": True, "title": alert_title, "incident_key": incident_key}

    return {"alert_sent": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KiBot Live Trading Readiness Evaluator")
    parser.add_argument("--json", action="store_true", help="Output raw JSON analysis")
    parser.add_argument("--send", action="store_true", help="Send milestone/status alert to Telegram if triggered")
    args = parser.parse_args()

    data = evaluate_approved_readiness()

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_readiness_scorecard(data))

    if args.send:
        res = check_and_notify_milestones(data, send_telegram=True)
        if res and res.get("alert_sent"):
            print(f"\n[Telegram Notification]: Alert dispatched ({res.get('incident_key')})")
        else:
            print("\n[Telegram Notification]: No milestone threshold crossed; zero spam preserved.")
