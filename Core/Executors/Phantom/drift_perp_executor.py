import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("DriftPerpExecutor")

class DriftPerpExecutor:
    """ 3. Perpetual DEX: Opens Long/Short positions on Drift Protocol for hedging. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_perp_trade(self, symbol: str, side: str, leverage: float, amount: float) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Drift Perp, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.execute_drift_perp(symbol, side, leverage, amount)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in DriftPerpExecutor: {e}")
            return False
