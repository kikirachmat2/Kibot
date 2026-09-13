"""
Live Trading Readiness Evaluator for KiBot V2.
Ported from KiBot V1 Core/Intelligence/live_readiness.py.

Evaluates virtual paper trading performance against the 5 canonical quantitative criteria:
1. Sample Size: N >= 30 closed trades
2. Profit Factor: PF >= 1.50 (Gross Profit / Gross Loss net of fees)
3. Net Win Rate: WR >= 45.0%
4. Max Drawdown: MDD <= 6.0% from peak equity
5. Time Diversity: Spread across >= 10 distinct calendar days

Consequence:
- Passing all 5 unlocks '🟡 SIAP SOFT LAUNCH' (micro-capital phase: Rp 50.000 - Rp 100.000).
- This evaluation is STRICTLY READ-ONLY and NEVER flips LIVE_TRADING_ENABLED automatically.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from notifications import telegram_notifier

logger = logging.getLogger("KiBotV2.LiveReadiness")

WIB = timezone(timedelta(hours=7))

TARGET_SAMPLE_SIZE = 30
TARGET_PROFIT_FACTOR = 1.50
TARGET_WIN_RATE_PCT = 45.0
MAX_DRAWDOWN_LIMIT_PCT = 6.0
TARGET_CALENDAR_DAYS = 10
MILESTONES = [10, 20, 30, 50]

class LiveReadinessEvaluator:
    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file
        self.last_milestone_notified: int = 0
        self.last_verdict: str = "BELUM_SIAP"

    def evaluate_trades(
        self,
        trade_history: List[Dict[str, Any]],
        current_equity_idr: float = 10_000_000.0,
        initial_bankroll_idr: float = 10_000_000.0,
        peak_equity_idr: float = 10_000_000.0,
        current_drawdown_pct: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Evaluates the provided closed trade history list against all 5 criteria.
        """
        wins = 0
        losses = 0
        gross_profit = 0.0
        gross_loss = 0.0
        unique_dates = set()

        for tr in trade_history:
            pnl_idr = float(tr.get("realized_pnl_idr") or 0.0)
            pnl_pct = float(tr.get("realized_pnl_pct") or 0.0)
            
            # Extract date in WIB
            exit_ts = tr.get("exit_time") or tr.get("timestamp") or time.time()
            dt_wib = datetime.fromtimestamp(float(exit_ts), WIB)
            date_str = dt_wib.strftime("%Y-%m-%d")
            unique_dates.add(date_str)

            if pnl_idr > 0 or pnl_pct > 0:
                wins += 1
                gross_profit += pnl_idr
            else:
                losses += 1
                gross_loss += abs(pnl_idr)

        total_trades = len(trade_history)
        win_rate_pct = round((wins / total_trades) * 100.0, 2) if total_trades > 0 else 0.0

        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            profit_factor = 99.99
        else:
            profit_factor = 0.0

        calendar_days_count = len(unique_dates)
        net_dd_pct = round(current_drawdown_pct, 2)
        total_pnl_idr = round(current_equity_idr - initial_bankroll_idr, 2)

        # Evaluate 5 Quantitative Criteria
        c1_sample = total_trades >= TARGET_SAMPLE_SIZE
        c2_pf = profit_factor >= TARGET_PROFIT_FACTOR
        c3_wr = win_rate_pct >= TARGET_WIN_RATE_PCT
        c4_mdd = net_dd_pct <= MAX_DRAWDOWN_LIMIT_PCT
        c5_days = calendar_days_count >= TARGET_CALENDAR_DAYS

        all_passed = c1_sample and c2_pf and c3_wr and c4_mdd and c5_days

        if all_passed:
            verdict = "SIAP_SOFT_LAUNCH"
            verdict_badge = "🟡"
            verdict_title = "SIAP SOFT LAUNCH (FASE 1: MODAL MIKRO)"
            verdict_desc = (
                "Memenuhi seluruh 5 kriteria kelayakan paper trading! "
                "Direkomendasikan buka live trading HANYA dengan modal mikro "
                "(Rp 50.000 - Rp 100.000 per posisi) untuk menguji slippage dan orderbook riil."
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
                unmet.append(f"Max DD {net_dd_pct:.1f}%/{MAX_DRAWDOWN_LIMIT_PCT:.1f}%")
            if not c5_days:
                unmet.append(f"Hari kalender {calendar_days_count}/{TARGET_CALENDAR_DAYS}")

            verdict_title = f"BELUM SIAP ({', '.join(unmet[:2])})"
            verdict_desc = (
                f"Kriteria belum terpenuhi: {', '.join(unmet)}. "
                "Live execution dilarang. Lanjutkan pengumpulan data paper trading."
            )

        criteria = {
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
                "actual": f"{net_dd_pct:.2f}%",
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

        result = {
            "evaluated_at": datetime.now(WIB).isoformat(),
            "verdict": verdict,
            "verdict_badge": verdict_badge,
            "verdict_title": verdict_title,
            "verdict_desc": verdict_desc,
            "all_passed": all_passed,
            "metrics": {
                "initial_bankroll_idr": initial_bankroll_idr,
                "current_equity_idr": current_equity_idr,
                "peak_equity_idr": peak_equity_idr,
                "total_pnl_idr": total_pnl_idr,
                "total_trades": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate_pct": win_rate_pct,
                "profit_factor": profit_factor,
                "gross_profit_idr": round(gross_profit, 2),
                "gross_loss_idr": round(gross_loss, 2),
                "max_drawdown_pct": net_dd_pct,
                "calendar_days_count": calendar_days_count,
                "unique_dates": sorted(list(unique_dates)),
            },
            "criteria": criteria,
        }

        self._check_and_notify_milestones(result)
        return result

    def _check_and_notify_milestones(self, eval_res: Dict[str, Any]) -> None:
        """Sends non-blocking Telegram notifications for milestones and status changes."""
        total_trades = eval_res["metrics"]["total_trades"]
        verdict = eval_res["verdict"]

        # 1. Milestone Check (10, 20, 30, 50 closed trades)
        for m in MILESTONES:
            if total_trades >= m > self.last_milestone_notified:
                self.last_milestone_notified = m
                telegram_notifier.send_alert_non_blocking(
                    event_type="READINESS_MILESTONE",
                    title=f"🎯 GO-LIVE MILESTONE REACHED: {m} Closed Trades",
                    message=(
                        f"Paper trading has reached {m} closed trades milestone!\n\n"
                        f"• Win Rate: {eval_res['metrics']['win_rate_pct']}%\n"
                        f"• Profit Factor: {eval_res['metrics']['profit_factor']}\n"
                        f"• Max Drawdown: {eval_res['metrics']['max_drawdown_pct']}%\n"
                        f"• Calendar Days: {eval_res['metrics']['calendar_days_count']}/10\n"
                        f"• Status: {eval_res['verdict_title']}"
                    ),
                    severity="INFO",
                    details=eval_res["criteria"],
                )
                break

        # 2. Verdict Status Change Check
        if verdict != self.last_verdict:
            old = self.last_verdict
            self.last_verdict = verdict
            severity = "SUCCESS" if verdict == "SIAP_SOFT_LAUNCH" else "WARNING"
            telegram_notifier.send_alert_non_blocking(
                event_type="GO_LIVE_STATUS_CHANGED",
                title=f"{eval_res['verdict_badge']} LIVE READINESS STATUS: {verdict}",
                message=(
                    f"Readiness verdict transitioned from {old} to {verdict}!\n\n"
                    f"{eval_res['verdict_desc']}\n\n"
                    f"⚠️ Note: LIVE_TRADING_ENABLED remains strictly manual."
                ),
                severity=severity,
                details=eval_res["metrics"],
            )

live_readiness_evaluator = LiveReadinessEvaluator()
