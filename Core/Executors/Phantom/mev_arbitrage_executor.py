import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("MEVArbitrageExecutor")

class MEVArbitrageExecutor:
    """ 10. MEV Arbitrage: Flash loans and cross-dex arb. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_arbitrage(self, token: str, buy_dex: str, sell_dex: str) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute MEV Arbitrage, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.execute_mev_arbitrage(token, buy_dex, sell_dex)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in MEVArbitrageExecutor: {e}")
            return False
