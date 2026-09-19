"""
KiBot V2 — Secondary Market Regime Consensus via getregime.com.
Fetches macroeconomic/global crypto market regime signals as an out-of-band sanity check.
Caches responses for 5 minutes (300s) to adhere strictly to free tier rate limits (10 req/min).
Falls back 100% to internal regime detector upon any network or API timeout.
"""
import asyncio
import logging
import time
from typing import Any, Dict, Optional, Tuple

import aiohttp
from council.regime_detector import MarketRegime

logger = logging.getLogger("KiBotV2.ExternalRegime")

EXTERNAL_REGIME_API_URL = "https://getregime.com/api/v1/market/regime"
CACHE_TTL_SECONDS = 300.0  # 5 minutes

REGIME_NUMERIC_MAP = {
    MarketRegime.BEAR: -1,
    MarketRegime.RANGE: 0,
    MarketRegime.UNKNOWN: 0,
    MarketRegime.BULL: 1,
}

class ExternalRegimeConsensus:
    def __init__(
        self,
        api_url: str = EXTERNAL_REGIME_API_URL,
        cache_ttl: float = CACHE_TTL_SECONDS,
        request_timeout: float = 4.0,
    ):
        self.api_url = api_url
        self.cache_ttl = cache_ttl
        self.request_timeout = request_timeout
        self._cached_data: Optional[Dict[str, Any]] = None
        self._last_fetch_ts: float = 0.0

    def _normalize_external_regime(self, raw_str: str) -> MarketRegime:
        s = str(raw_str).strip().lower()
        if "bull" in s:
            return MarketRegime.BULL
        elif "bear" in s:
            return MarketRegime.BEAR
        elif any(c in s for c in ["chop", "range", "sideway", "neutral"]):
            return MarketRegime.RANGE
        return MarketRegime.UNKNOWN

    async def fetch_external_regime(self, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
        """Fetches regime classification from getregime.com with 5-minute memory cache."""
        now = time.time()
        if not force_refresh and self._cached_data and (now - self._last_fetch_ts) < self.cache_ttl:
            return self._cached_data

        timeout = aiohttp.ClientTimeout(total=self.request_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.api_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        raw_regime = data.get("regime", "unknown")
                        normalized = self._normalize_external_regime(raw_regime)
                        
                        parsed = {
                            "raw_regime": raw_regime,
                            "normalized_regime": normalized,
                            "confidence": data.get("confidence", 0.0),
                            "signal_summary": data.get("signalSummary", {}),
                            "is_delayed": data.get("_delayed", False),
                            "fetched_at": now,
                        }
                        self._cached_data = parsed
                        self._last_fetch_ts = now
                        logger.info(f"[ExternalRegime] 🌐 getregime.com: {raw_regime} -> {normalized.value.upper()} (conf: {parsed['confidence']})")
                        return parsed
                    else:
                        logger.warning(f"[ExternalRegime] HTTP {resp.status} from getregime.com API")
                        return self._cached_data
        except Exception as exc:
            logger.warning(f"[ExternalRegime] Fetch error (fallback to internal): {exc}")
            return self._cached_data

    def compute_consensus(
        self,
        internal_regime: Any = None,
        internal_strength: Any = None,
        external_info: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Calculates consensus multiplier between internal and external regime signals.
        Supports:
          - compute_consensus(internal_dict, external_info)
          - compute_consensus(internal_regime, internal_strength, external_info)
          - compute_consensus(internal_regime=..., internal_strength=..., external_info=...)
        """
        if isinstance(internal_regime, dict):
            int_regime = internal_regime.get("regime", MarketRegime.RANGE)
            int_strength = float(internal_regime.get("strength", 50.0))
            ext_info = internal_strength if isinstance(internal_strength, dict) else external_info
        else:
            int_regime = internal_regime
            int_strength = float(internal_strength) if internal_strength is not None else 50.0
            ext_info = external_info

        if not ext_info or "normalized_regime" not in ext_info:
            return {
                "regime": int_regime,
                "strength": int_strength,
                "consensus_status": "FALLBACK_INTERNAL",
                "adjusted_strength": int_strength,
                "damping_multiplier": 1.0,
                "internal_regime": int_regime,
                "external_regime": None,
                "disagreement_distance": 0,
            }

        ext_regime = ext_info["normalized_regime"]
        int_val = REGIME_NUMERIC_MAP.get(int_regime, 0)
        ext_val = REGIME_NUMERIC_MAP.get(ext_regime, 0)
        distance = abs(int_val - ext_val)

        if distance == 0:
            multiplier = 1.0
            status = "AGREED"
        elif distance == 1:
            multiplier = 0.85
            status = "PARTIAL_DISAGREEMENT"
        else:  # distance == 2 (BULL vs BEAR)
            multiplier = 0.50
            status = "FULL_DISAGREEMENT"

        adjusted_strength = round(int_strength * multiplier, 2)
        return {
            "regime": int_regime,
            "strength": adjusted_strength,
            "consensus_status": status,
            "adjusted_strength": adjusted_strength,
            "damping_multiplier": multiplier,
            "internal_regime": int_regime,
            "external_regime": ext_regime,
            "disagreement_distance": distance,
        }

external_regime_consensus = ExternalRegimeConsensus()

async def fetch_external_regime(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    return await external_regime_consensus.fetch_external_regime(force_refresh=force_refresh)

def compute_consensus(
    internal_regime: Any = None,
    internal_strength: Any = None,
    external_info: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    return external_regime_consensus.compute_consensus(
        internal_regime=internal_regime,
        internal_strength=internal_strength,
        external_info=external_info,
        **kwargs,
    )

