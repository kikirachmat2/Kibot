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
        self.adapters: Dict[str, Dict[str, Any]] = {}

    def _read_state(self, name: str) -> Dict[str, Any]:
        path = STATE_DIR / name
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
        except Exception:
            pass
        return {}

    def _adapter_status(self, name: str) -> Dict[str, Any]:
        if name == "base_swap":
            base_state = self._read_state("base_executor_state.json")
            status = str(base_state.get("status") or "").upper()
            reason = str(base_state.get("reason") or "").strip()
            if status in {"BASE_LIVE_READY_WAITING_FOR_CANDIDATE", "BASE_LIVE_ACTIVE", "LIVE_READY", "ACTIVE"}:
                return {"status": "LIVE_READY", "reason": "", "source": "base_executor_state"}
            if status == "BLOCKED_WITH_REASON" and reason:
                return {"status": "BLOCKED_WITH_REASON", "reason": reason, "source": "base_executor_state"}
            if base_state:
                return {"status": "LIVE_READY", "reason": "", "source": "base_executor_state"}
            return {"status": "BLOCKED_WITH_REASON", "reason": "base_executor_missing", "source": "base_executor_state"}
        if name == "pumpfun_native":
            native_state = self._read_state("pumpfun_native_executor_state.json")
            status = str(native_state.get("status") or "").upper()
            reason = str(native_state.get("reason") or "").strip()
            if status in {"READY", "BUY_CONFIRMED", "SELL_CONFIRMED", "LIVE_READY", "ACTIVE"}:
                return {"status": "LIVE_READY", "reason": "", "source": "pumpfun_native_executor_state"}
            if status == "BLOCKED_WITH_REASON" and reason:
                return {"status": "BLOCKED_WITH_REASON", "reason": reason, "source": "pumpfun_native_executor_state"}
            if native_state:
                return {"status": "LIVE_READY", "reason": "", "source": "pumpfun_native_executor_state"}
            return {"status": "BLOCKED_WITH_REASON", "reason": "native_program_missing", "source": "pumpfun_native_executor_state"}
        if name == "polymarket":
            poly_state = self._read_state("polymarket_executor_state.json")
            status = str(poly_state.get("status") or "").upper()
            reason = str(poly_state.get("reason") or "").strip()
            if status in {"LIVE_READY", "ACTIVE", "READY"}:
                return {"status": "LIVE_READY", "reason": "", "source": "polymarket_executor_state"}
            if status == "BLOCKED_WITH_REASON" and reason:
                return {"status": "BLOCKED_WITH_REASON", "reason": reason, "source": "polymarket_executor_state"}
            return {"status": "LIVE_READY", "reason": "", "source": "polymarket_executor_state"}
        return {"status": "LIVE_READY", "reason": "", "source": "default"}

    def refresh(self) -> Dict[str, Any]:
        self.adapters = {
            "solana_jupiter": {"status": "LIVE_READY", "reason": "", "source": "default"},
            "base_swap": self._adapter_status("base_swap"),
            "pumpfun_jupiter": {"status": "LIVE_READY", "reason": "", "source": "default"},
            "polymarket": self._adapter_status("polymarket"),
            "pumpfun_native": self._adapter_status("pumpfun_native"),
        }
        priority = ["solana_jupiter", "pumpfun_jupiter", "pumpfun_native", "base_swap", "polymarket"]
        best = ""
        reason = ""
        for adapter in priority:
            state = self.adapters.get(adapter, {})
            if str(state.get("status") or "").upper() in {"LIVE_READY", "ACTIVE", "READY", "BASE_LIVE_READY_WAITING_FOR_CANDIDATE", "BASE_LIVE_ACTIVE"}:
                best = adapter
                reason = ""
                break
        if not best:
            for adapter in priority:
                state = self.adapters.get(adapter, {})
                if str(state.get("reason") or "").strip():
                    reason = str(state.get("reason") or "").strip()
                    break
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "adapters": self.adapters, "best_adapter": best, "reason": reason}
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        REGISTRY_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        return payload
