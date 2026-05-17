import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("AirdropFarmerExecutor")

class AirdropFarmerExecutor:
    """ 6. Airdrop Farming: Low value interactions to build on-chain volume. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_farm(self, target_protocol: str, action: str) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Airdrop Farm, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.farm_airdrop(target_protocol, action)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in AirdropFarmerExecutor: {e}")
            return False
