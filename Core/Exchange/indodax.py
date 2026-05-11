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

# Resolve absolute root
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from Core.Support.ki_vault import load_sovereign_env
    load_sovereign_env()
except Exception as e:
    print(f"⚠️ Vault initialization failed: {e}")

logger = logging.getLogger("IndodaxGateway")

class IndodaxGateway:
    _info_cache = None
    _info_cache_time = 0
    _CACHE_TTL = 2  # 2 seconds cache for get_info

    def __init__(self, api_key=None, api_secret=None):
        self.api_key = (api_key or os.environ.get("INDODAX_API_KEY", "")).strip()
        self.api_secret = (api_secret or os.environ.get("INDODAX_API_SECRET", "")).strip()
        self.base_url = "https://indodax.com/tapi"
        self.public_url = "https://indodax.com/api"
        
        if not self.api_key or not self.api_secret:
            logger.error("❌ CRITICAL: Indodax API Credentials missing from environment!")

    def _generate_signature(self, payload_dict):
        payload_str = urllib.parse.urlencode(payload_dict)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload_str.encode("utf-8"),
            hashlib.sha512
        ).hexdigest()
        return payload_str, signature

    async def _post_private(self, method, params=None):
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
        now = time.time()
        if IndodaxGateway._info_cache and (now - IndodaxGateway._info_cache_time < IndodaxGateway._CACHE_TTL):
            return IndodaxGateway._info_cache
            
        res = await self._post_private("getInfo")
        if res.get("success") == 1:
            IndodaxGateway._info_cache = res
            IndodaxGateway._info_cache_time = now
        return res

    async def get_balance(self, coin="idr"):
        res = await self.get_info()
        if res.get("success") == 1:
            balances = res.get("return", {}).get("balance", {})
            return float(balances.get(coin.lower(), 0.0))
        return 0.0

    def round_step(self, amount, step_size):
        """Standard exchange precision rounding."""
        import decimal
        try:
            d = decimal.Decimal(str(amount))
            s = decimal.Decimal(str(step_size))
            return float(d.quantize(s, rounding=decimal.ROUND_DOWN))
        except:
            return amount

    async def trade(self, pair, type, price, amount_coin=None, amount_idr=None):
        params = {
            "pair": pair.lower(),
            "type": type.lower(),
            "price": int(price)
        }
        
        # Indodax precision handles: IDR usually int, Crypto usually 8 decimals
        if amount_coin:
            coin_symbol = pair.split('_')[0]
            # Use standard 8 decimal precision for crypto if not specified
            params[coin_symbol] = self.round_step(amount_coin, "0.00000001")
        elif amount_idr and type.lower() == 'buy':
            params['idr'] = int(amount_idr)
        
        # Clear cache after trade to ensure next check is fresh
        IndodaxGateway._info_cache = None
        return await self._post_private("trade", params)

    async def get_ticker(self, pair):
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/{pair.lower()}/ticker")
                return resp.json().get("ticker", {})
            except:
                return {}

    async def get_orderbook(self, pair):
        """Fetch orderbook depth for slippage protection."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/{pair.lower()}/depth")
                return resp.json()
            except Exception as e:
                logger.error(f"❌ Orderbook Fetch Error: {e}")
                return {"bids": [], "asks": []}
