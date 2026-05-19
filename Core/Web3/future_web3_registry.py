from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
REGISTRY_FILE = STATE_DIR / "future_web3_registry.json"


class FutureWeb3Registry:
    def __init__(self) -> None:
        self.adapters: Dict[str, Dict[str, Any]] = {
            "solana_jupiter": {"status": "LIVE_READY"},
            "base_swap": {"status": "BLOCKED_WITH_REASON", "reason": "base_executor_missing"},
            "pumpfun_jupiter": {"status": "LIVE_READY"},
            "polymarket": {"status": "LIVE_READY"},
            "pumpfun_native": {"status": "BLOCKED_WITH_REASON", "reason": "native_program_missing"},
        }

    def refresh(self) -> Dict[str, Any]:
        best = "solana_jupiter"
        reason = ""
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "adapters": self.adapters, "best_adapter": best, "reason": reason}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        REGISTRY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        return payload
