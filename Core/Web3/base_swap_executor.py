from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from web3 import Web3

from Core.Web3.base_allowance_manager import BaseAllowanceManager
from Core.Web3.base_quote_router import BaseQuoteRouter
from Core.Web3.base_executor_state import write_base_state
from Core.Scanner.source_proof import SourceProof

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
BASE_EXECUTOR_STATE_FILE = STATE_DIR / "base_executor_state.json"


class BaseSwapExecutor:
    def __init__(self) -> None:
        self.enabled = str(os.getenv("BASE_LIVE_EXECUTOR_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}
        self.rpc_url = os.getenv("BASE_RPC_URL", "").strip()
        self.evm_address = os.getenv("PHANTOM_EVM_ADDRESS", "").strip()
        self.idrx_token_address = os.getenv("IDRX_BASE_TOKEN_ADDRESS", "").strip()
        self.private_key = os.getenv("PHANTOM_PRIVATE_KEY", "").strip()
        self.router = os.getenv("BASE_SWAP_ROUTER", "0x").strip()
        self._w3 = Web3(Web3.HTTPProvider(self.rpc_url)) if self.rpc_url else None
        self.quote_router = BaseQuoteRouter()
        self.allowance = BaseAllowanceManager(signer_present=bool(self.private_key))

    def readiness(self) -> Dict[str, Any]:
        if not self.enabled:
            return self._write("BLOCKED_WITH_REASON", "base_executor_disabled")
        if not self.rpc_url or not self.evm_address or not self.idrx_token_address:
            return self._write("BLOCKED_WITH_REASON", "base_config_missing")
        if not self.private_key:
            return self._write("BLOCKED_WITH_REASON", "evm_signer_missing")
        approval = self.allowance.readiness()
        if not approval.get("allowed", False):
            return self._write("BLOCKED_WITH_REASON", str(approval.get("reason") or "capital_governor_orders_blocked"))
        return self._write("BASE_LIVE_READY_WAITING_FOR_CANDIDATE", "")

    def _write(self, status: str, reason: str, **extra: Any) -> Dict[str, Any]:
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "status": status, "reason": reason, "enabled": self.enabled, "rpc_ok": bool(self.rpc_url), "signer_present": bool(self.private_key), "router": self.router, **extra}
        write_base_state(payload)
        return payload

    async def quote(self, token_in: str, token_out: str, amount_raw: int, *, trade_size_idr: float | None = None, balance_snapshot: Dict[str, Any] | None = None) -> Dict[str, Any]:
        return await self.quote_router.quote(token_in, token_out, amount_raw, trade_size_idr=trade_size_idr, balance_snapshot=balance_snapshot)

    async def execute_swap(self, token_in: str, token_out: str, amount_raw: int, quote: Dict[str, Any]) -> Dict[str, Any]:
        status = self.readiness()
        if status["status"] != "BASE_LIVE_READY_WAITING_FOR_CANDIDATE" and status["status"] != "BASE_LIVE_ACTIVE":
            return self._write("BLOCKED_WITH_REASON", status["reason"])
        approval = self.allowance.readiness()
        if not approval["allowed"]:
            return self._write("BLOCKED_WITH_REASON", approval["reason"])
        if not quote.get("quote_ok"):
            return self._write("BLOCKED_WITH_REASON", quote.get("reason", "no_quote"))
        fee_intelligence = quote.get("fee_intelligence") if isinstance(quote.get("fee_intelligence"), dict) else {}
        if fee_intelligence and not bool(fee_intelligence.get("gas_affordable", True)):
            return self._write("BLOCKED_WITH_REASON", str(fee_intelligence.get("gas_reason") or "base_gas_unaffordable"))
        proof = quote.get("source_proof")
        if proof is not None and not SourceProof.validate(proof):
            return self._write("BLOCKED_WITH_REASON", "invalid_source_proof")
        # Generic live send placeholder via EVM signer path; 0x/aggregator tx building is external-config dependent.
        return self._write("BASE_LIVE_ACTIVE", "", entry_quote=quote, last_action="quote_ready")
