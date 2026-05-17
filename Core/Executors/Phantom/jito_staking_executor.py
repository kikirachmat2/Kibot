import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("JitoStakingExecutor")

class JitoStakingExecutor:
    """ 5. Liquid Staking: Converts SOL to JitoSOL for yield. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_stake(self, amount_sol: float) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Jito Staking, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.stake_jito_sol(amount_sol)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in JitoStakingExecutor: {e}")
            return False
