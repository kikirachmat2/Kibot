import logging
import os
import asyncio
import json
from typing import Dict, Any, List, Optional
import aiohttp

from Core.Intelligence.defi_metrics_fetcher import DeFiMetricsFetcher
from Core.Support.ki_config import KiConfig

logger = logging.getLogger("PhantomOpportunityScout")

class PhantomOpportunityScout:
    """
    Phantom Opportunity Scout.
    Analyzes Web3 opportunities on Solana/EVM, simulates Jupiter swap routes, 
    evaluates DeFi yields, stablecoin swaps, slippage, and handles RPC failovers.
    Integrates paper/simulation guards for total safety.
    """
    def __init__(self, rpc_urls: Optional[List[str]] = None):
        self.rpc_urls = rpc_urls or [
            os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
            "https://solana-api.projectserum.com",
            "https://rpc.ankr.com/solana",
            "https://api.devnet.solana.com"
        ]
        self.active_rpc = self.rpc_urls[0]
        self.defi_fetcher = DeFiMetricsFetcher()
        self.state_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "state", "phantom_scout.json")
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        self.telemetry = {
            "active_rpc": self.active_rpc,
            "failed_rpcs": [],
            "simulated_opportunities_count": 0,
            "last_run_yields": {}
        }
        self._save_state()

    def _save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.telemetry, f, indent=4)
        except Exception as e:
            logger.warning(f"Failed to write phantom scout state: {e}")

    async def verify_and_failover_rpc(self) -> str:
        """
        Verify the active RPC endpoint and automatically fail over to alternative 
        endpoints if the active one times out or returns bad responses.
        """
        async def check_rpc(url: str) -> bool:
            try:
                payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=3) as resp:
                        if resp.status == 200:
                            res = await resp.json()
                            return res.get("result") == "ok" or "result" in res
            except Exception:
                pass
            return False

        # Try active RPC first
        if await check_rpc(self.active_rpc):
            return self.active_rpc

        logger.warning(f"⚠️ Primary RPC {self.active_rpc} is unresponsive. Initiating RPC failover...")
        if self.active_rpc not in self.telemetry["failed_rpcs"]:
            self.telemetry["failed_rpcs"].append(self.active_rpc)

        # Iterate over other RPCs
        for url in self.rpc_urls:
            if url == self.active_rpc:
                continue
            logger.info(f"Checking failover endpoint: {url}")
            if await check_rpc(url):
                logger.info(f"🎯 Switched active RPC to {url}")
                self.active_rpc = url
                self.telemetry["active_rpc"] = url
                self._save_state()
                return url

        # Fallback to devnet/mainnet default if all else fails
        fallback = self.rpc_urls[0]
        logger.error(f"🚨 All Solana RPC endpoints failed! Falling back to: {fallback}")
        self.active_rpc = fallback
        self.telemetry["active_rpc"] = fallback
        self._save_state()
        return fallback

    async def scout_jupiter_swap(
        self, 
        token_in: str, 
        token_out: str, 
        amount_in: float, 
        slippage_bps: int = 50
    ) -> Dict[str, Any]:
        """
        Simulate/scout a Jupiter swap route quote with price impact, slippage, and yield estimation.
        """
        self.telemetry["simulated_opportunities_count"] += 1
        
        # Stubs or real quote fetching
        is_live = KiConfig.LIVE_TRADING_ENABLED
        
        # Mints mapping for helper
        mint_names = {
            "So11111111111111111111111111111111111111112": "SOL",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT"
        }
        
        symbol_in = mint_names.get(token_in, "TOKEN_IN")
        symbol_out = mint_names.get(token_out, "TOKEN_OUT")
        
        result = {
            "token_in": token_in,
            "token_out": token_out,
            "symbol_in": symbol_in,
            "symbol_out": symbol_out,
            "amount_in": amount_in,
            "estimated_out": 0.0,
            "price_impact_pct": 0.0,
            "slippage_bps": slippage_bps,
            "best_route_path": "Jupiter DEX Aggregator V6",
            "pass_slippage_guard": True,
            "reason": "",
            "is_simulation": not is_live
        }
        
        if is_live:
            # Attempt to fetch dynamic quote from Jupiter API
            try:
                url = f"https://api.jup.ag/swap/v1/quote?inputMint={token_in}&outputMint={token_out}&amount={int(amount_in)}&slippageBps={slippage_bps}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            result["estimated_out"] = float(data.get("outAmount", 0))
                            result["price_impact_pct"] = float(data.get("priceImpactPct", 0.0)) * 100
                            # Check slippage guard
                            max_impact = 1.0 # Max 1% price impact allowed
                            if result["price_impact_pct"] > max_impact:
                                result["pass_slippage_guard"] = False
                                result["reason"] = f"Price impact {result['price_impact_pct']:.2f}% exceeds {max_impact}% limit."
                            return result
            except Exception as e:
                logger.warning(f"Could not fetch live Jupiter quote: {e}. Falling back to simulation.")

        # Simulation/Fallback Calculation
        # Assuming SOL-USDC exchange rate of $150
        exchange_rate = 1.0
        if symbol_in == "SOL" and symbol_out == "USDC":
            exchange_rate = 150.0
        elif symbol_in == "USDC" and symbol_out == "SOL":
            exchange_rate = 1.0 / 150.0
            
        result["estimated_out"] = amount_in * exchange_rate * 0.999 # minor execution loss
        result["price_impact_pct"] = 0.05  # extremely small simulated impact
        result["reason"] = "Paper simulation route approved cleanly."
        
        self._save_state()
        return result

    async def get_best_defi_opportunities(self) -> Dict[str, Any]:
        """
        Fetches and ranks the best DeFi yield opportunities across Solana protocols 
        using DeFi Llama fetcher metrics.
        """
        try:
            intel = await self.defi_fetcher.get_aggregated_defi_intelligence()
            yields = intel.get("yield_farming_apys", {})
            
            # Sort yields
            sorted_opportunities = sorted(yields.items(), key=lambda item: item[1], reverse=True)
            
            best_opt = {
                "highest_apy_protocol": sorted_opportunities[0][0] if sorted_opportunities else "kamino_apy",
                "highest_apy": sorted_opportunities[0][1] if sorted_opportunities else 8.5,
                "all_opportunities": yields,
                "regime": intel.get("market_regime_hints", "DeFi yields STABLE")
            }
            
            self.telemetry["last_run_yields"] = yields
            self._save_state()
            return best_opt
        except Exception as e:
            logger.error(f"Error scouting DeFi opportunities: {e}")
            return {
                "highest_apy_protocol": "kamino_apy",
                "highest_apy": 8.5,
                "all_opportunities": {"kamino_apy": 8.5, "jito_staking_apy": 7.5},
                "regime": "DeFi yields STABLE (Mocked)"
            }
