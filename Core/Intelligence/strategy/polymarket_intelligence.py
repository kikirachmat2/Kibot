import logging
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("kibot.intelligence.polymarket")

@dataclass
class MarketIntelligence:
    market_id: str
    implied_probability: float
    fair_probability: float
    edge: float
    liquidity_score: float
    resolution_risk: float
    evidence_quality: float
    confidence: float
    recommendation: str  # ENTER, EXIT, WAIT, AVOID

class PolymarketIntelligenceEngine:
    """
    Sovereign Intelligence Engine for Polymarket (§G-003).
    Analyzes event markets for probability edge, liquidity, and resolution risk.
    """

    def __init__(self, coordinator=None):
        self.coordinator = coordinator
        self.coordinator_query = coordinator
        self.last_analysis: Dict[str, MarketIntelligence] = {}

    async def analyze_market(self, market_data: Dict[str, Any]) -> MarketIntelligence:
        """
        Full spectrum analysis of a Polymarket event.
        """
        market_id = market_data.get("id") or market_data.get("condition_id")
        
        # 1. Probability Analysis
        implied_prob = self._get_implied_probability(market_data)
        fair_prob, confidence = await self._estimate_fair_probability(market_data)
        edge = fair_prob - implied_prob

        # 2. Liquidity Simulation
        liq_score = self._simulate_liquidity(market_data)

        # 3. Resolution Risk Assessment
        res_risk = self._assess_resolution_risk(market_data)

        # 4. Evidence Bundling
        ev_quality = await self._bundle_evidence(market_data)

        # 5. Recommendation Logic
        recommendation = self._decide(edge, liq_score, res_risk, ev_quality, confidence)

        intel = MarketIntelligence(
            market_id=market_id,
            implied_probability=implied_prob,
            fair_probability=fair_prob,
            edge=edge,
            liquidity_score=liq_score,
            resolution_risk=res_risk,
            evidence_quality=ev_quality,
            confidence=confidence,
            recommendation=recommendation
        )

        self.last_analysis[market_id] = intel
        return intel

    def _get_implied_probability(self, data: Dict[str, Any]) -> float:
        """Extracts market price as implied probability."""
        # Typically price (0.0 - 1.0) is the probability
        return float(data.get("price", 0.5))

    async def _estimate_fair_probability(self, data: Dict[str, Any]) -> tuple:
        """
        Uses AI Coordinator to research and estimate fair probability.
        """
        if not self.coordinator:
            # Fallback if coordinator not injected (e.g. standalone test)
            try:
                from Core.Intelligence.kibot_ai_coordinator import query_ai
                self.coordinator_query = query_ai
            except ImportError:
                return 0.5, 0.5

        title = data.get("title") or data.get("question") or "Unknown Event"
        description = data.get("description") or ""
        
        # Use deep reasoning if available for event markets
        context = {
            "title": title,
            "description": description,
            "current_price": data.get("price", 0.5),
            "market_type": "event_probability",
            "search_query": f"latest news on {title}"
        }
        
        try:
            # Request deep research probability
            res = await self.coordinator_query("EVENT_PROBABILITY_RESEARCH", context)
            if res and isinstance(res, dict):
                fair_prob = float(res.get("fair_probability", 0.5))
                confidence = float(res.get("confidence", 0.5))
                return fair_prob, confidence
        except Exception as e:
            logger.warning(f"AI probability research failed: {e}")
            
        return 0.5, 0.5

    def _simulate_liquidity(self, data: Dict[str, Any]) -> float:
        """
        Analyzes orderbook depth and spread.
        """
        # CLOB data usually has 'liquidity' or we can check 'orderbook'
        liquidity = float(data.get("liquidity", 0.0))
        volume_24h = float(data.get("volume_24h", 0.0))
        
        # Normalize score (0.0 - 1.0)
        # Thresholds: >$10k liq is decent, >$100k is good for our size
        score = 0.0
        if liquidity > 100000: score = 0.9
        elif liquidity > 50000: score = 0.7
        elif liquidity > 10000: score = 0.5
        elif liquidity > 1000: score = 0.3
        
        if volume_24h > 1000000: score = min(1.0, score + 0.1)
        
        return score

    def _assess_resolution_risk(self, data: Dict[str, Any]) -> float:
        """
        Analyzes wording and source dependency for resolution ambiguity.
        """
        risk = 0.1 # Base risk
        title = str(data.get("title", "")).lower()
        source = str(data.get("resolution_source", "")).lower()
        
        # Ambiguity flags
        ambiguity_flags = ["maybe", "likely", "subjective", "interpreted", "discretion"]
        for flag in ambiguity_flags:
            if flag in title:
                risk += 0.2
                
        # Source reliability
        if not source:
            risk += 0.3 # Unknown source is dangerous
        elif "twitter" in source or "x.com" in source:
            risk += 0.2 # Social media resolution risk
        elif "reuters" in source or "ap.org" in source or "official" in source:
            risk -= 0.1 # Official sources are better
            
        return max(0.0, min(1.0, risk))

    async def _bundle_evidence(self, data: Dict[str, Any]) -> float:
        """
        Aggregates search results and official source verification.
        """
        # This would normally pull from search providers
        # For now, we use a proxy based on data freshness and title clarity
        clarity = 0.5
        if data.get("title") and len(data.get("title", "")) > 20:
            clarity += 0.2
        if data.get("resolution_source"):
            clarity += 0.2
            
        return min(1.0, clarity)

    def _decide(self, edge: float, liq: float, risk: float, ev: float, conf: float) -> str:
        """Sovereign decision gate for event markets."""
        # Risk Veto
        if risk > 0.45: return "AVOID"
        
        # Liquidity Veto
        if liq < 0.2: return "WAIT"
        
        # Edge Logic
        # We want positive edge + sufficient confidence
        if edge > 0.07 and conf > 0.65 and ev > 0.6:
            return "ENTER"
            
        # If we already have edge but low confidence, wait for more evidence
        if edge > 0.10:
            return "WAIT"
            
        return "WAIT"

if __name__ == "__main__":
    # Basic test
    engine = PolymarketIntelligenceEngine()
    test_market = {"id": "test-123", "price": 0.45, "title": "Will AI dominate 2024?"}
    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(engine.analyze_market(test_market))
    print(f"Analysis: {result}")
