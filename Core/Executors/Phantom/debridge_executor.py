import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("DeBridgeExecutor")

class DeBridgeExecutor:
    """ 8. Cross-Chain Bridging: Asset movement across chains. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_bridge(self, amount: float, token: str, from_chain: str, to_chain: str) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Bridge, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.bridge_debridge(amount, token, from_chain, to_chain)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in DeBridgeExecutor: {e}")
            return False
