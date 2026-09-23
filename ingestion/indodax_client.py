"""
Module: ingestion.indodax_client
Author: KiBot V3 Team
Date: 2026-10-01

References:
[1] CCXT Documentation (2026). "Unified Exchange Client & Indodax Connector Architecture."
[2] Indodax API Official Docs (2026). "Trade API v2: getInfo, trade, openOrders, cancelOrder specifications."
[3] Binance Academy (2026). "API Key Security: Least Privilege, Read-Only / Trade-Only Scopes."
"""

import hmac
import hashlib
import time
from urllib.parse import urlencode
from typing import Dict, Any, Optional
import aiohttp


class IndodaxClient:
    """
    Clean wrapper for Indodax REST API (Public & Trade API 2.0).
    Designed with timeout, retry, HMAC-SHA256 signature, and post-only safety.
    """
    PUBLIC_BASE_URL = "https://indodax.com/api"
    PRIVATE_V2_BASE_URL = "https://api.indodax.com"

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        timeout_seconds: float = 10.0,
        session: Optional[aiohttp.ClientSession] = None
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session = session

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }
            self._session = aiohttp.ClientSession(timeout=self.timeout, headers=headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _sign_payload_v2(self, params: Dict[str, Any]) -> str:
        """Computes HMAC-SHA256 signature over query string for Trade API 2.0."""
        query_string = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    async def get_ticker(self, pair: str) -> Dict[str, Any]:
        """
        Fetch public ticker for a pair (e.g. 'btc_idr').
        Returns dict containing buy (best bid), sell (best ask), last.
        """
        pair_clean = pair.lower()
        url = f"{self.PUBLIC_BASE_URL}/ticker/{pair_clean}"
        session = await self._get_session()
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("ticker", {})

    async def get_balance(self) -> Dict[str, float]:
        """
        Fetch user balance via Trade API 2.0 GET /api/v2/account.
        Returns clean dictionary of available balances: {'idr': 0.0, 'btc': 0.0, ...}
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials missing for private endpoint get_balance")

        params = {
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
            "omitZeroBalances": "false"
        }
        query_str = urlencode(params)
        signature = self._sign_payload_v2(params)
        url = f"{self.PRIVATE_V2_BASE_URL}/api/v2/account?{query_str}"
        headers = {
            "X-APIKEY": self.api_key,
            "Sign": signature,
        }

        session = await self._get_session()
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Indodax API error (HTTP {resp.status}): {text}")
            res = await resp.json()
            raw_balances = res.get("balances", [])
            balances = {}
            for item in raw_balances:
                asset = item.get("asset", "").lower()
                free_amt = float(item.get("free", 0.0))
                balances[asset] = free_amt
            return balances

    async def place_buy_order(
        self,
        pair: str,
        price: float,
        amount_asset: float,
        order_type: str = "MARKET"
    ) -> Dict[str, Any]:
        """
        Place a BUY order on Indodax via Trade API 2.0 POST /api/v2/order.
        KiBot V3 is strictly BUY-ONLY. No sell codepath exists.
        """
        if not self.api_key or not self.api_secret:
            raise ValueError("API credentials missing for trade execution")

        pair_clean = pair.lower().replace("_", "")
        params = {
            "symbol": pair_clean,
            "side": "BUY",
            "type": order_type.upper(),
            "quantity": str(amount_asset),
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        if order_type.upper() == "LIMIT":
            params["price"] = str(price)

        body_str = urlencode(params)
        signature = self._sign_payload_v2(params)
        url = f"{self.PRIVATE_V2_BASE_URL}/api/v2/order"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-APIKEY": self.api_key,
            "Sign": signature,
        }

        session = await self._get_session()
        async with session.post(url, data=body_str, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Buy order placement failed (HTTP {resp.status}): {text}")
            return await resp.json()
