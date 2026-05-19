from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"


class BaseAllowanceManager:
    def __init__(self, signer_present: bool = False) -> None:
        self.signer_present = signer_present

    def readiness(self) -> Dict[str, Any]:
        return {"allowed": bool(self.signer_present), "reason": "" if self.signer_present else "evm_signer_missing"}

    def build_approval(self, token: str, router: str, amount_raw: int) -> Dict[str, Any]:
        return {"ok": bool(self.signer_present), "reason": "" if self.signer_present else "evm_signer_missing", "token": token, "router": router, "amount_raw": int(amount_raw or 0)}
