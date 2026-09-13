import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger("CapitalCommander")

class CapitalCommander:
    """
    Indodax-only treasury commander.

    Wallet/cross-chain routing has been removed by operator decision. This
    class keeps legacy call sites safe while only allocating to Indodax/reserve.
    """

    def __init__(self, indodax_gateway, *_unused):
        self.indodax = indodax_gateway
        self.total_equity_idr = 0.0
        self.allocations = {
            "BULL": {"indodax_spot": 0.85, "reserve": 0.15},
            "CRAB": {"indodax_spot": 0.80, "reserve": 0.20},
            "BEAR": {"indodax_spot": 0.65, "reserve": 0.35},
        }

    async def safe_execute(self, executor_name: str, method_name: str, *args, timeout: int = 30, **kwargs) -> bool:
        logger.error("Executor %s.%s is unavailable in Indodax-only runtime.", executor_name, method_name)
        return False

    async def get_treasury_snapshot(self) -> Dict[str, Any]:
        """
        Aggregates balance across all active treasury routes with hardened fallbacks.
        """
        snapshot = {
            "indodax": {"cash_idr": 0.0, "crypto_value_idr": 0.0},
            "reserve": {"cash_idr": 0.0},
            "total_equity_idr": 0.0
        }
        
        # 1. Fetch Indodax (Fiat & Local Crypto)
        try:
            # Hardened timeout for API requests
            indo_info = await asyncio.wait_for(self.indodax.get_info(), timeout=10)
            if indo_info.get("success") == 1:
                balances = indo_info.get("return", {}).get("balance", {})
                snapshot["indodax"]["cash_idr"] = float(balances.get("idr", 0) or 0)
        except Exception as e:
            logger.error(f"Failed to fetch Indodax treasury: {e}")

        snapshot["total_equity_idr"] = snapshot["indodax"]["cash_idr"] + snapshot["indodax"]["crypto_value_idr"]
        self.total_equity_idr = snapshot["total_equity_idr"]

        return snapshot

    def request_allocation(self, route: str, requested_amount_idr: float, current_regime: str) -> bool:
        if not self.total_equity_idr:
            logger.warning("Treasury snapshot missing, denying allocation.")
            return False

        regime_targets = self.allocations.get(current_regime.upper(), self.allocations["CRAB"])
        
        route_key = str(route or "").strip().lower()
        if route_key == "indodax":
            route_key = "indodax_spot"
        if route_key not in regime_targets:
            logger.warning(f"Route {route} not supported in regime {current_regime}")
            return False
            
        target_pct = regime_targets[route_key]
        max_allowed = self.total_equity_idr * target_pct
        
        if requested_amount_idr <= max_allowed:
            logger.info(f"✅ Treasury Approved: {requested_amount_idr:,.0f} IDR for {route}")
            return True
            
        logger.warning(f"❌ Treasury Denied: {requested_amount_idr:,.0f} IDR exceeds max {max_allowed:,.0f} for {route}")
        return False
