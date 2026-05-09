#!/usr/bin/env python3
import os
import sys
import time
import hashlib
import hmac
import json
import urllib.parse
from pathlib import Path
import httpx
import logging

# Setup Pathing
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(ROOT_DIR))

try:
    from SERVER_BATAM.Support.ki_vault import load_sovereign_env
    load_sovereign_env()
except ImportError:
    print("⚠️ Vault not found, using raw environment variables.")

logger = logging.getLogger("IndodaxGateway")

class IndodaxGateway:
    """
    Sovereign Indodax API Gateway.
    Handles authentication, signing, and execution of private/public requests.
    """
    def __init__(self, api_key=None, api_secret=None):
        self.api_key = api_key or os.environ.get("INDODAX_API_KEY")
        self.api_secret = api_secret or os.environ.get("INDODAX_API_SECRET")
        self.base_url = "https://indodax.com/tapi"
        self.public_url = "https://indodax.com/api"
        
        if not self.api_key or not self.api_secret:
            logger.error("❌ CRITICAL: Indodax API Credentials missing from environment!")

    def _generate_signature(self, payload_dict):
        """Generates HMAC-SHA512 signature for Indodax TAPI."""
        payload_str = urllib.parse.urlencode(payload_dict)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload_str.encode("utf-8"),
            hashlib.sha512
        ).hexdigest()
        return payload_str, signature

    async def _post_private(self, method, params=None):
        """Standard POST wrapper for private TAPI methods."""
        if not self.api_key:
            return {"success": 0, "error": "Missing API Key"}

        payload = {
            "method": method,
            "nonce": int(time.time() * 1000)
        }
        if params:
            payload.update(params)

        payload_str, signature = self._generate_signature(payload)
        
        headers = {
            "Key": self.api_key,
            "Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded"
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(self.base_url, content=payload_str, headers=headers)
                data = resp.json()
                if data.get("success") != 1:
                    logger.warning(f"⚠️ Indodax {method} Error: {data.get('error')}")
                return data
            except Exception as e:
                logger.error(f"❌ Indodax Connection Error ({method}): {e}")
                return {"success": 0, "error": str(e)}

    async def get_info(self):
        """Fetches account information and balances."""
        return await self._post_private("getInfo")

    async def get_balance(self, coin="idr"):
        """Convenience method to get specific coin balance."""
        res = await self.get_info()
        if res.get("success") == 1:
            balances = res.get("return", {}).get("balance", {})
            return float(balances.get(coin.lower(), 0.0))
        return 0.0

    async def trade(self, pair, type, price, amount_coin=None, amount_idr=None):
        """
        Executes a trade.
        @param pair: e.g. 'btc_idr'
        @param type: 'buy' or 'sell'
        @param price: execution price
        @param amount_coin: amount in base asset (for sell/buy)
        @param amount_idr: amount in IDR (alternative for buy)
        """
        params = {
            "pair": pair.lower(),
            "type": type.lower(),
            "price": int(price)
        }
        
        if amount_coin:
            params[pair.split('_')[0]] = amount_coin
        elif amount_idr and type.lower() == 'buy':
            params['idr'] = int(amount_idr)
        else:
            return {"success": 0, "error": "Missing amount parameters"}

        return await self._post_private("trade", params)

    async def get_open_orders(self, pair=None):
        """Fetches open orders."""
        params = {}
        if pair: params["pair"] = pair.lower()
        return await self._post_private("openOrders", params)

    async def cancel_order(self, pair, order_id, type):
        """Cancels an order."""
        params = {
            "pair": pair.lower(),
            "order_id": order_id,
            "type": type.lower()
        }
        return await self._post_private("cancelOrder", params)

    async def get_ticker(self, pair):
        """Public API: Get ticker info."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/{pair.lower()}/ticker")
                return resp.json().get("ticker", {})
            except:
                return {}

if __name__ == "__main__":
    # Quick test
    async def run_test():
        gw = IndodaxGateway()
        print("🔍 Testing Indodax Connectivity...")
        info = await gw.get_info()
        if info.get("success") == 1:
            print(f"✅ Success! Balances: {info['return']['balance']}")
        else:
            print(f"❌ Failed: {info.get('error')}")

    import asyncio
    asyncio.run(run_test())
