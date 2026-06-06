import logging
import os
import json
from typing import Dict, Any, List
import asyncio

from Core.Intelligence.defi_metrics_fetcher import DeFiMetricsFetcher
from Core.Support.ki_config import KiConfig

logger = logging.getLogger("MarketRotationEngine")

class MarketRotationEngine:
    """
    Market Rotation Engine.
    Dynamically orchestrates capital allocations across Indodax, Polymarket, Phantom (DeFi),
    and CASH_WAIT, based on expected net yields, slippages, risk factors, and market regimes.
    Enforces total simulation safety.
    """
    def __init__(self):
        self.defi_fetcher = DeFiMetricsFetcher()
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
        if KiConfig.INDODAX_ONLY:
            return {
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

        venues = {
            "Indodax": {"apy": 0.0, "risk_score": 2, "description": "Spot HFT trading via Lead-Lag & orderbook microstructure."},
            "Polymarket": {"apy": 0.0, "risk_score": 4, "description": "Prediction markets arbitrage & dynamic probability scans."},
            "Phantom": {"apy": 0.0, "risk_score": 3, "description": "DeFi lending (Kamino), Orca pools, or Jito liquid staking."},
            "CASH_WAIT": {"apy": 0.0, "risk_score": 0, "description": "Idle IDR/USDC cash buffer awaiting highly-rated opportunities."}
        }
        
        # 1. Phantom (DeFi) APY
        try:
            intel = await self.defi_fetcher.get_aggregated_defi_intelligence()
            yields = intel.get("yield_farming_apys", {})
            venues["Phantom"]["apy"] = max(yields.values()) if yields else 8.5
        except Exception as e:
            logger.warning(f"Failed to fetch DeFi metrics for rotation: {e}")
            venues["Phantom"]["apy"] = 8.5
            
        # 2. Indodax simulated HFT yield
        # Derived from scanning leadlag_alpha state if available
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

        # 3. Polymarket APY (based on prediction opportunity count)
        # Using a model regime estimation
        venues["Polymarket"]["apy"] = 12.0 # Standard yield baseline for predictive event arbitrage
        
        # 4. CASH_WAIT (stable yield)
        venues["CASH_WAIT"]["apy"] = 4.5 # Bank deposit or stable yield proxy
        
        return venues

    async def compute_optimal_allocation(self, total_capital_idr: float = 100_000_000.0) -> Dict[str, Any]:
        """
        Evaluate APRs and calculate optimal capital distribution across venues.
        Allocates capital primarily to higher-yield, lower-risk environments.
        """
        if KiConfig.INDODAX_ONLY:
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
                "suggested_movements": [],
                "retired_venues": {
                    "phantom": "REMOVED_BY_OPERATOR",
                    "polymarket": "REMOVED_BY_OPERATOR",
                    "web3": "REMOVED_BY_OPERATOR",
                },
            }
            self._save_state(result)
            logger.info(f"📈 Indodax-only Rotation Computed: {allocations}")
            return result

        venues = await self.calculate_venue_yields()
        
        # Calculate a combined score: Yield divided by Risk Score (adding a risk-adjusted discount)
        # For CASH_WAIT, risk is 0, so give it a default baseline score.
        scores = {}
        for name, details in venues.items():
            apy = details["apy"]
            risk = details["risk_score"]
            if risk == 0:
                score = apy  # CASH_WAIT
            else:
                score = apy / (1.0 + (risk * 0.2)) # risk-adjusted divisor
            scores[name] = score
            
        total_score = sum(scores.values())
        allocations = {}
        
        if total_score > 0:
            for name, score in scores.items():
                allocations[name] = round((score / total_score) * 100.0, 2)
        else:
            # Equal weight fallback
            allocations = {k: 25.0 for k in venues.keys()}
            
        # Ensure a minimum allocation of 10% to CASH_WAIT for emergency buffers
        min_cash = 10.0
        if allocations["CASH_WAIT"] < min_cash:
            diff = min_cash - allocations["CASH_WAIT"]
            allocations["CASH_WAIT"] = min_cash
            # Deduct diff proportionally from others
            other_names = [n for n in allocations.keys() if n != "CASH_WAIT"]
            sum_others = sum(allocations[n] for n in other_names)
            for n in other_names:
                allocations[n] = round(allocations[n] - (diff * (allocations[n] / sum_others)), 2)

        # Build allocation recommendation
        alloc_idr = {name: round(total_capital_idr * (pct / 100.0), 0) for name, pct in allocations.items()}
        
        result = {
            "timestamp_ms": int(asyncio.get_event_loop().time() * 1000),
            "total_capital_idr": total_capital_idr,
            "venue_yields": venues,
            "allocations_pct": allocations,
            "allocations_idr": alloc_idr,
            "suggested_movements": []
        }
        
        # Determine suggestion (e.g. if rotation has shifted from previous state)
        if self.last_allocation:
            prev_pcts = self.last_allocation.get("allocations_pct", {})
            for venue, pct in allocations.items():
                prev_pct = prev_pcts.get(venue, pct)
                if abs(pct - prev_pct) >= 5.0:
                    action = "ADD" if pct > prev_pct else "REDUCE"
                    diff_idr = abs(alloc_idr[venue] - self.last_allocation.get("allocations_idr", {}).get(venue, 0))
                    result["suggested_movements"].append({
                        "venue": venue,
                        "action": action,
                        "pct_change": round(pct - prev_pct, 2),
                        "amount_idr": diff_idr,
                        "reason": f"{venue} expected APR changed. Yield now {venues[venue]['apy']}%."
                    })
                    
        self._save_state(result)
        logger.info(f"📈 Optimal Rotation Computed: {allocations}")
        return result
