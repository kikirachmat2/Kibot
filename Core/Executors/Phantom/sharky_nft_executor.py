import logging
from Core.Exchange.phantom_router import PhantomRouter

logger = logging.getLogger("SharkyNFTExecutor")

class SharkyNFTExecutor:
    """ 9. NFT Lending: Loan offers on SharkyFi. """
    def __init__(self, router: PhantomRouter):
        self.router = router
        self.is_ready = bool(router.private_key)

    async def execute_loan_offer(self, collection_slug: str, offer_usdc: float) -> bool:
        if not self.is_ready:
            logger.error("🚨 CRITICAL: Cannot execute Sharky NFT Loan, PhantomRouter uninitialized.")
            return False
            
        try:
            success = await self.router.offer_nft_loan(collection_slug, offer_usdc)
            return success
        except Exception as e:
            logger.error(f"❌ Unhandled error in SharkyNFTExecutor: {e}")
            return False
