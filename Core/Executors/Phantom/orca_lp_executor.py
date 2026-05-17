import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("OrcaLPExecutor")

class OrcaLPExecutor:
    """ 7. Liquidity Provision: Concentrated liquidity on Orca/Meteora. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_lp(self, pool_id: str, amount_a: float, amount_b: float) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Orca LP, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.provide_orca_liquidity(pool_id, amount_a, amount_b)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in OrcaLPExecutor: {e}")
            return False
