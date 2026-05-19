from __future__ import annotations

from Core.Web3.future_web3_registry import FutureWeb3Registry


class FutureWeb3Executor:
    def __init__(self) -> None:
        self.registry = FutureWeb3Registry()

    def readiness(self):
        return self.registry.refresh()
