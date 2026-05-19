import logging
from typing import Dict, Any

from Core.Exchange.indodax import IndodaxGateway
from Core.Intelligence.defi_metrics_fetcher import DeFiMetricsFetcher
from Core.Support.ki_utils import telegram_send
from Core.Support.ki_config import KiConfig

logger = logging.getLogger("BridgeRouter")

class BridgeRouter:
    """
    Cross-Chain Bridge Router
    Handles bridging assets between Indodax (CEX) and Phantom (Web3 DeFi).
    """

    # Withdrawal fees in exact token amounts (not USD)
    WITHDRAWAL_FEES = {
        "usdt_polygon": {"coin": "usdt", "amount": 1.0, "network": "polygon"},
        "sol_solana": {"coin": "sol", "amount": 0.005, "network": "solana"},
        "matic_polygon": {"coin": "matic", "amount": 0.1, "network": "polygon"},
    }

    def __init__(self, phantom_router, indodax_gateway: IndodaxGateway = None):
        self.phantom = phantom_router
        self.indodax = indodax_gateway
        self.defi_fetcher = DeFiMetricsFetcher()
        self.state = None

    def transition_to(self, new_state: str, details: str = ""):
        self.state = new_state
        logger.info(f"🔄 [BridgeRouter State] -> {new_state.upper()}: {details}")

    async def find_cheapest_transport_coin(self, target_network: str = "all") -> Dict[str, Any]:
        """
        Dynamically calculates the IDR equivalent of withdrawal fees to find the cheapest transport coin.
        """
        if not self.indodax:
            return {"coin": "usdt", "fee_idr": 16000, "fee_token": 1.0, "network": "polygon"}

        lowest_fee_idr = float('inf')
        best_route = None

        for key, details in self.WITHDRAWAL_FEES.items():
            if target_network != "all" and details["network"] != target_network:
                continue
            
            coin = details["coin"]
            token_amount = details["amount"]
            
            # Use USDT as a proxy if it's a stablecoin
            if coin == "usdt":
                price_idr = 16000 # Approximation, can be dynamic
            else:
                ticker = await self.indodax.get_ticker(f"{coin}_idr")
                price_idr = float(ticker.get("last", 16000)) if ticker else 16000
                
            fee_idr = token_amount * price_idr
            
            if fee_idr < lowest_fee_idr:
                lowest_fee_idr = fee_idr
                best_route = {
                    "coin": coin,
                    "fee_idr": fee_idr,
                    "fee_token": token_amount,
                    "network": details["network"],
                    "price_idr": price_idr
                }
                
        return best_route

    async def auto_bridge_to_phantom(self, amount_idr: float, destination_address: str, target_network: str = "all", target_apy: float = 0.0) -> bool:
        """
        Fully Automatic Bridge from Indodax -> Phantom with Fee Guard and Dynamic Routing.
        Buys the cheapest transport coin and sends it.
        """
        import os
        self.transition_to("planned", f"Bridging Rp {amount_idr:,.0f} to {destination_address} on {target_network}")

        if not self.indodax:
            logger.error("❌ IndodaxGateway not provided to BridgeRouter.")
            self.transition_to("failed", "IndodaxGateway not provided")
            return False

        # 1. Determine the cheapest transport coin
        best_route = await self.find_cheapest_transport_coin(target_network)
        if not best_route:
            logger.error("❌ Could not determine a valid transport route.")
            self.transition_to("failed", "Could not determine a valid transport route")
            return False
            
        coin = best_route["coin"]
        fee_idr = best_route["fee_idr"]
        price_idr = best_route["price_idr"]
        network = best_route["network"]
        
        logger.info(f"🔍 Dynamic Bridge Router selected: {coin.upper()} on {network}. Estimated Fee: Rp {fee_idr:,.0f}")

        # Hook the PhantomOpportunityScout into BridgeRouter to fetch dynamic DeFi yields
        if target_apy <= 0.0:
            try:
                if self.phantom and hasattr(self.phantom, "scout"):
                    best_defi = await self.phantom.scout.get_best_defi_opportunities()
                    target_apy = best_defi.get("highest_apy", 8.5)
                    logger.info(f"📊 Dynamic APY selected from Scout: {target_apy}% ({best_defi.get('highest_apy_protocol')})")
            except Exception as e:
                logger.warning(f"⚠️ Could not resolve dynamic APY from Scout: {e}")
                target_apy = 8.5

        # Fee Guard: Profitability check
        # Yield generated in 1 month = amount_idr * (target_apy / 100) / 12
        expected_monthly_yield_idr = amount_idr * (target_apy / 100) / 12
        
        self.transition_to("fee_checked", f"Fee: Rp {fee_idr:,.0f}, Expected Yield: Rp {expected_monthly_yield_idr:,.0f}")

        # Block if fee > expected profit
        if fee_idr > expected_monthly_yield_idr:
            logger.warning(
                f"🛡️ FEE GUARD BLOCKED TRANSFER: Bridging Rp {amount_idr:,.0f} is unprofitable. "
                f"Fee: Rp {fee_idr:,.0f}. Expected Monthly Yield: Rp {expected_monthly_yield_idr:,.0f} (at {target_apy}% APY)."
            )
            self.transition_to("blocked", f"Fee Rp {fee_idr:,.0f} exceeds expected profit Rp {expected_monthly_yield_idr:,.0f}")
            return False

        logger.info(f"🌉 FEE GUARD PASSED: Proceeding to bridge via {coin.upper()}.")
        
        # 2. Determine if real live trading is allowed
        # Enforce guarded mode unless KiConfig.ENABLE_REAL_BRIDGE and KiConfig.ENABLE_REAL_WITHDRAWAL are true.
        is_live = KiConfig.LIVE_TRADING_ENABLED and KiConfig.ENABLE_REAL_BRIDGE and KiConfig.ENABLE_REAL_WITHDRAWAL


        amount_coin = (amount_idr / price_idr) * 0.998 # Approximate amount after 0.2% trading fee
        
        if not is_live:
            self.transition_to("guarded_approved", "Running in guarded mode (real bridge or withdrawal is disabled)")
            logger.warning(f"🧪 GUARDED MODE: Skipping actual market buy and withdrawal for {coin.upper()}.")
            telegram_send(f"🧪 *GUARDED BRIDGE INITIATED*\nBot guarded buy and withdrawal of `{amount_coin:.4f} {coin.upper()}` to `{destination_address}` on {network}.\nFee Paid: ~Rp {fee_idr:,.0f}")
            self.transition_to("executed", f"Guarded bridge of {amount_coin:.4f} {coin.upper()}")
            return True

        # Real Live Mode execution
        try:
            # Place buy order
            logger.info(f"🛒 [LIVE] Executing Market Buy: {amount_coin:.4f} {coin.upper()} using Rp {amount_idr:,.0f}")
            trade_res = await self.indodax.trade(
                pair=f"{coin}_idr",
                type="buy",
                price=price_idr,
                amount_idr=amount_idr
            )
            if not trade_res or trade_res.get("success") != 1:
                err = trade_res.get("error", "Unknown error") if trade_res else "No response"
                logger.error(f"❌ Indodax Buy Order Failed: {err}")
                telegram_send(f"❌ *BRIDGE FAILURE*: Indodax Market Buy order for {coin.upper()} failed: `{err}`")
                self.transition_to("failed", f"Indodax Buy Order Failed: {err}")
                return False

            logger.info(f"✅ Indodax Buy Order placed successfully: {trade_res}")

            # 3. Request Withdrawal
            res = await self.indodax.withdraw_coin(
                currency=coin,
                withdraw_address=destination_address,
                withdraw_amount=amount_coin
            )

            if res.get("success") == 1:
                logger.info("✅ Indodax API accepted withdrawal request.")
                telegram_send(f"🚨 *DYNAMIC BRIDGE INITIATED*\nBot bought and withdrew `{amount_coin:.4f} {coin.upper()}` to `{destination_address}` on {network}.\nFee Paid: ~Rp {fee_idr:,.0f}\n\n⚠️ *ACTION REQUIRED*: Check your email to confirm the withdrawal link!")
                self.transition_to("executed", f"Successfully withdrew {amount_coin:.4f} {coin.upper()}")
                return True
            else:
                err_msg = res.get("error", "Unknown withdrawal error")
                logger.error(f"❌ Indodax Withdrawal Failed: {err_msg}")
                telegram_send(f"❌ *BRIDGE FAILURE*: Indodax withdrawal of {coin.upper()} failed: `{err_msg}`")
                self.transition_to("failed", f"Indodax Withdrawal Failed: {err_msg}")
                return False
        except Exception as e:
            logger.error(f"❌ Indodax bridge operations encountered an exception: {e}")
            telegram_send(f"❌ *BRIDGE EXCEPTION*: Bridge error: `{e}`")
            self.transition_to("failed", f"Exception: {e}")
            return False
