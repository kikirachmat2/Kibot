"""
Binance Lead-Lag Tracker for KiBot V2.
Tracks rolling prices and calculates micro/macro momentum from Binance miniTicker stream.
Provides cross-market lead-lag confirmation to prevent buying Indodax during global liquidation dumps.

Data Integrity (D-08 Fix B):
  Cold-start and stale-data conditions are FAIL-CLOSED (i.e., treated as unsafe for entry):
  - get_momentum() returns UNKNOWN sentinel dict when no data received yet.
  - is_data_fresh() returns False when newest tick is > 120s old.
  - is_dumping() / is_flash_crash() return (True, 'BINANCE_DATA_UNKNOWN') for stale data.
  Callers MUST check for the UNKNOWN sentinel and block entry accordingly.
"""
from __future__ import annotations

import time
from typing import Dict, Any, List, Tuple, Optional
from collections import deque

# Sentinel value used in momentum dict to signal no Binance data available.
# Callers must check mom.get('status') == 'UNKNOWN' and treat it as FAIL-CLOSED.
UNKNOWN_MOMENTUM: Dict[str, Any] = {
    "status": "UNKNOWN",
    "return_5m": None,
    "return_1h": None,
    "return_24h": None,
    "data_points": 0,
}


class BinanceLeadLagTracker:
    """
    In-memory lightweight price history tracker for Binance mini-tickers.
    Stores rolling (timestamp, price) tuples up to 3600 seconds (1 hour) per symbol.
    Provides sub-microsecond momentum queries without database overhead.
    """

    PAIR_MAPPING = {
        "BTC/IDR": "BTCUSDT",
        "BTCIDR": "BTCUSDT",
        "ETH/IDR": "ETHUSDT",
        "ETHIDR": "ETHUSDT",
        "AVAX/IDR": "AVAXUSDT",
        "AVAXIDR": "AVAXUSDT",
        "SOL/IDR": "SOLUSDT",
        "SOLIDR": "SOLUSDT",
    }

    def __init__(self, max_history_s: float = 3600.0):
        self.max_history_s = max_history_s
        # symbol -> deque of (timestamp, price)
        self._history: Dict[str, deque[Tuple[float, float]]] = {}
        # symbol -> latest parsed 24h open
        self._latest_open_24h: Dict[str, float] = {}

    def map_indodax_to_binance(self, indodax_symbol: str) -> str:
        clean = indodax_symbol.upper().strip()
        return self.PAIR_MAPPING.get(clean, f"{clean.replace('/', '').replace('IDR', '')}USDT")

    def update_ticker(self, ticker: Dict[str, Any]) -> None:
        """
        Ingests parsed mini-ticker from Binance WebSocket.
        Format expected: {'symbol': 'BTCUSDT', 'close': 65000.0, 'open': 64000.0, 'ts': 1789000000.0}
        """
        symbol = str(ticker.get("symbol", "")).upper().strip()
        price = float(ticker.get("close") or ticker.get("price") or 0.0)
        ts = float(ticker.get("ts") or time.time())
        open_24h = float(ticker.get("open") or 0.0)

        if not symbol or price <= 0:
            return

        if open_24h > 0:
            self._latest_open_24h[symbol] = open_24h

        if symbol not in self._history:
            self._history[symbol] = deque()

        q = self._history[symbol]
        q.append((ts, price))

        # Evict entries older than max_history_s
        cutoff = ts - self.max_history_s
        while q and q[0][0] < cutoff:
            q.popleft()

    def get_momentum(self, symbol: str) -> Dict[str, float]:
        """
        Calculates 5-minute, 1-hour, and 24-hour return for a Binance symbol.
        Returns:
            {
                'return_5m': 0.005,   # +0.5%
                'return_1h': -0.012,  # -1.2%
                'return_24h': 0.025,  # +2.5%
                'data_points': 120,
            }
        """
        sym = symbol.upper().strip()
        q = self._history.get(sym)
        if not q:
            # Cold-started or symbol not received yet — FAIL-CLOSED (not safe to trade on)
            return dict(UNKNOWN_MOMENTUM)

        now_ts, latest_price = q[-1]

        # Check freshness: if newest tick is > 120 seconds old, treat as stale
        if time.time() - now_ts > 120.0:
            return dict(UNKNOWN_MOMENTUM)

        # Calculate 5m return (ref_ts = now - 300)
        cutoff_5m = now_ts - 300.0
        p_5m = latest_price
        for ts, p in q:
            if ts >= cutoff_5m:
                p_5m = p
                break
        ret_5m = (latest_price - p_5m) / p_5m if p_5m > 0 else 0.0

        # Calculate 1h return (oldest entry in 1h deque)
        oldest_ts, oldest_price = q[0]
        ret_1h = (latest_price - oldest_price) / oldest_price if oldest_price > 0 else 0.0

        # 24h return from 24h rolling open if available
        open_24h = self._latest_open_24h.get(sym, oldest_price)
        ret_24h = (latest_price - open_24h) / open_24h if open_24h > 0 else ret_1h

        return {
            "status": "OK",
            "return_5m": round(ret_5m, 4),
            "return_1h": round(ret_1h, 4),
            "return_24h": round(ret_24h, 4),
            "data_points": len(q),
        }

    def is_data_fresh(self, symbol: str, max_age_s: float = 120.0) -> bool:
        """
        Returns True only if we have received Binance data for this symbol
        within the last `max_age_s` seconds (default: 120s).
        Returns False (stale/cold) when no data or data is older than threshold.
        Callers should block entry when this returns False.
        """
        sym = symbol.upper().strip()
        q = self._history.get(sym)
        if not q:
            return False
        newest_ts = q[-1][0]
        return (time.time() - newest_ts) <= max_age_s

    def is_dumping(self, symbol: str, threshold_1h: float = -0.015, threshold_5m: float = -0.010) -> Tuple[bool, str]:
        """
        Evaluates whether Binance is undergoing a liquidation dump.
        Returns (True, reason) if threshold breached, else (False, 'STABLE').
        Returns (True, 'BINANCE_DATA_UNKNOWN') when data is stale or missing (FAIL-CLOSED).
        """
        mom = self.get_momentum(symbol)
        if mom.get("status") == "UNKNOWN":
            return True, f"BINANCE_DATA_UNKNOWN: no fresh data for {symbol} (fail-closed)"
        ret_1h = mom["return_1h"]
        ret_5m = mom["return_5m"]

        if ret_1h <= threshold_1h:
            return True, f"Binance {symbol} 1h dump: {ret_1h*100:.2f}% <= {threshold_1h*100:.1f}%"
        if ret_5m <= threshold_5m:
            return True, f"Binance {symbol} 5m flash-dump: {ret_5m*100:.2f}% <= {threshold_5m*100:.1f}%"

        return False, "STABLE"

    def is_flash_crash(self, symbol: str, threshold_5m: float = -0.020) -> Tuple[bool, float, str]:
        """
        Detects emergency cross-market liquidation flash crashes (default: <= -2.0% in 5m).
        Returns: (is_crash: bool, ret_5m: float, reason: str).
        Returns (True, 0.0, 'BINANCE_DATA_UNKNOWN') when data is stale or missing (FAIL-CLOSED).
        """
        binance_sym = self.map_indodax_to_binance(symbol) if not symbol.endswith("USDT") else symbol.upper().strip()
        mom = self.get_momentum(binance_sym)
        if mom.get("status") == "UNKNOWN":
            return True, 0.0, f"BINANCE_DATA_UNKNOWN: no fresh data for {binance_sym} (fail-closed)"
        ret_5m = mom["return_5m"]

        if ret_5m <= threshold_5m:
            return True, ret_5m, f"Binance {binance_sym} 5m flash crash: {ret_5m*100:.2f}% <= {threshold_5m*100:.1f}%"
        return False, ret_5m, "STABLE"

