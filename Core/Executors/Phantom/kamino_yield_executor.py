import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("KaminoYieldExecutor")

class KaminoYieldExecutor:
    """ 2. Yield Farming: Supplies idle capital to Kamino Finance for passive yield. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_yield_deposit(self, token: str, amount: float) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Kamino Yield, PhantomRouter is uninitialized (missing PK).")
            return False
            
        try:
            success = await self.router.deposit_kamino_yield(token, amount)
            if not success:
                logger.warning(f"⚠️ Kamino deposit failed for {amount} {token}.")
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in KaminoYieldExecutor: {e}")
            return False
