from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
NATIVE_STATE_FILE = STATE_DIR / "pumpfun_native_executor_state.json"


def _write_json(path: Path, payload: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


class PumpfunNativeExecutor:
    """Guarded placeholder for Pump.fun native bonding-curve execution.

    This module intentionally does not submit trades unless explicit signer and
    native-program configuration are present. Until then it only reports the
    blocked reason so the scanner can continue operating safely.
    """

    def __init__(self) -> None:
        self.signer_path = os.getenv("PUMPFUN_NATIVE_SIGNER_PATH", "").strip()
        self.program_id = os.getenv("PUMPFUN_NATIVE_PROGRAM_ID", "").strip()
        self.enabled = str(os.getenv("PUMPFUN_NATIVE_EXECUTOR_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}

    def get_status(self) -> Dict[str, Any]:
        if not self.enabled:
            status = "BLOCKED_WITH_REASON"
            reason = "native_executor_not_enabled"
        elif not self.signer_path:
            status = "BLOCKED_WITH_REASON"
            reason = "signer_missing"
        elif not self.program_id:
            status = "BLOCKED_WITH_REASON"
            reason = "native_program_missing"
        else:
            status = "BLOCKED_WITH_REASON"
            reason = "native_executor_not_implemented"

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "reason": reason,
            "enabled": self.enabled,
            "signer_present": bool(self.signer_path),
            "program_id_present": bool(self.program_id),
            "native_ready": False,
        }
        _write_json(NATIVE_STATE_FILE, payload)
        return payload

    def build_buy_transaction(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def build_sell_transaction(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def simulate_buy(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def simulate_sell(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def submit_transaction(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def verify_confirmation(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def get_curve_state(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def estimate_buy_out(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

    def estimate_sell_out(self, *args, **kwargs) -> Dict[str, Any]:
        return {"ok": False, "reason": self.get_status()["reason"]}

