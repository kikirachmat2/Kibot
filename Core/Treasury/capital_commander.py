import logging
import asyncio
from typing import Dict, Any, Optional

from Core.Exchange.bridge_router import BridgeRouter

logger = logging.getLogger("CapitalCommander")

class CapitalCommander:
    """
    Sovereign Capital Treasury Commander.
    Orchestrates capital distribution across all integrated exchanges and wallets
    (Indodax, Polymarket, Solana, Global CEX) based on the Sovereign Council's directives.
    """

    def __init__(self, indodax_gateway, phantom_router):
        self.indodax = indodax_gateway
        self.phantom = phantom_router
        self.bridge = BridgeRouter(self.phantom, self.indodax)
        self.total_equity_idr = 0.0
        
        # Load the 10 Sovereign Web3 Executors safely
        self.web3_executors = self._load_web3_executors()
        
        # Regime-based target allocations
        self.allocations = {
            "BULL": {"indodax_spot": 0.30, "phantom_meme": 0.20, "polymarket": 0.10, "defi_yield": 0.10, "defi_perp": 0.0, "defi_nft": 0.15, "mev_arb": 0.15},
            "CRAB": {"indodax_spot": 0.20, "phantom_meme": 0.05, "polymarket": 0.20, "defi_yield": 0.30, "defi_perp": 0.10, "defi_nft": 0.15, "mev_arb": 0.0},
            "BEAR": {"indodax_spot": 0.20, "phantom_meme": 0.00, "polymarket": 0.10, "defi_yield": 0.30, "defi_perp": 0.40, "defi_nft": 0.00, "mev_arb": 0.0}
        }

    def _load_web3_executors(self):
        executors = {}
        if not self.phantom or not self.phantom.private_key:
            logger.warning("⚠️ PhantomRouter unavailable or unkeyed. Web3 Executors will remain offline.")
            return executors
            
        try:
            from Core.Executors.Phantom.polymarket_executor import PolymarketExecutor
            from Core.Executors.Phantom.kamino_yield_executor import KaminoYieldExecutor
            from Core.Executors.Phantom.drift_perp_executor import DriftPerpExecutor
            from Core.Executors.Phantom.jupiter_sniper_executor import JupiterSniperExecutor
            from Core.Executors.Phantom.jito_staking_executor import JitoStakingExecutor
            from Core.Executors.Phantom.airdrop_farmer_executor import AirdropFarmerExecutor
            from Core.Executors.Phantom.orca_lp_executor import OrcaLPExecutor
            from Core.Executors.Phantom.debridge_executor import DeBridgeExecutor
            from Core.Executors.Phantom.sharky_nft_executor import SharkyNFTExecutor
            from Core.Executors.Phantom.mev_arbitrage_executor import MEVArbitrageExecutor
            
            # Since polymarket is custom, we might wrap it differently, but for standard ones:
            executors["polymarket"] = PolymarketExecutor(self.phantom)
            executors["kamino"] = KaminoYieldExecutor(self.phantom)
            executors["drift"] = DriftPerpExecutor(self.phantom)
            executors["jupiter"] = JupiterSniperExecutor(self.phantom)
            executors["jito"] = JitoStakingExecutor(self.phantom)
            executors["airdrop"] = AirdropFarmerExecutor(self.phantom)
            executors["orca"] = OrcaLPExecutor(self.phantom)
            executors["debridge"] = DeBridgeExecutor(self.phantom)
            executors["sharky"] = SharkyNFTExecutor(self.phantom)
            executors["mev"] = MEVArbitrageExecutor(self.phantom)
            
            logger.info("✅ All 10 Web3 Sovereign Executors successfully locked and loaded.")
        except ImportError as e:
            logger.warning(f"⚠️ Could not load all Web3 Executors (check imports): {e}")
        except Exception as e:
            logger.error(f"❌ Unexpected error loading Web3 Executors: {e}")
            
        return executors

    async def safe_execute(self, executor_name: str, method_name: str, *args, timeout: int = 30, **kwargs) -> bool:
        """
        Hardened Wrapper: Prevents any Web3 RPC call from hanging the MasterNode event loop.
        """
        if executor_name not in self.web3_executors:
            logger.error(f"❌ Executor {executor_name} not available in CapitalCommander.")
            return False
            
        executor = self.web3_executors[executor_name]
        method = getattr(executor, method_name, None)
        
        if not method or not callable(method):
            logger.error(f"❌ Method {method_name} not found on {executor_name}.")
            return False
            
        try:
            # Wrap execution with a strict timeout circuit breaker
            result = await asyncio.wait_for(method(*args, **kwargs), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"🛑 CIRCUIT BREAKER: {executor_name}.{method_name} timed out after {timeout}s.")
            return False
        except Exception as e:
            logger.error(f"❌ EXECUTION FAILED: {executor_name}.{method_name} encountered an error: {e}")
            return False

    async def get_treasury_snapshot(self) -> Dict[str, Any]:
        """
        Aggregates balance across all active treasury routes with hardened fallbacks.
        """
        snapshot = {
            "indodax": {"cash_idr": 0.0, "crypto_value_idr": 0.0},
            "phantom": {"usdc_balance": 0.0, "sol_balance": 0.0},
            "global_cex": {"usdt_balance": 0.0},
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

        # 2. Fetch Phantom (Web3)
        if self.phantom:
            try:
                phantom_balances = await asyncio.wait_for(self.phantom.get_balances(), timeout=10)
                snapshot["phantom"] = phantom_balances
            except Exception as e:
                logger.error(f"Failed to fetch Phantom treasury: {e}")

        usd_idr_rate = 16000
        snapshot["total_equity_idr"] = (
            snapshot["indodax"]["cash_idr"] +
            (snapshot["phantom"]["usdc_balance"] * usd_idr_rate)
        )
        self.total_equity_idr = snapshot["total_equity_idr"]

        return snapshot

    def request_allocation(self, route: str, requested_amount_idr: float, current_regime: str) -> bool:
        if not self.total_equity_idr:
            logger.warning("Treasury snapshot missing, denying allocation.")
            return False

        regime_targets = self.allocations.get(current_regime.upper(), self.allocations["CRAB"])
        
        if route.lower() not in regime_targets:
            logger.warning(f"Route {route} not supported in regime {current_regime}")
            return False
            
        target_pct = regime_targets[route.lower()]
        max_allowed = self.total_equity_idr * target_pct
        
        if requested_amount_idr <= max_allowed:
            logger.info(f"✅ Treasury Approved: {requested_amount_idr:,.0f} IDR for {route}")
            return True
            
        logger.warning(f"❌ Treasury Denied: {requested_amount_idr:,.0f} IDR exceeds max {max_allowed:,.0f} for {route}")
        return False

    async def bridge_phantom_to_indodax(self, amount_usdc: float, indodax_deposit_address: str):
        """ [FULL-AUTO] Sweeps capital from Web3 back to Fiat (Indodax). """
        logger.info(f"💸 Initiating FULL-AUTO transfer: {amount_usdc} USDC from Phantom to Indodax.")
        return await self.safe_execute("debridge", "execute_bridge", amount_usdc, "USDC", "Solana", "Indodax")

    async def bridge_indodax_to_phantom(self, amount_idr_equiv: float, target_network: str = "all", target_apy: float = 0.0):
        """ [FULL-AUTO] Sweeps capital from Indodax to Web3 (Phantom) via dynamic BridgeRouter. """
        if not self.phantom or not self.phantom.wallet_address:
            logger.error("❌ Phantom Router not configured. Cannot bridge.")
            return False
            
        logger.info(f"🏦 Initiating FULL-AUTO transfer: {amount_idr_equiv:,.0f} IDR to Phantom ({self.phantom.wallet_address}).")
        
        success = await self.bridge.auto_bridge_to_phantom(
            amount_idr=amount_idr_equiv,
            destination_address=self.phantom.wallet_address,
            target_network=target_network,
            target_apy=target_apy
        )
        return success
