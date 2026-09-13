"""Official Deposit Event Manager — handles manual operator balance top-up notifications.

Ensures manual top-ups are officially logged and distinguished from trading PnL,
allowing CapitalGovernor to increase baseline equity without triggering drift safeguards.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("KiBot.DepositEventManager")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT_DIR / "state"
DEPOSIT_LOG_FILE = STATE_DIR / "deposit_events.jsonl"
WIB_TZ = timezone(timedelta(hours=7))


def _now_wib() -> datetime:
    return datetime.now(WIB_TZ)


class DepositEventManager:
    def __init__(self, log_file: Optional[Path] = None):
        self.log_file = Path(log_file) if log_file is not None else (STATE_DIR / "deposit_events.jsonl")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def record_deposit(self, amount_idr: float, note: str = "") -> Dict[str, Any]:
        """Record an official operator balance deposit event."""
        if amount_idr <= 0:
            raise ValueError("Deposit amount_idr must be greater than 0.")

        now_iso = _now_wib().isoformat()
        event_id = f"dep_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        event_record = {
            "event_id": event_id,
            "event_type": "OPERATOR_DEPOSIT",
            "amount_idr": round(float(amount_idr), 2),
            "note": str(note or "Operator manual top-up"),
            "reconciled": False,
            "reconciled_at": None,
            "timestamp_wib": now_iso,
            "ts": time.time(),
        }

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_record, ensure_ascii=False) + "\n")

        logger.info(f"💰 [DepositEvent] Recorded deposit notification of Rp{amount_idr:,.2f} IDR (ID: {event_id})")
        return event_record

    def record_withdrawal(self, amount_idr: float, note: str = "") -> Dict[str, Any]:
        """Record an official operator balance withdrawal event."""
        if amount_idr <= 0:
            raise ValueError("Withdrawal amount_idr must be greater than 0.")

        now_iso = _now_wib().isoformat()
        event_id = f"wd_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        event_record = {
            "event_id": event_id,
            "event_type": "OPERATOR_WITHDRAWAL",
            "amount_idr": round(float(amount_idr), 2),
            "note": str(note or "Operator manual withdrawal"),
            "reconciled": False,
            "reconciled_at": None,
            "timestamp_wib": now_iso,
            "ts": time.time(),
        }

        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event_record, ensure_ascii=False) + "\n")

        logger.info(f"💸 [DepositEvent] Recorded withdrawal notification of Rp{amount_idr:,.2f} IDR (ID: {event_id})")
        return event_record

    def get_all_records(self) -> List[Dict[str, Any]]:
        """Load all transfer events (deposits and withdrawals) from log file."""
        records: List[Dict[str, Any]] = []
        if not self.log_file.exists():
            return records
        try:
            for line in self.log_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if isinstance(record, dict) and record.get("event_type") in {"OPERATOR_DEPOSIT", "OPERATOR_WITHDRAWAL"}:
                        records.append(record)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error reading transfer log file: {e}")
        return records

    def get_all_deposits(self) -> List[Dict[str, Any]]:
        """Load all deposit events from deposit_events.jsonl."""
        return [r for r in self.get_all_records() if r.get("event_type") == "OPERATOR_DEPOSIT"]

    def get_all_withdrawals(self) -> List[Dict[str, Any]]:
        """Load all withdrawal events from deposit_events.jsonl."""
        return [r for r in self.get_all_records() if r.get("event_type") == "OPERATOR_WITHDRAWAL"]

    def get_unreconciled_deposits(self) -> List[Dict[str, Any]]:
        """Return all deposit events that have not yet been reconciled by CapitalGovernor."""
        return [d for d in self.get_all_deposits() if not d.get("reconciled")]

    def get_unreconciled_withdrawals(self) -> List[Dict[str, Any]]:
        """Return all withdrawal events that have not yet been reconciled by CapitalGovernor."""
        return [w for w in self.get_all_withdrawals() if not w.get("reconciled")]

    def mark_reconciled(self, event_ids: List[str]) -> None:
        """Mark specified events (deposits or withdrawals) as reconciled."""
        if not event_ids or not self.log_file.exists():
            return

        target_ids = set(event_ids)
        records = self.get_all_records()
        now_iso = _now_wib().isoformat()

        updated = False
        for d in records:
            if d.get("event_id") in target_ids and not d.get("reconciled"):
                d["reconciled"] = True
                d["reconciled_at"] = now_iso
                updated = True

        if updated:
            lines = [json.dumps(d, ensure_ascii=False) for d in records]
            self.log_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            logger.info(f"✅ [DepositEvent] Marked {len(target_ids)} transfer event(s) as reconciled.")


_deposit_manager_instance: Optional[DepositEventManager] = None


def get_deposit_manager(log_file: Optional[Path] = None) -> DepositEventManager:
    global _deposit_manager_instance
    if log_file is not None:
        return DepositEventManager(log_file=log_file)
    if _deposit_manager_instance is None:
        _deposit_manager_instance = DepositEventManager()
    return _deposit_manager_instance
