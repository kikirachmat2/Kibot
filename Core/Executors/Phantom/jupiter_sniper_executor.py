import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("JupiterSniperExecutor")

class JupiterSniperExecutor:
    """ 4. Meme Sniping: High slippage rapid execution via Jupiter. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_snipe(self, token_address: str, amount_sol: float, slippage_bps: int = 1000) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Sniper, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.snipe_meme_coin(token_address, amount_sol, slippage_bps)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in JupiterSniperExecutor: {e}")
            return False
