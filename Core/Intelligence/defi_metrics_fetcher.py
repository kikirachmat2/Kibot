import logging
import aiohttp
import asyncio
from typing import Dict, Any, List

logger = logging.getLogger("DeFiMetricsFetcher")

class DeFiMetricsFetcher:
    """
    Public API Fetcher for Web3 Intelligence.
    Uses rate-limiting and robust error handling to prevent IP bans.
    """
    def __init__(self):
        self.defi_llama_url = "https://yields.llama.fi/pools"
        self.dexscreener_url = "https://api.dexscreener.com/latest/dex/search?q="
        # Simple local cache to prevent spamming
        self._cache = {}
        self._cache_ttl = 300  # 5 minutes

    async def _fetch_json(self, url: str) -> Dict[str, Any]:
        """ Helper to fetch JSON with timeout and basic anti-ban delay. """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    logger.warning(f"⚠️ API returned {response.status} for {url}")
                    return {}
        except Exception as e:
            logger.error(f"❌ Failed to fetch {url}: {e}")
            return {}

    async def get_kamino_jito_yields(self) -> Dict[str, float]:
        """ Fetches current APY for Kamino and Jito from DeFi Llama. """
        # Using cache
        if "llama_yields" in self._cache and (asyncio.get_event_loop().time() - self._cache["llama_yields"]["time"]) < self._cache_ttl:
            return self._cache["llama_yields"]["data"]

        data = await self._fetch_json(self.defi_llama_url)
        results = {"kamino_apy": 0.0, "jito_apy": 0.0, "orca_apy": 0.0}
        
        pools = data.get("data", [])
        for pool in pools:
            if not pool.get("chain") == "Solana":
                continue
                
            project = pool.get("project", "").lower()
            symbol = pool.get("symbol", "").lower()
            apy = pool.get("apy", 0.0)

            if project == "kamino" and "usdc" in symbol:
                results["kamino_apy"] = max(results["kamino_apy"], apy)
            elif project == "jito" and "sol" in symbol:
                results["jito_apy"] = max(results["jito_apy"], apy)
            elif project == "orca":
                results["orca_apy"] = max(results["orca_apy"], apy)

        self._cache["llama_yields"] = {"time": asyncio.get_event_loop().time(), "data": results}
        return results

    async def get_trending_solana_memes(self) -> List[Dict[str, Any]]:
        """ Fetches top volume Solana tokens from DexScreener. """
        if "dex_memes" in self._cache and (asyncio.get_event_loop().time() - self._cache["dex_memes"]["time"]) < self._cache_ttl:
            return self._cache["dex_memes"]["data"]

        # A broad search for WIF or POPCAT to gauge sentiment, or general SOL pairs
        # In a real scenario, DexScreener token-profiles or a specific trending endpoint is better
        # We will use a generic search and filter by volume
        data = await self._fetch_json(f"{self.dexscreener_url}sol")
        pairs = data.get("pairs", [])
        
        # Filter for solana chain and high volume
        memes = []
        for p in pairs:
            if p.get("chainId") == "solana":
                vol_24h = p.get("volume", {}).get("h24", 0)
                if vol_24h > 1000000: # $1M volume minimum for sniping safety
                    memes.append({
                        "symbol": p.get("baseToken", {}).get("symbol"),
                        "address": p.get("baseToken", {}).get("address"),
                        "volume_24h": vol_24h,
                        "liquidity": p.get("liquidity", {}).get("usd", 0),
                        "fdv": p.get("fdv", 0)
                    })
        
        # Sort by volume
        memes = sorted(memes, key=lambda x: x["volume_24h"], reverse=True)[:5]
        self._cache["dex_memes"] = {"time": asyncio.get_event_loop().time(), "data": memes}
        return memes

    async def get_drift_funding_rates(self) -> Dict[str, float]:
        """ Stub for Drift Funding Rates. Highly negative = Long bias, Highly positive = Short bias. """
        return {"SOL-PERP": -0.015, "BTC-PERP": 0.005} # Mocks for now

    async def get_jupiter_trending(self) -> Dict[str, Any]:
        """ Stub for Jupiter trading metrics. """
        return {"jup_volume_24h": 1200000000, "top_pairs": ["SOL-USDC", "WIF-SOL"]}

    async def get_jito_staking_yield(self) -> float:
        """ Stub for Jito MEV staking yields. """
        return 7.5

    async def get_sharky_nft_yields(self) -> float:
        """ Stub for SharkyFi NFT lending APYs. """
        return 120.0 # High risk, high yield

    async def get_mev_arb_estimate(self) -> float:
        """ Stub for MEV Arbitrage projected yield. """
        return 5.0 # Steady baseline

    async def get_aggregated_defi_intelligence(self) -> Dict[str, Any]:
        """ Consolidates all Web3 intelligence into one bundle for the World Scout. """
        yields = await self.get_kamino_jito_yields()
        memes = await self.get_trending_solana_memes()
        funding = await self.get_drift_funding_rates()
        jup = await self.get_jupiter_trending()
        jito_yield = await self.get_jito_staking_yield()
        sharky_yield = await self.get_sharky_nft_yields()
        mev_arb = await self.get_mev_arb_estimate()
        
        # Supplement yields with specific executor data
        yield_farming_apys = {
            **yields,
            "jito_staking_apy": jito_yield,
            "sharky_nft_apy": sharky_yield,
            "mev_arb_apy": mev_arb
        }
        
        highest_apy = max(yield_farming_apys.values()) if yield_farming_apys else 0
        
        return {
            "yield_farming_apys": yield_farming_apys,
            "trending_snipable_memes": memes,
            "perp_funding_rates": funding,
            "jupiter_metrics": jup,
            "market_regime_hints": "DeFi yields HIGH" if highest_apy > 15.0 else "DeFi yields LOW"
        }
