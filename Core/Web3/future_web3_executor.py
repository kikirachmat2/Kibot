from __future__ import annotations

from Core.Web3.future_web3_registry import FutureWeb3Registry
from Core.Scanner.source_proof import SourceProof


class FutureWeb3Executor:
    def __init__(self) -> None:
        self.registry = FutureWeb3Registry()

    def readiness(self):
        return self.registry.refresh()

    def approve_candidate(self, candidate):
        proof = candidate.get("source_proof") if isinstance(candidate, dict) else None
        if not SourceProof.validate(proof):
            return {"allowed": False, "reason": "invalid_source_proof"}
        return {"allowed": True, "reason": "approved"}
