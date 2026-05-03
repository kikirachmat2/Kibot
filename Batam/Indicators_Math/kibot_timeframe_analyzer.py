"""
KiBot Trinity - Sovereign Multi-Timeframe (SMTF) Analyzer
========================================================
Advanced trend confirmation using Trend-Volume-Momentum (TVM) consensus.
Aligns with "Maximize Probability, Minimize Loss" philosophy.
"""

import time
import requests
import json
import math
from typing import List, Dict, Any, Optional

class TimeframeScore:
    def __init__(self, t1m: str, t15m: str, t60m: str, metadata: Dict[str, Any]):
        self.t1m = t1m    # UP, DOWN, SIDEWAYS
        self.t15m = t15m
        self.t60m = t60m
        self.metadata = metadata

    def entry_quality(self) -> str:
        """
        A: Elite (Full Alignment)
        A-: Strong (1m+15m Up, 60m Neutral)
        B: Speculative (1m Up, 15m Neutral)
        C: Neutral/Noisy
        D: High Risk (Counter-trend or Overbought)
        """
        # Veto: If macro is down, entry is D (Danger)
        if self.t15m == "DOWN" or self.t60m == "DOWN":
            return "D"
        
        # Veto: Overbought Protection
        if self.metadata.get("t1m_rsi", 0) > 85:
            return "D"

        if self.t1m == "UP" and self.t15m == "UP" and self.t60m == "UP":
            return "A"
        elif self.t1m == "UP" and self.t15m == "UP":
            return "A-"
        elif self.t1m == "UP":
            return "B"
        else:
            return "C"

def _calculate_ema(prices: List[float], period: int) -> float:
    if not prices or len(prices) < period:
        return prices[-1] if prices else 0.0
    alpha = 2 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = (p * alpha) + (ema * (1 - alpha))
    return ema

def _calculate_rsi(prices: List[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    if avg_loss == 0:
        return 100.0
        
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
        
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def analyze_timeframes(pair_id: str) -> TimeframeScore:
    """
    Sovereign Multi-Timeframe Analysis via Indodax UDF.
    Uses TVM (Trend-Volume-Momentum) consensus.
    """
    symbol = pair_id.upper().replace("_", "")
    now = int(time.time())
    
    results = {}
    meta = {}
    
    def analyze_single_timeframe(res: str) -> str:
        try:
            # Fetch 50 candles for indicators
            count = 50
            from_ts = now - (int(res) * 60 * count)
            url = f"https://indodax.com/tradingview/history?symbol={symbol}&resolution={res}&from={from_ts}&to={now}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("s") == "ok":
                    closes = [float(x) for x in data.get("c", [])]
                    vols = [float(x) for x in data.get("v", [])]
                    
                    if len(closes) < 20:
                        return "SIDEWAYS"
                    
                    price = closes[-1]
                    ema20 = _calculate_ema(closes, 20)
                    rsi = _calculate_rsi(closes, 14)
                    
                    # Store metadata for 1m
                    if res == "1":
                        meta["t1m_rsi"] = rsi
                        meta["t1m_ema20"] = ema20

                    # TVM Consensus Logic
                    is_trending = price > ema20
                    is_oversold = rsi < 30
                    is_overbought = rsi > 80
                    
                    # Volume check (last 3 avg vs prev 20 avg)
                    if len(vols) >= 23:
                        recent_vol = sum(vols[-3:]) / 3
                        prev_vol = sum(vols[-23:-3]) / 20
                        vol_surge = recent_vol > prev_vol * 1.5
                    else:
                        vol_surge = False

                    if is_trending and not is_overbought:
                        return "UP"
                    elif price < ema20 and not is_oversold:
                        return "DOWN"
                        
        except Exception:
            pass
        return "SIDEWAYS"
    
    t1 = analyze_single_timeframe("1")
    t15 = analyze_single_timeframe("15")
    t60 = analyze_single_timeframe("60")
    
    return TimeframeScore(t1, t15, t60, meta)
