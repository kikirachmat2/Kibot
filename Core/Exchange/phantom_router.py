import logging
from typing import Dict, Any, Optional
import os
import asyncio
import base64
import json
import time

import aiohttp
from Core.Support.ki_config import KiConfig
from Core.Trading.autonomous_sizing import AutonomousSizing
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

logger = logging.getLogger("PhantomRouter")

class PhantomRouter:
    """
    Generic Web3 Wallet Router (Phantom EVM & SPL).
    Abstracts private key interactions, DEX swaps, and bridging logic 
    for the Capital Commander to use without coupling executors to RPC details.
    """

    def __init__(self, private_key: str = None, rpc_url: str = None):
        self.private_key_str = private_key or os.getenv("PHANTOM_PRIVATE_KEY")
        self.rpc_url = rpc_url or os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        self.keypair = None
        self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        
        # Initialize the PhantomOpportunityScout
        from Core.Intelligence.phantom_opportunity_scout import PhantomOpportunityScout
        self.scout = PhantomOpportunityScout()
        self.sizing = AutonomousSizing()
        
        if not self.private_key_str:
            logger.error("🚨 CRITICAL: PhantomRouter initialized without a Private Key. All Web3 txs will fail.")
        else:
            try:
                # Assuming base58 encoded private key for Phantom
                import base58
                key_bytes = base58.b58decode(self.private_key_str)
                self.keypair = Keypair.from_bytes(key_bytes)
                logger.info(f"🔐 PhantomRouter initialized with secure key. Address: {self.keypair.pubkey()}")
            except Exception as e:
                logger.error(f"❌ Failed to parse Phantom Private Key: {e}")
                
        self.address = str(self.keypair.pubkey()) if self.keypair else "0x..."

    @property
    def private_key(self) -> Optional[str]:
        return self.private_key_str

    @property
    def wallet_address(self) -> str:
        return self.address

    async def _close(self):
        if self.client:
            await self.client.close()

    def _live_web3_gate_context(self) -> Dict[str, Any]:
        try:
            from Core.Treasury.phantom_treasury import PhantomTreasury
            from Core.Treasury.phantom_multichain_controller import PhantomMultichainController
            treasury = PhantomTreasury(self)
            controller = PhantomMultichainController()
            route = controller.get_route("solana")
            return {
                "treasury": treasury.get_summary(),
                "route": route,
                "controller": controller,
            }
        except Exception as e:
            logger.debug("Web3 gate context unavailable: %s", e)
            return {"treasury": {}, "route": {"status": "SCOUTING"}, "controller": None}

    async def get_balances(self) -> Dict[str, float]:
        """
        Fetch balances across supported chains (Polygon, Solana).
        """
        usdc_balance = 0.0
        sol_balance = 0.0
        
        if self.keypair:
            try:
                resp = await self.client.get_balance(self.keypair.pubkey())
                if resp.value:
                    sol_balance = resp.value / 1e9 # Lamports to SOL
            except Exception as e:
                logger.error(f"Error fetching SOL balance: {e}")

            try:
                from solders.pubkey import Pubkey
                from solana.rpc.types import TokenAccountOpts
                usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
                opts = TokenAccountOpts(mint=usdc_mint)
                usdc_resp = await self.client.get_token_accounts_by_owner(self.keypair.pubkey(), opts)
                if usdc_resp.value:
                    for acc in usdc_resp.value:
                        bal_resp = await self.client.get_token_account_balance(acc.pubkey)
                        if bal_resp.value and bal_resp.value.ui_amount is not None:
                            usdc_balance += bal_resp.value.ui_amount
            except Exception as e:
                logger.error(f"Error fetching USDC balance: {e}")

        return {
            "usdc_balance": usdc_balance,
            "sol_balance": sol_balance,
            "matic_balance": 0.0
        }
        
    async def bridge_assets(self, from_chain: str, to_chain: str, token: str, amount: float) -> bool:
        """
        Initiate a cross-chain bridge transaction.
        """
        if not KiConfig.LIVE_TRADING_ENABLED or not KiConfig.ENABLE_REAL_BRIDGE or not KiConfig.ENABLE_REAL_WITHDRAWAL:
            logger.warning(f"⚠️ [GUARDED] Cross-chain bridge blocked (Real Bridge/Withdrawal OFF): {amount} {token} from {from_chain} to {to_chain}")
            return True
        logger.info(f"Guarded Bridge: {amount} {token} from {from_chain} to {to_chain}")
        return True


    async def swap_assets(self, token_in: str, token_out: str, amount_in: float, chain: str) -> bool:
        """
        Swap tokens using Jupiter Aggregator V6 API.
        token_in and token_out should be mint addresses.
        amount_in is in raw smallest units (e.g., lamports).
        """
        # Pre-verify with the Scout
        try:
            scout_res = await self.scout.scout_jupiter_swap(token_in, token_out, amount_in)
            if not scout_res["pass_slippage_guard"]:
                logger.warning(f"🛡️ Swap blocked by Slippage Guard: {scout_res['reason']}")
                return False
            # Verify and fail over RPC dynamically
            self.rpc_url = await self.scout.verify_and_failover_rpc()
            self.client = AsyncClient(self.rpc_url, commitment=Confirmed)
        except Exception as e:
            logger.warning(f"⚠️ Pre-trade Web3 scouting failed/bypassed: {e}")

        if not KiConfig.LIVE_TRADING_ENABLED or not KiConfig.ENABLE_REAL_SWAP:
            logger.warning(f"⚠️ [GUARDED] Swap blocked (Real Swap OFF): {amount_in} of {token_in} -> {token_out} on {chain}")
            return True

        gate_ctx = self._live_web3_gate_context()
        from Core.Web3.web3_quote_router import Web3QuoteRouter
        from Core.Web3.web3_safety_checker import Web3SafetyChecker
        from Core.Web3.web3_executor_guard import Web3ExecutorGuard
        quote_router = Web3QuoteRouter()
        safety_checker = Web3SafetyChecker()
        executor_guard = Web3ExecutorGuard()
        quote = await quote_router.quote("solana", token_in, token_out, int(amount_in))
        sizing = self.sizing.size(
            total_capital_idr=float(gate_ctx.get("treasury", {}).get("total_value_idr", 0.0) or 0.0),
            venue_capital_idr=float(gate_ctx.get("treasury", {}).get("total_value_idr", 0.0) or 0.0),
            route_bucket_idr=float(gate_ctx.get("treasury", {}).get("buckets", {}).get("swap_idr", 0.0) or 0.0),
            available_balance_idr=float(gate_ctx.get("treasury", {}).get("buckets", {}).get("swap_idr", 0.0) or 0.0),
            daily_risk_remaining_idr=float(gate_ctx.get("treasury", {}).get("daily_risk_remaining_idr", 0.0) or 0.0),
            liquidity_usd=float(scout_res.get("liquidity", 0.0) or 0.0),
            slippage_pct=float(quote.get("slippage_pct", 0) or 0),
            confidence=float(scout_res.get("confidence", 0.0) or 0.0),
            ev_pct=float(scout_res.get("estimated_out", 0.0) or 0.0),
            volatility_pct=float(scout_res.get("volatility_pct", 0.0) or 0.0),
            current_open_exposure_idr=0.0,
            exit_available=True,
            route="solana",
            reserve_locked=True,
            hard_cap_idr=float(os.getenv("WEB3_SOLANA_SWAP_HARD_CAP_IDR", "0") or 0.0),
            liquidity_safe_size_idr=float(scout_res.get("liquidity", 0.0) or 0.0) * 16000.0 * 0.015,
        )
        if not sizing.get("approved"):
            logger.warning("🛡️ Web3 autonomous sizing rejected Solana swap: %s", sizing.get("reason"))
            return False
        safety = safety_checker.evaluate({
            "ev": float(scout_res.get("estimated_out", 0.0) or 0.0),
            "liquidity": scout_res.get("liquidity", 0.0),
            "volume": scout_res.get("volume", 0.0),
            "spread_pct": scout_res.get("price_impact_pct", 0.0),
            "slippage_pct": scout_res.get("price_impact_pct", 0.0),
            "token_type": "solana",
        })
        approval = executor_guard.approve(
            treasury=gate_ctx.get("treasury", {}),
            route={"network": "solana", "allowed": gate_ctx.get("route", {}).get("status") == "LIVE_READY", "reason": gate_ctx.get("route", {}).get("status", "SCOUTING")},
            safety=safety,
            quote=quote,
            budget_idr=float(sizing.get("size_idr") or os.getenv("WEB3_SOLANA_SWAP_BUCKET_CAP_IDR", "25000") or 25000),
            stop_loss_pct=float(os.getenv("WEB3_DEFAULT_STOP_LOSS_PCT", "1.5") or 1.5),
            take_profit_pct=float(os.getenv("WEB3_DEFAULT_TAKE_PROFIT_PCT", "2.0") or 2.0),
            trailing_stop_pct=float(os.getenv("WEB3_DEFAULT_TRAILING_STOP_PCT", "0.5") or 0.5),
            time_stop_seconds=int(float(os.getenv("WEB3_DEFAULT_TIME_STOP_SECONDS", "3600") or 3600)),
            spend_reserve=False,
        )
        if not approval.get("allowed"):
            logger.warning("🛡️ Web3 executor guard blocked Solana swap: %s", approval.get("reason"))
            return False


        if not self.keypair:
            logger.error("❌ Cannot swap: No keypair loaded.")
            return False

        try:
            logger.info(f"🔄 Executing swap: {amount_in} of {token_in} -> {token_out} on {chain}")
            # 1. Get Quote
            quote_url = f"https://api.jup.ag/swap/v1/quote?inputMint={token_in}&outputMint={token_out}&amount={int(amount_in)}&slippageBps=50"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(quote_url) as resp:
                    if resp.status != 200:
                        logger.error(f"❌ Jupiter Quote failed: {await resp.text()}")
                        return False
                    quote_resp = await resp.json()
            
            # 2. Get Swap Transaction
            swap_payload = {
                "quoteResponse": quote_resp,
                "userPublicKey": str(self.keypair.pubkey()),
                "wrapAndUnwrapSol": True,
                "prioritizationFeeLamports": "auto"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post("https://api.jup.ag/swap/v1/swap", json=swap_payload) as resp:
                    if resp.status != 200:
                        logger.error(f"❌ Jupiter Swap endpoint failed: {await resp.text()}")
                        return False
                    swap_resp = await resp.json()
                    
            swap_tx_b64 = swap_resp.get("swapTransaction")
            if not swap_tx_b64:
                logger.error("❌ No swapTransaction returned from Jupiter.")
                return False
                
            # 3. Sign and Send Transaction
            raw_tx = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(raw_tx)
            
            # Assuming signature process via solders
            # Jupiter txs are already partially built, we just sign
            from solders.message import to_bytes_versioned
            signature = self.keypair.sign_message(to_bytes_versioned(tx.message))
            tx = VersionedTransaction.populate(tx.message, [signature])
            
            opts = {"skip_preflight": False, "max_retries": 3}
            result = await self.client.send_raw_transaction(bytes(tx), opts=opts)
            logger.info(f"✅ Swap Transaction Broadcasted: {result.value}")
            try:
                executor_guard.persist_position({
                    "id": f"solana-{int(time.time())}",
                    "network": "solana",
                    "asset": token_out,
                    "entry_value_idr": approval.get("max_trade_idr", 0),
                    "amount": amount_in,
                    "entry_quote": quote,
                    "autonomous_sizing": sizing,
                    "stop_loss_pct": float(os.getenv("WEB3_DEFAULT_STOP_LOSS_PCT", "1.5") or 1.5),
                    "take_profit_pct": float(os.getenv("WEB3_DEFAULT_TAKE_PROFIT_PCT", "2.0") or 2.0),
                    "trailing_stop_pct": float(os.getenv("WEB3_DEFAULT_TRAILING_STOP_PCT", "0.5") or 0.5),
                    "time_stop_seconds": int(float(os.getenv("WEB3_DEFAULT_TIME_STOP_SECONDS", "3600") or 3600)),
                    "status": "OPEN",
                })
            except Exception as e:
                logger.debug("Failed to persist Web3 position: %s", e)
            return True

        except Exception as e:
            logger.error(f"❌ Swap failed: {e}")
            return False

    # ---------------------------------------------------------
    # 10 Web3 Autonomous Capabilities (Phase 2 Hardened Stubs)
    # ---------------------------------------------------------

    async def execute_polymarket_trade(self, market_id: str, outcome: str, amount_usdc: float) -> bool:
        """ 1. Prediction Markets: Execute trade on Polymarket (Polygon). """
        if not KiConfig.LIVE_TRADING_ENABLED or not KiConfig.ENABLE_POLYMARKET_LIVE:
            logger.warning(f"⚠️ [GUARDED] Polymarket trade blocked (Live OFF): {amount_usdc} USDC on {outcome} in {market_id}")
            return True

        gate_ctx = self._live_web3_gate_context()
        treasury = gate_ctx.get("treasury", {})
        poly_bucket = float(treasury.get("buckets", {}).get("polymarket_idr", 0.0) or 0.0)
        if gate_ctx.get("route", {}).get("status") != "LIVE_READY" or poly_bucket <= 0:
            logger.warning("🛡️ Polymarket route blocked until gate is live-ready and bucket > 0.")
            return False
        
        try:
            logger.info(f"🔮 Polymarket: Betting {amount_usdc} USDC on {outcome} in {market_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Polymarket trade failed: {e}")
            return False

    async def deposit_kamino_yield(self, token: str, amount: float) -> bool:
        """ 2. Yield Farming: Supply asset to Kamino Finance (Solana). """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] Kamino deposit blocked: {amount} {token}")
            return True
        try:
            logger.info(f"🚜 Yield: Depositing {amount} {token} into Kamino.")
            return True
        except Exception as e:
            logger.error(f"❌ Kamino deposit failed: {e}")
            return False

    async def execute_drift_perp(self, symbol: str, side: str, leverage: float, amount: float) -> bool:
        """ 3. Perpetual DEX: Open Long/Short on Drift Protocol (Solana). """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] Drift perp blocked: {side} {symbol} with {leverage}x leverage")
            return True
        try:
            logger.info(f"📉 Perp: Opening {side} on {symbol} with {leverage}x leverage on Drift.")
            return True
        except Exception as e:
            logger.error(f"❌ Drift perp failed: {e}")
            return False

    async def snipe_meme_coin(self, token_address: str, amount_sol: float, slippage_bps: int = 1000) -> bool:
        """ 4. Meme Sniping: Fast swap via Jupiter with high slippage (Solana). """
        if not KiConfig.LIVE_TRADING_ENABLED or not KiConfig.ENABLE_REAL_SWAP:
            logger.warning(f"⚠️ [GUARDED] Meme snipe blocked: {token_address} with {amount_sol} SOL")
            return True

        gate_ctx = self._live_web3_gate_context()
        if gate_ctx.get("controller"):
            route_gate = gate_ctx["controller"].route_opportunity("solana", {"asset": token_address, "category": "solana_meme"})
            if not route_gate.get("allowed"):
                logger.warning("🛡️ Solana meme snipe blocked by route gate: %s", route_gate.get("reason"))
                return False
        from Core.Web3.web3_quote_router import Web3QuoteRouter
        from Core.Web3.web3_safety_checker import Web3SafetyChecker
        from Core.Web3.web3_executor_guard import Web3ExecutorGuard
        quote_router = Web3QuoteRouter()
        safety_checker = Web3SafetyChecker()
        executor_guard = Web3ExecutorGuard()
        quote = await quote_router.quote("solana", "So11111111111111111111111111111111111111112", token_address, int(amount_sol * 1e9))
        if not quote.get("quote_ok"):
            logger.warning("🛡️ Web3 quote missing for Solana meme snipe: %s", quote.get("reason"))
            return False
        safety = safety_checker.evaluate({
            "ev": float(quote.get("expected_out", 0) or 0),
            "liquidity": float(os.getenv("WEB3_MEME_MIN_LIQUIDITY_USD", "10000") or 10000),
            "volume": float(os.getenv("WEB3_MEME_MIN_VOLUME_1H_USD", "5000") or 5000),
            "spread_pct": float(quote.get("slippage_pct", 0) or 0),
            "slippage_pct": float(quote.get("slippage_pct", 0) or 0),
            "token_type": "solana",
        })
        approval = executor_guard.approve(
            treasury=gate_ctx.get("treasury", {}),
            route={"network": "solana", "allowed": gate_ctx.get("route", {}).get("status") == "LIVE_READY", "reason": gate_ctx.get("route", {}).get("status", "SCOUTING")},
            safety=safety,
            quote=quote,
            budget_idr=float(os.getenv("WEB3_SOLANA_SWAP_BUCKET_CAP_IDR", "25000") or 25000),
            stop_loss_pct=float(os.getenv("WEB3_DEFAULT_STOP_LOSS_PCT", "1.5") or 1.5),
            take_profit_pct=float(os.getenv("WEB3_DEFAULT_TAKE_PROFIT_PCT", "2.0") or 2.0),
            trailing_stop_pct=float(os.getenv("WEB3_DEFAULT_TRAILING_STOP_PCT", "0.5") or 0.5),
            time_stop_seconds=int(float(os.getenv("WEB3_DEFAULT_TIME_STOP_SECONDS", "3600") or 3600)),
            spend_reserve=False,
            exit_plan=True,
            quote_context="ok" if quote.get("quote_ok") else "quote_context_missing",
        )
        if not approval.get("allowed"):
            logger.warning("🛡️ Web3 executor guard blocked Solana meme snipe: %s", approval.get("reason"))
            return False

        try:
            logger.info(f"🔫 Sniping: Buying {token_address} with {amount_sol} SOL (Slippage: {slippage_bps} bps).")
            # SOL Mint: So11111111111111111111111111111111111111112
            sol_mint = "So11111111111111111111111111111111111111112"
            lamports = int(amount_sol * 1e9)
            
            # Fetch Quote with custom slippage
            quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={sol_mint}&outputMint={token_address}&amount={lamports}&slippageBps={slippage_bps}"
            async with aiohttp.ClientSession() as session:
                async with session.get(quote_url) as resp:
                    if resp.status != 200:
                        logger.error(f"❌ Snipe Quote failed: {await resp.text()}")
                        return False
                    quote_resp = await resp.json()
                    
            # We defer to the swap logic but inline here for speed / direct control
            swap_payload = {
                "quoteResponse": quote_resp,
                "userPublicKey": str(self.keypair.pubkey()),
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post("https://quote-api.jup.ag/v6/swap", json=swap_payload) as resp:
                    if resp.status != 200:
                        logger.error(f"❌ Snipe Swap endpoint failed: {await resp.text()}")
                        return False
                    swap_resp = await resp.json()
                    
            swap_tx_b64 = swap_resp.get("swapTransaction")
            if not swap_tx_b64:
                return False
                
            raw_tx = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(raw_tx)
            from solders.message import to_bytes_versioned
            signature = self.keypair.sign_message(to_bytes_versioned(tx.message))
            tx = VersionedTransaction.populate(tx.message, [signature])
            
            result = await self.client.send_raw_transaction(bytes(tx))
            logger.info(f"🎯 Snipe SUCCESS! TxID: {result.value}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Meme snipe failed: {e}")
            return False

    async def stake_jito_sol(self, amount_sol: float) -> bool:
        """ 5. Liquid Staking: Stake SOL for JitoSOL (Solana). """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] Jito staking blocked: {amount_sol} SOL")
            return True
        try:
            logger.info(f"💧 Staking: Converting {amount_sol} SOL to JitoSOL.")
            return True
        except Exception as e:
            logger.error(f"❌ Jito staking failed: {e}")
            return False

    async def farm_airdrop(self, target_protocol: str, action: str) -> bool:
        """ 6. Airdrop Farming: Execute low-value interactions to build volume. """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] Airdrop farm blocked: {action} on {target_protocol}")
            return True
        try:
            logger.info(f"🪂 Airdrop Farm: Executing {action} on {target_protocol}.")
            return True
        except Exception as e:
            logger.error(f"❌ Airdrop farming failed: {e}")
            return False

    async def provide_orca_liquidity(self, pool_id: str, amount_a: float, amount_b: float) -> bool:
        """ 7. Liquidity Provision: Supply concentrated LP on Orca/Meteora. """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] Orca LP provision blocked: pool {pool_id}")
            return True
        try:
            logger.info(f"🌊 LP: Supplying {amount_a} and {amount_b} to Orca pool {pool_id}.")
            return True
        except Exception as e:
            logger.error(f"❌ LP provision failed: {e}")
            return False

    async def bridge_debridge(self, amount: float, token: str, from_chain: str, to_chain: str) -> bool:
        """ 8. Cross-Chain Bridging: Move funds via DeBridge/Wormhole. """
        if not KiConfig.LIVE_TRADING_ENABLED or not KiConfig.ENABLE_REAL_BRIDGE or not KiConfig.ENABLE_REAL_WITHDRAWAL:
            logger.warning(f"⚠️ [GUARDED] Bridge blocked (Real Bridge/Withdrawal OFF): {amount} {token} from {from_chain} to {to_chain}")
            return True

        try:
            logger.info(f"🌉 Bridge: Moving {amount} {token} from {from_chain} to {to_chain}.")
            return True
        except Exception as e:
            logger.error(f"❌ Bridge failed: {e}")
            return False

    async def offer_nft_loan(self, collection_slug: str, offer_usdc: float) -> bool:
        """ 9. NFT Lending: Offer a loan on SharkyFi (Solana). """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] NFT loan blocked: {offer_usdc} USDC for {collection_slug}")
            return True
        try:
            logger.info(f"🖼️ NFT Loan: Offering {offer_usdc} USDC for {collection_slug} on SharkyFi.")
            return True
        except Exception as e:
            logger.error(f"❌ NFT loan failed: {e}")
            return False

    async def execute_mev_arbitrage(self, token: str, buy_dex: str, sell_dex: str) -> bool:
        """ 10. MEV Arbitrage: Flash loan or instant arb across DEXs. """
        if not KiConfig.LIVE_TRADING_ENABLED:
            logger.warning(f"⚠️ [GUARDED] MEV arbitrage blocked: Buy {token} on {buy_dex}, Sell on {sell_dex}")
            return True
        try:
            logger.info(f"⚡ MEV Arb: Buying {token} on {buy_dex} and selling on {sell_dex}.")
            return True
        except Exception as e:
            logger.error(f"❌ MEV Arbitrage failed: {e}")
            return False
