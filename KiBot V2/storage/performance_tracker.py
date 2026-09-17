"""
Daily Performance Tracker for KiBot V2.
Records daily end-of-day equity snapshots and calculates rolling 7-day performance metrics.
Exposes real-time progress toward the 7-day positive expectancy milestone.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings

logger = logging.getLogger("KiBotV2.PerformanceTracker")


class DailyPerformanceTracker:
    """
    Manages daily equity curve snapshots and rolling 7-day performance analytics.
    Persists snapshots to state/daily_performance_tracker.json.
    """

    def __init__(self, state_file_path: Optional[Path] = None):
        self.state_file = state_file_path or (settings.STATE_DIR / "daily_performance_tracker.json")
        self.snapshots: List[Dict[str, Any]] = []
        self._load_sync()

    def _load_sync(self) -> None:
        """Loads historical snapshots from disk if file exists."""
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    self.snapshots = data
                elif isinstance(data, dict) and "snapshots" in data:
                    self.snapshots = data.get("snapshots", [])
            logger.info(f"[PerformanceTracker] Loaded {len(self.snapshots)} daily snapshots from {self.state_file}")
        except Exception as e:
            logger.warning(f"[PerformanceTracker] Could not load snapshots from {self.state_file}: {e}")

    def _save_sync(self) -> None:
        """Atomically saves snapshots list to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_file.with_suffix(".tmp")
            payload = {
                "version": "1.0.0",
                "last_updated": time.time(),
                "snapshots": self.snapshots,
            }
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(temp_path, self.state_file)
        except Exception as e:
            logger.error(f"[PerformanceTracker] Failed to save snapshots to {self.state_file}: {e}")

    def record_daily_snapshot(
        self,
        total_equity_idr: float,
        cash_idr: float,
        open_positions_count: int,
        unrealized_pnl_idr: float,
        trade_history: Optional[List[Dict[str, Any]]] = None,
        date_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Records or updates a daily snapshot for today's UTC date.
        """
        today = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        trades = trade_history or []
        cumulative_realized_pnl_idr = sum(float(t.get("realized_pnl_idr", 0.0)) for t in trades)

        snapshot = {
            "date": today,
            "timestamp": time.time(),
            "total_equity_idr": round(total_equity_idr, 2),
            "cash_idr": round(cash_idr, 2),
            "open_positions": open_positions_count,
            "unrealized_pnl_idr": round(unrealized_pnl_idr, 2),
            "closed_trades_count": len(trades),
            "cumulative_realized_pnl_idr": round(cumulative_realized_pnl_idr, 2),
        }

        # Update if snapshot for date already exists, otherwise append
        existing_idx = next((i for i, s in enumerate(self.snapshots) if s.get("date") == today), None)
        if existing_idx is not None:
            self.snapshots[existing_idx] = snapshot
        else:
            self.snapshots.append(snapshot)

        self._save_sync()
        return snapshot

    def get_7d_summary(
        self,
        current_equity_idr: float,
        trade_history: Optional[List[Dict[str, Any]]] = None,
        now_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculates rolling 7-day window performance metrics.
        """
        now = now_ts if now_ts is not None else time.time()
        window_start_ts = now - (7 * 86400.0)
        trades = trade_history or []

        # Find snapshots within 7-day window
        window_snapshots = [s for s in self.snapshots if s.get("timestamp", 0.0) >= window_start_ts]

        # Determine baseline equity (first snapshot in window, or earliest recorded, or 10M fallback)
        if window_snapshots:
            baseline_equity = float(window_snapshots[0].get("total_equity_idr", 10_000_000.0))
        elif self.snapshots:
            baseline_equity = float(self.snapshots[0].get("total_equity_idr", 10_000_000.0))
        else:
            baseline_equity = 10_000_000.0

        pnl_7d_idr = round(current_equity_idr - baseline_equity, 2)
        pnl_7d_pct = round((pnl_7d_idr / baseline_equity * 100.0), 2) if baseline_equity > 0 else 0.0

        # Filter trades closed in last 7 days
        trades_7d = [t for t in trades if float(t.get("closed_at", 0.0)) >= window_start_ts]
        trades_7d_count = len(trades_7d)
        wins_7d = [t for t in trades_7d if float(t.get("realized_pnl_idr", 0.0)) > 0]
        losses_7d = [t for t in trades_7d if float(t.get("realized_pnl_idr", 0.0)) < 0]

        win_rate_7d_pct = round(len(wins_7d) / trades_7d_count * 100.0, 1) if trades_7d_count > 0 else 0.0
        gross_profit = sum(float(t.get("realized_pnl_idr", 0.0)) for t in wins_7d)
        gross_loss = abs(sum(float(t.get("realized_pnl_idr", 0.0)) for t in losses_7d))

        if gross_loss > 0:
            profit_factor_7d = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            profit_factor_7d = 99.0
        else:
            profit_factor_7d = 0.0

        # Max drawdown across window snapshots + current equity
        equity_points = [float(s.get("total_equity_idr", 0.0)) for s in window_snapshots] + [current_equity_idr]
        peak = 0.0
        max_dd_pct = 0.0
        for eq in equity_points:
            if eq > peak:
                peak = eq
            elif peak > 0:
                dd = (peak - eq) / peak * 100.0
                if dd > max_dd_pct:
                    max_dd_pct = dd

        equity_curve = [
            {"date": s.get("date"), "equity_idr": s.get("total_equity_idr")}
            for s in self.snapshots[-7:]
        ]

        return {
            "baseline_equity_idr": round(baseline_equity, 2),
            "current_equity_idr": round(current_equity_idr, 2),
            "pnl_7d_idr": pnl_7d_idr,
            "pnl_7d_pct": pnl_7d_pct,
            "trades_7d_count": trades_7d_count,
            "win_rate_7d_pct": win_rate_7d_pct,
            "profit_factor_7d": profit_factor_7d,
            "max_drawdown_7d_pct": round(max_dd_pct, 2),
            "recorded_days": len(self.snapshots),
            "equity_curve": equity_curve,
        }
