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
    def __init__(self, log_file: Path = DEPOSIT_LOG_FILE):
        self.log_file = log_file
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

    def get_all_deposits(self) -> List[Dict[str, Any]]:
        """Load all deposit events from deposit_events.jsonl."""
        deposits: List[Dict[str, Any]] = []
        if not self.log_file.exists():
            return deposits
        try:
            for line in self.log_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    if isinstance(record, dict) and record.get("event_type") == "OPERATOR_DEPOSIT":
                        deposits.append(record)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Error reading deposit log file: {e}")
        return deposits

    def get_unreconciled_deposits(self) -> List[Dict[str, Any]]:
        """Return all deposit events that have not yet been reconciled by CapitalGovernor."""
        return [d for d in self.get_all_deposits() if not d.get("reconciled")]

    def mark_reconciled(self, event_ids: List[str]) -> None:
        """Mark specified deposit events as reconciled."""
        if not event_ids or not self.log_file.exists():
            return

        target_ids = set(event_ids)
        deposits = self.get_all_deposits()
        now_iso = _now_wib().isoformat()

        updated = False
        for d in deposits:
            if d.get("event_id") in target_ids and not d.get("reconciled"):
                d["reconciled"] = True
                d["reconciled_at"] = now_iso
                updated = True

        if updated:
            lines = [json.dumps(d, ensure_ascii=False) for d in deposits]
            self.log_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            logger.info(f"✅ [DepositEvent] Marked {len(target_ids)} deposit event(s) as reconciled.")


_deposit_manager_instance: Optional[DepositEventManager] = None


def get_deposit_manager() -> DepositEventManager:
    global _deposit_manager_instance
    if _deposit_manager_instance is None:
        _deposit_manager_instance = DepositEventManager()
    return _deposit_manager_instance
