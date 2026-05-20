from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"


def _capital_governor_block() -> Dict[str, Any]:
    gov_path = STATE_DIR / "capital_governor.json"
    if not gov_path.exists():
        return {"blocked": True, "reason": "capital_governor_missing"}
    try:
        gov = json.loads(gov_path.read_text(encoding="utf-8"))
    except Exception:
        return {"blocked": True, "reason": "capital_governor_unreadable"}
    allow = bool(gov.get("allow_new_orders", False))
    status = str(gov.get("status") or "").upper()
    reason = str(gov.get("allow_new_orders_reason") or "").strip()
    if allow and status in {"RECONCILED", "RECONCILING"}:
        return {"blocked": False, "reason": ""}
    if not reason:
        if status == "BLOCKED_WITH_REASON":
            reason = "capital_governor_global_hard_stop"
        elif status:
            reason = f"capital_governor_status_{status.lower()}"
        else:
            reason = "capital_governor_orders_blocked"
    return {"blocked": True, "reason": reason}


class BaseAllowanceManager:
    def __init__(self, signer_present: bool = False) -> None:
        self.signer_present = signer_present

    def readiness(self) -> Dict[str, Any]:
        if not self.signer_present:
            return {"allowed": False, "reason": "evm_signer_missing"}
        block = _capital_governor_block()
        if block.get("blocked"):
            return {"allowed": False, "reason": str(block.get("reason") or "capital_governor_orders_blocked")}
        return {"allowed": True, "reason": ""}

    def build_approval(self, token: str, router: str, amount_raw: int) -> Dict[str, Any]:
        ready = self.readiness()
        return {"ok": bool(ready.get("allowed", False)), "reason": str(ready.get("reason") or ""), "token": token, "router": router, "amount_raw": int(amount_raw or 0)}
