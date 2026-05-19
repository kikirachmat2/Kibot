from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Web3RouteAdapter:
    network: str
    route_name: str

    def readiness(self) -> Dict[str, Any]:
        return {"status": "BLOCKED_WITH_REASON", "reason": "adapter_not_implemented"}

    async def scan(self) -> Dict[str, Any]:
        return {"updated_at": "", "candidates": [], "best_candidate": {}, "rejected": []}

    async def quote(self, candidate) -> Dict[str, Any]:
        return {"quote_ok": False, "reason": "adapter_not_implemented"}

    async def size(self, candidate) -> Dict[str, Any]:
        return {"approved": False, "reason": "adapter_not_implemented"}

    async def build_entry(self, candidate, size) -> Dict[str, Any]:
        return {"ok": False, "reason": "adapter_not_implemented"}

    async def submit_entry(self, tx) -> Dict[str, Any]:
        return {"ok": False, "reason": "adapter_not_implemented"}

    async def confirm_entry(self, sig) -> Dict[str, Any]:
        return {"ok": False, "reason": "adapter_not_implemented"}

    async def build_exit(self, position) -> Dict[str, Any]:
        return {"ok": False, "reason": "adapter_not_implemented"}

    async def submit_exit(self, tx) -> Dict[str, Any]:
        return {"ok": False, "reason": "adapter_not_implemented"}

    async def confirm_exit(self, sig) -> Dict[str, Any]:
        return {"ok": False, "reason": "adapter_not_implemented"}
