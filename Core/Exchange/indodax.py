#!/usr/bin/env python3
import os
import sys
import time
import hashlib
import hmac
import json
import re
import urllib.parse
from pathlib import Path
import httpx
import logging
import threading
from typing import Any, Dict

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
    _pairs_cache: Dict[str, Dict[str, Any]] | None = None
    _pairs_cache_time = 0.0
    _pairs_cache_ttl = 3600

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

    def _bump_nonce_floor(self, floor: int) -> None:
        """Force the persisted nonce floor above the exchange-reported value."""
        if floor <= 0:
            return
        import fcntl

        self._nonce_file.parent.mkdir(parents=True, exist_ok=True)
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

                nonce = max(last_nonce, floor)
                fp.seek(0)
                fp.truncate()
                fp.write(json.dumps({"last_nonce": nonce}))
                fp.flush()
                os.fsync(fp.fileno())
                fcntl.flock(fp, fcntl.LOCK_UN)

    async def _post_private(self, method, params=None, *, _nonce_retry: bool = False):
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
                    error_text = str(data.get("error", ""))
                    nonce_match = re.search(
                        r"Nonce must be greater than\s+(\d+)\.?\s*You provided\s+(\d+)",
                        error_text,
                        re.IGNORECASE,
                    )
                    if nonce_match:
                        required_nonce = int(nonce_match.group(1))
                        provided_nonce = int(nonce_match.group(2))
                        self._bump_nonce_floor(max(required_nonce + 1, provided_nonce + 1, int(time.time_ns() // 1000)))
                        if not _nonce_retry:
                            logger.info(
                                f"🔁 Indodax {method} nonce bumped after exchange hint; retrying once."
                            )
                            return await self._post_private(method, params=params, _nonce_retry=True)
                    logger.warning(f"⚠️ Indodax {method} Error: {error_text}")
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
        price_value = float(price)
        normalized_price = (
            int(price_value)
            if "_idr" in pair and price_value >= 1 and price_value.is_integer()
            else self.round_step(price_value, "0.00000001")
        )
        params = {
            "pair": pair,
            "type": type.lower(),
            "price": normalized_price
        }
        
        if amount_coin is not None and amount_coin > 0:
            coin_symbol = pair.split('_')[0]
            params[coin_symbol] = self.round_step(amount_coin, "0.00000001")
        elif amount_idr and type.lower() == 'buy':
            params['idr'] = int(amount_idr)
        
        IndodaxGateway._info_cache = None
        return await self._post_private("trade", params)

    async def withdraw_coin(self, currency: str, withdraw_address: str, withdraw_amount: float, withdraw_memo: str = "") -> Dict[str, Any]:
        """
        Request a crypto withdrawal to an external wallet.
        IMPORTANT: This usually triggers an email confirmation unless Callback URL is active!
        """
        params = {
            "currency": currency.lower(),
            "withdraw_address": withdraw_address,
            "withdraw_amount": self.round_step(withdraw_amount, "0.00000001"),
            "request_id": f"kibot_wd_{int(time.time())}"
        }
        if withdraw_memo:
            params["withdraw_memo"] = withdraw_memo
            
        logger.warning(f"💸 Initiating Withdrawal: {withdraw_amount} {currency} to {withdraw_address}")
        IndodaxGateway._info_cache = None
        return await self._post_private("withdrawCoin", params)

    async def get_ticker(self, pair):
        pair = self._normalize_pair(pair)
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/ticker/{pair}", timeout=8.0)
                return resp.json().get("ticker", {})
            except Exception as e:
                logger.debug(f"Ticker fetch failed for {pair}: {e}")
                return {}

    async def get_orderbook(self, pair):
        """Fetch orderbook depth for slippage protection."""
        pair = self._normalize_pair(pair)
        depth_pair = pair.replace("_", "")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/depth/{depth_pair}", timeout=8.0)
                data = resp.json()
                buys = data.get("buy", []) or data.get("bids", [])
                sells = data.get("sell", []) or data.get("asks", [])
                return {
                    "buy": buys,
                    "sell": sells,
                    "bids": buys,
                    "asks": sells,
                }
            except Exception as e:
                logger.error(f"❌ Orderbook Fetch Error: {e}")
                return {"bids": [], "asks": []}

    async def get_pair_info(self, pair: str) -> Dict[str, Any]:
        """Return Indodax pair metadata, including minimum base/coin trade sizes."""
        pair = self._normalize_pair(pair)
        now = time.time()
        if (
            IndodaxGateway._pairs_cache is not None
            and now - IndodaxGateway._pairs_cache_time < IndodaxGateway._pairs_cache_ttl
        ):
            return IndodaxGateway._pairs_cache.get(pair, {})

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(f"{self.public_url}/pairs", timeout=10.0)
                rows = resp.json()
                cache: Dict[str, Dict[str, Any]] = {}
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        ticker_id = str(row.get("ticker_id") or "").lower()
                        if ticker_id:
                            cache[ticker_id] = row
                IndodaxGateway._pairs_cache = cache
                IndodaxGateway._pairs_cache_time = now
                return cache.get(pair, {})
            except Exception as e:
                logger.debug(f"Pair metadata fetch failed: {e}")
                return {}

    async def get_open_orders(self, pair: str | None = None) -> Dict[str, Any]:
        params = {}
        if pair:
            params["pair"] = self._normalize_pair(pair)
        return await self._post_private("openOrders", params)
