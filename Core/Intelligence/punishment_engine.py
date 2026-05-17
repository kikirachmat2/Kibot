"""Punishment Engine — adaptive quarantine for under-performing strategies.

Tracks per-strategy loss streaks and enforces quarantine periods.
A strategy that hits consecutive stop-losses or exceeds daily drawdown
threshold is quarantined for a minimum cooling period before re-evaluation.

Persistence: state is stored in state/punishment_state.json.
No external calls, deterministic.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_STATE_FILE = Path("state/punishment_state.json")

# Quarantine rules
LOSS_STREAK_LIMIT = 3           # consecutive losses → quarantine
MAX_DAILY_DRAWDOWN = 0.03       # 3% daily drawdown → quarantine
QUARANTINE_SECONDS = 3600 * 4  # 4-hour quarantine window
SEVERITY_DECAY_PER_WIN = 0.2    # each win reduces severity by this much


@dataclass
class StrategyRecord:
    strategy_id: str
    loss_streak: int = 0
    daily_pnl: float = 0.0       # cumulative for the current day (fraction)
    quarantine_until: float = 0.0
    severity: float = 0.0        # 0.0 = clean, 1.0 = fully punished
    total_trades: int = 0
    total_wins: int = 0
    total_losses: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def is_quarantined(self) -> bool:
        return time.time() < self.quarantine_until

    @property
    def win_rate(self) -> float:
        return self.total_wins / max(1, self.total_trades)


class PunishmentEngine:
    """Stateful engine that tracks per-strategy punishment and quarantine."""

    def __init__(self, state_file: Path = _STATE_FILE) -> None:
        self._state_file = state_file
        self._records: Dict[str, StrategyRecord] = {}
        self.corrupted_state_active = False
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        strategy_id: str,
        pnl_pct: float,         # fractional P&L of the trade (e.g. +0.015 or -0.01)
    ) -> StrategyRecord:
        """Update strategy record after a trade completes."""
        rec = self._get_or_create(strategy_id)
        rec.total_trades += 1
        rec.daily_pnl += pnl_pct
        rec.last_updated = time.time()

        if pnl_pct >= 0:
            rec.total_wins += 1
            rec.loss_streak = 0
            rec.severity = max(0.0, rec.severity - SEVERITY_DECAY_PER_WIN)
        else:
            rec.total_losses += 1
            rec.loss_streak += 1
            rec.severity = min(1.0, rec.severity + 0.25)

        # Check quarantine triggers
        if rec.loss_streak >= LOSS_STREAK_LIMIT:
            self._quarantine(rec, reason=f"loss streak {rec.loss_streak}")
        elif rec.daily_pnl <= -MAX_DAILY_DRAWDOWN:
            self._quarantine(rec, reason=f"daily drawdown {rec.daily_pnl:.2%}")

        self._save()
        return rec

    def get_status(self, strategy_id: str) -> Dict[str, Any]:
        """Return current punishment status for a strategy."""
        rec = self._get_or_create(strategy_id)
        return {
            "strategy_id": strategy_id,
            "is_quarantined": rec.is_quarantined,
            "severity": round(rec.severity, 3),
            "loss_streak": rec.loss_streak,
            "daily_pnl": round(rec.daily_pnl * 100, 3),
            "quarantine_until": rec.quarantine_until,
            "quarantine_remaining_s": max(0, rec.quarantine_until - time.time()),
            "win_rate": round(rec.win_rate, 3),
            "total_trades": rec.total_trades,
        }

    def reset_daily(self) -> None:
        """Call at the start of each trading day to reset intraday drawdown counters."""
        for rec in self._records.values():
            rec.daily_pnl = 0.0
        self._save()

    def force_clear(self, strategy_id: str) -> None:
        """Operator command to clear quarantine manually."""
        if strategy_id in self._records:
            rec = self._records[strategy_id]
            rec.quarantine_until = 0.0
            rec.loss_streak = 0
            rec.severity = 0.0
            self._save()

    def is_quarantined(self, strategy_id: str) -> bool:
        if getattr(self, "corrupted_state_active", False):
            return True
        return self._get_or_create(strategy_id).is_quarantined

    def get_severity(self, strategy_id: str) -> float:
        if getattr(self, "corrupted_state_active", False):
            return 1.0
        return self._get_or_create(strategy_id).severity

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, strategy_id: str) -> StrategyRecord:
        if strategy_id not in self._records:
            self._records[strategy_id] = StrategyRecord(strategy_id=strategy_id)
        return self._records[strategy_id]

    def _quarantine(self, rec: StrategyRecord, reason: str) -> None:
        rec.quarantine_until = time.time() + QUARANTINE_SECONDS
        rec.severity = 1.0
        import logging
        logging.getLogger(__name__).warning(
            "Strategy %s quarantined for %ds — %s",
            rec.strategy_id, QUARANTINE_SECONDS, reason,
        )

    def _write_baseline(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        baseline = {
            "status": "idle",
            "records": {},
            "quarantined": [],
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "schema_version": 1
        }
        self._state_file.write_text(json.dumps(baseline, indent=2))
        self._records = {}

    def _load(self) -> None:
        if not self._state_file.exists():
            self._write_baseline()
            return
        try:
            raw_text = self._state_file.read_text().strip()
            if not raw_text:
                raise ValueError("Empty state file")
            data = json.loads(raw_text)
            if not isinstance(data, dict):
                raise ValueError("State data must be a JSON dictionary")
            
            # Check schema version
            if "records" in data and "schema_version" in data:
                records_dict = data.get("records", {})
            else:
                # Old schema: dict mapping strategy ID to record fields directly
                records_dict = data
            
            for sid, rec_data in records_dict.items():
                valid_fields = {k: v for k, v in rec_data.items() if k in StrategyRecord.__dataclass_fields__}
                self._records[sid] = StrategyRecord(**valid_fields)
                
        except Exception as e:
            self.corrupted_state_active = True
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Corrupted state file detected: {self._state_file} ({e}). Entering fail-safe quarantine.")
            
            # Backup corrupt file to state/punishment_state.corrupt.<timestamp>.json
            try:
                if self._state_file.exists():
                    timestamp = int(time.time())
                    backup_path = self._state_file.with_name(f"punishment_state.corrupt.{timestamp}.json")
                    backup_path.write_text(self._state_file.read_text())
                    logger.warning(f"Backed up corrupted state to {backup_path}")
            except Exception as backup_err:
                logger.error(f"Failed to backup corrupted state file: {backup_err}")
            
            # Re-write clean baseline
            try:
                self._write_baseline()
            except Exception as write_err:
                logger.error(f"Failed to write baseline after corruption: {write_err}")

    def _save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        quarantined_list = [sid for sid, rec in self._records.items() if rec.is_quarantined]
        payload = {
            "status": "active" if quarantined_list else "idle",
            "records": {sid: asdict(rec) for sid, rec in self._records.items()},
            "quarantined": quarantined_list,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "schema_version": 1
        }
        self._state_file.write_text(json.dumps(payload, indent=2))


# Module-level singleton for import convenience
_engine: Optional[PunishmentEngine] = None


def get_engine() -> PunishmentEngine:
    global _engine
    if _engine is None:
        _engine = PunishmentEngine()
    return _engine
