import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional

from Core.Support.ki_config import KiConfig

logger = logging.getLogger("PhantomTreasury")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PHANTOM_STATE_FILE = STATE_DIR / "phantom_treasury.json"
USD_IDR_RATE = 16000.0  # Manifesto standard conversion rate

class PhantomTreasury:
    """
    Sovereign Phantom Treasury Manager
    Interfaces with PhantomRouter to fetch SOL & USDC, converts to IDR,
    and dynamically allocates capital into Swap, Polymarket, Reserve, and future Web3.
    """
    def __init__(self, phantom_router=None):
        self.router = phantom_router
        self.sol_balance = 0.0
        self.usdc_balance = 0.0
        self.total_value_idr = 0.0
        
        # Default bucket percentages
        self.bucket_percentages = {
            "swap": 0.40,
            "polymarket": 0.00,
            "reserve": 0.60,
            "future_web3": 0.00
        }
        self.buckets = {
            "swap_idr": 0.0,
            "polymarket_idr": 0.0,
            "reserve_idr": 0.0,
            "future_web3_idr": 0.0
        }
        self._load_state()

    def _load_state(self):
        if PHANTOM_STATE_FILE.exists():
            try:
                with open(PHANTOM_STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.bucket_percentages = data.get("bucket_percentages", self.bucket_percentages)
                    self.buckets = data.get("buckets", self.buckets)
                    logger.info("✅ Phantom Treasury state loaded successfully.")
            except Exception as e:
                logger.error(f"❌ Failed to load Phantom Treasury state: {e}")
        self._update_allocation_percentages()

    def _update_allocation_percentages(self):
        """Derive sub-bucket allocation percentages based on mode/rules."""
        # Check if we should use Polymarket Paper or Micro-live allocations
        is_polymarket_paper = not KiConfig.ENABLE_POLYMARKET_LIVE
        if is_polymarket_paper:
            # Polymarket Paper: Swap 40%, Polymarket 20%, Reserve 40%
            self.bucket_percentages = {
                "swap": 0.40,
                "polymarket": 0.20,
                "reserve": 0.40,
                "future_web3": 0.00
            }
        else:
            # Micro-live: Swap 40%, Polymarket 0%, Reserve 60%
            self.bucket_percentages = {
                "swap": 0.40,
                "polymarket": 0.00,
                "reserve": 0.60,
                "future_web3": 0.00
            }

    def save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(PHANTOM_STATE_FILE, "w") as f:
                json.dump({
                    "address": self.router.wallet_address if self.router else "0x...",
                    "sol_balance": self.sol_balance,
                    "usdc_balance": self.usdc_balance,
                    "total_value_idr": self.total_value_idr,
                    "bucket_percentages": self.bucket_percentages,
                    "buckets": self.buckets
                }, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save Phantom Treasury state: {e}")

    async def reconcile_balances(self):
        """Fetch real balances from PhantomRouter and recalculate buckets."""
        if self.router:
            try:
                balances = await self.router.get_balances()
                self.sol_balance = balances.get("sol_balance", 0.0)
                self.usdc_balance = balances.get("usdc_balance", 0.0)
            except Exception as e:
                logger.error(f"❌ Failed to query balances from PhantomRouter: {e}")
        
        # Calculate IDR equivalencies
        # SOL is valued at $170 USD for IDR conversion (assuming roughly stable Sol price, or we can fetch a rate)
        # For precision, let's assume 1 SOL = $170 * USD_IDR_RATE
        sol_value_usd = 170.0 
        sol_value_idr = self.sol_balance * sol_value_usd * USD_IDR_RATE
        usdc_value_idr = self.usdc_balance * USD_IDR_RATE
        
        self.total_value_idr = sol_value_idr + usdc_value_idr
        self._update_allocation_percentages()
        
        # Split into buckets
        self.buckets = {
            "swap_idr": self.total_value_idr * self.bucket_percentages.get("swap", 0.0),
            "polymarket_idr": self.total_value_idr * self.bucket_percentages.get("polymarket", 0.0),
            "reserve_idr": self.total_value_idr * self.bucket_percentages.get("reserve", 0.0),
            "future_web3_idr": self.total_value_idr * self.bucket_percentages.get("future_web3", 0.0)
        }
        self.save()

    def get_summary(self) -> Dict[str, Any]:
        return {
            "address": self.router.wallet_address if self.router else "0x...",
            "sol_balance": self.sol_balance,
            "usdc_balance": self.usdc_balance,
            "total_value_idr": self.total_value_idr,
            "bucket_percentages": self.bucket_percentages,
            "buckets": self.buckets
        }
