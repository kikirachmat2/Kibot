"""
KiBot Trinity - Multi-Timeframe Analyzer
========================================
Menarik data historis candle 1m, 15m, 60m dari Indodax untuk konfirmasi trend.
"""

import time
import requests
import json
from datetime import datetime

class TimeframeScore:
    def __init__(self, t1m, t15m, t60m):
        self.t1m = t1m    # UP, DOWN, SIDEWAYS
        self.t15m = t15m
        self.t60m = t60m

    def entry_quality(self) -> str:
        """A: Strong trend, B: Early breakout, C: Uncertain, D: Downtrend"""
        if self.t1m == "UP" and self.t15m == "UP" and self.t60m == "UP":
            return "A"
        elif self.t1m == "UP" and self.t15m == "UP" and self.t60m == "SIDEWAYS":
            return "A-"
        elif self.t1m == "UP" and self.t15m == "SIDEWAYS":
            return "B"
        elif self.t15m == "DOWN" or self.t60m == "DOWN":
            return "D"
        else:
            return "C"

def analyze_timeframes(pair_id: str) -> TimeframeScore:
    """
    Analisa trend di timeframe 1m, 15m, 60m via TradingView/Indodax UDF API.
    Abaikan exception dan return default SIDEWAYS jika error.
    """
    symbol = pair_id.upper().replace("_", "")
    now = int(time.time())
    
    def fetch_candle_direction(res):
        try:
            # UDF API endpoint untuk chart history
            url = f"https://indodax.com/tradingview/history?symbol={symbol}&resolution={res}&from={now - (int(res) * 60 * 10)}&to={now}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("s") == "ok":
                    closes = data.get("c", [])
                    if len(closes) >= 3:
                        c_curr = closes[-1]
                        c_prev = closes[-3]
                        if c_curr > c_prev * 1.002:
                            return "UP"
                        elif c_curr < c_prev * 0.998:
                            return "DOWN"
        except Exception:
            pass
        return "SIDEWAYS"
    
    t1 = fetch_candle_direction("1")
    t15 = fetch_candle_direction("15")
    t60 = fetch_candle_direction("60")
    
    return TimeframeScore(t1, t15, t60)
