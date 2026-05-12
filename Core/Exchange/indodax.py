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
import threading

from Core.Support.ki_config import STATE_DIR

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
    _nonce_lock = threading.Lock()
    _nonce_file = STATE_DIR / "indodax_nonce.json"

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

    def _next_nonce(self) -> int:
        """
        Generate a monotonic nonce that is safe across multiple KiBot processes.

        Indodax rejects duplicate or decreasing nonces, so we persist the last
        value to shared state and lock the update across processes.
        """
        import fcntl

        self._nonce_file.parent.mkdir(parents=True, exist_ok=True)
        # Use microseconds so a fresh process starts well above older
        # millisecond-based nonces even after a restart.
        candidate = int(time.time_ns() // 1000)

        with IndodaxGateway._nonce_lock:
            with open(self._nonce_file, "a+", encoding="utf-8") as fp:
                fcntl.flock(fp, fcntl.LOCK_EX)
                fp.seek(0)
                last_nonce = 0
                try:
                    payload = json.loads(fp.read() or "{}")
                    last_nonce = int(payload.get("last_nonce", 0))
                except Exception:
                    last_nonce = 0

                nonce = max(candidate, last_nonce + 1)
                fp.seek(0)
                fp.truncate()
                fp.write(json.dumps({"last_nonce": nonce}))
                fp.flush()
                os.fsync(fp.fileno())
                fcntl.flock(fp, fcntl.LOCK_UN)

        return nonce

    async def _post_private(self, method, params=None):
        if not self.api_key:
            return {"success": 0, "error": "Missing API Key"}

        payload = {
            "method": method,
            "nonce": self._next_nonce()
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

    def _normalize_pair(self, pair: str) -> str:
        """Normalizes symbol to indodax format (e.g. BTC/IDR -> btc_idr)."""
        return pair.lower().replace("/", "_")

    async def trade(self, pair, type, price, amount_coin=None, amount_idr=None):
        pair = self._normalize_pair(pair)
        params = {
            "pair": pair,
            "type": type.lower(),
            "price": int(price) if "_idr" in pair else self.round_step(price, "0.00000001")
        }
        
        if amount_coin is not None and amount_coin > 0:
            coin_symbol = pair.split('_')[0]
            params[coin_symbol] = self.round_step(amount_coin, "0.00000001")
        elif amount_idr and type.lower() == 'buy':
            params['idr'] = int(amount_idr)
        
        IndodaxGateway._info_cache = None
        return await self._post_private("trade", params)

    async def get_ticker(self, pair):
        pair = self._normalize_pair(pair)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/{pair}/ticker")
                return resp.json().get("ticker", {})
            except:
                return {}

    async def get_orderbook(self, pair):
        """Fetch orderbook depth for slippage protection."""
        pair = self._normalize_pair(pair)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/{pair}/depth")
                return resp.json()
            except Exception as e:
                logger.error(f"❌ Orderbook Fetch Error: {e}")
                return {"bids": [], "asks": []}
