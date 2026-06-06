import logging
import os
import json
from typing import Dict, Any, List
import asyncio

logger = logging.getLogger("MarketRotationEngine")

class MarketRotationEngine:
    """
    Market Rotation Engine.
    Dynamically orchestrates Indodax vs CASH_WAIT allocation based on expected
    edge, risk factors, and market regime.
    """
    def __init__(self):
        self.state_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
            "state", 
            "market_rotation.json"
        )
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        self.last_allocation = {}
        self._load_state()

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r") as f:
                    self.last_allocation = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load market rotation state: {e}")

    def _save_state(self, allocation: Dict[str, Any]):
        try:
            self.last_allocation = allocation
            with open(self.state_file, "w") as f:
                json.dump(allocation, f, indent=4)
        except Exception as e:
            logger.warning(f"Failed to write market rotation state: {e}")

    async def calculate_venue_yields(self) -> Dict[str, Dict[str, Any]]:
        """
        Estimate current annualized yield profiles (APRs) for all trading venues.
        """
        venues = {
            "Indodax": {
                "apy": 0.0,
                "risk_score": 2,
                "description": "Spot trading via Indodax orderbook, fee-aware EV, and lead-lag confirmation.",
            },
            "CASH_WAIT": {
                "apy": 0.0,
                "risk_score": 0,
                "description": "IDR cash buffer while deterministic gates wait for a qualified setup.",
            },
        }

        try:
            leadlag_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
                "state", 
                "leadlag_alpha.json"
            )
            if os.path.exists(leadlag_file):
                with open(leadlag_file, "r") as f:
                    ll_data = json.load(f)
                active_signals = len(ll_data.get("qualified_signals", []))
                # Scale expected APY based on active signal presence
                venues["Indodax"]["apy"] = min(15.0, 5.0 + (active_signals * 2.5))
            else:
                venues["Indodax"]["apy"] = 6.0
        except Exception:
            venues["Indodax"]["apy"] = 6.0

        venues["CASH_WAIT"]["apy"] = 0.0
        return venues

    async def compute_optimal_allocation(self, total_capital_idr: float = 100_000_000.0) -> Dict[str, Any]:
        """
        Evaluate APRs and calculate optimal capital distribution across venues.
        Allocates capital primarily to higher-yield, lower-risk environments.
        """
        venues = await self.calculate_venue_yields()
        allocations = {"Indodax": 85.0, "CASH_WAIT": 15.0}
        alloc_idr = {name: round(total_capital_idr * (pct / 100.0), 0) for name, pct in allocations.items()}
        result = {
            "timestamp_ms": int(asyncio.get_event_loop().time() * 1000),
            "platform_mode": "INDODAX_ONLY",
            "total_capital_idr": total_capital_idr,
            "venue_yields": venues,
            "allocations_pct": allocations,
            "allocations_idr": alloc_idr,
            "suggested_movements": []
        }
        self._save_state(result)
        logger.info(f"📈 Indodax-only Rotation Computed: {allocations}")
        return result
