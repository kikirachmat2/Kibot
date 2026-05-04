#!/usr/bin/env python3
import time
import json
import socket
import requests
import math
import os
import sys
from datetime import datetime
from typing import Dict, List

# Add current dir to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Support"))
from ki_stats import calculate_ema, calculate_rsi, calculate_z_score
import dynamic_config

# CONFIGURATION
INDODAX_TICKER_API = "https://indodax.com/api/tickers"
MANAGER_UDP_IP = os.getenv("KIBOT_MANAGER_UDP_HOST", "127.0.0.1")
MANAGER_UDP_PORT = int(
    os.getenv("KIBOT_MANAGER_UDP_TARGET_PORT")
    or os.getenv("KIBOT_MANAGER_UDP_BIND_PORT")
    or os.getenv("KIBOT_MANAGER_PORT")
    or "9998"
)
SCAN_INTERVAL = int(os.getenv("KIBOT_LOCAL_SIGNAL_SCAN_INTERVAL_SEC", "30"))
CONVICTION_THRESHOLD = float(os.getenv("KIBOT_LOCAL_SIGNAL_CONVICTION_THRESHOLD", "0.85"))
SIGNAL_SOURCE = os.getenv("KIBOT_LOCAL_SIGNAL_SOURCE", "kibot_local_signal")
TICKER_CACHE_TTL_SEC = int(os.getenv("KIBOT_LOCAL_SIGNAL_TICKER_CACHE_TTL_SEC", "300"))
TICKER_COOLDOWN_SEC = int(os.getenv("KIBOT_LOCAL_SIGNAL_TICKER_COOLDOWN_SEC", "900"))
MAX_HISTORY_LEN = 100

_ticker_cache = {}
_ticker_cache_at = 0.0
_ticker_cooldown_until = 0.0
_price_history: Dict[str, List[float]] = {}

def get_tickers():
    global _ticker_cache, _ticker_cache_at, _ticker_cooldown_until
    now = time.time()
    if _ticker_cache and (now - _ticker_cache_at) < TICKER_CACHE_TTL_SEC:
        return dict(_ticker_cache)
    if now < _ticker_cooldown_until and _ticker_cache:
        return dict(_ticker_cache)
    try:
        response = requests.get(INDODAX_TICKER_API, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if response.status_code >= 300:
            if response.status_code == 429:
                _ticker_cooldown_until = now + TICKER_COOLDOWN_SEC
            return dict(_ticker_cache)
        payload = response.json()
        tickers = payload.get('tickers', {}) if isinstance(payload, dict) else {}
        if isinstance(tickers, dict) and tickers:
            _ticker_cache = dict(tickers)
            _ticker_cache_at = now
            _ticker_cooldown_until = 0.0
            return dict(_ticker_cache)
        return dict(_ticker_cache)
    except Exception as e:
        _ticker_cooldown_until = now + TICKER_COOLDOWN_SEC
        if _ticker_cache:
            return dict(_ticker_cache)
        print(f"[{datetime.now()}] Error fetching tickers: {e}")
        return {}

def calculate_conviction(symbol, ticker):
    """
    Enhanced ConvictionScore with Technical Indicators.
    """
    last = float(ticker.get('last', 0))
    vol_idr = float(ticker.get('vol_idr', 0))
    
    if last == 0 or vol_idr < 50_000_000: 
        return 0.0

    # Update history
    history = _price_history.get(symbol, [])
    history.append(last)
    if len(history) > MAX_HISTORY_LEN: history.pop(0)
    _price_history[symbol] = history

    if len(history) < 20: # Need minimum data for indicators
        return 0.0

    # 1. Trend Factor (Price vs EMA20)
    ema20 = calculate_ema(history, 20)
    trend_score = 1.0 if last > ema20 else 0.0
    
    # 2. Momentum (RSI)
    rsi = calculate_rsi(history, 14)
    # RSI between 40 and 70 is ideal for bullish continuation
    if 40 <= rsi <= 70:
        rsi_score = 1.0
    elif rsi > 70:
        rsi_score = 0.5 # Overbought, risky
    else:
        rsi_score = 0.0 # Oversold or weak

    # 3. Volatility (Z-Score)
    z = calculate_z_score(history, 20)
    z_limit = dynamic_config.get_param("KIBOT_Z_SCORE_THRESHOLD", 2.2)
    # We want a positive Z-score but not a massive blowout
    z_score = 1.0 if 0.5 <= z <= z_limit else 0.2

    # 4. Volume Intensity
    vol_score = min(vol_idr / 1_000_000_000, 1.0) 

    # Final Weighted Score
    # Trend (30%) + RSI (25%) + Z-Score (25%) + Volume (20%)
    raw_score = (trend_score * 0.3) + (rsi_score * 0.25) + (z_score * 0.25) + (vol_score * 0.2)
    
    # Sigmoid smoothing
    conviction = 1 / (1 + math.exp(-12 * (raw_score - 0.55))) 
    
    return round(conviction, 4)

def send_signal(pair, conviction, price):
    payload = {
        "kind": "local_signal",
        "pair": pair,
        "pairId": pair,
        "symbol": pair,
        "conviction": conviction,
        "score": round(conviction * 100.0, 2),
        "price": price,
        "timestamp": int(time.time()),
        "source": SIGNAL_SOURCE
    }
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(json.dumps(payload).encode(), (MANAGER_UDP_IP, MANAGER_UDP_PORT))
    except Exception as e:
        print(f"[{datetime.now()}] UDP Send failed: {e}")

def main():
    print(f"[{datetime.now()}] KiBot Sovereign Signal Engine Started target={MANAGER_UDP_IP}:{MANAGER_UDP_PORT}")
    
    while True:
        tickers = get_tickers()
        btc_data = tickers.get('btc_idr')
        btc_trend_ok = True
        
        # Trend Filter: If BTC is dumping, we pause all signals
        if btc_data:
            btc_last = float(btc_data.get('last', 0))
            btc_hist = _price_history.get('btc_idr', [])
            if len(btc_hist) >= 10:
                btc_ema = calculate_ema(btc_hist, 10)
                if btc_last < btc_ema * 0.995: # BTC down more than 0.5% below EMA
                    btc_trend_ok = False

        if btc_trend_ok:
            # Dynamic threshold
            min_conviction = dynamic_config.get_param("KIBOT_LOCAL_SIGNAL_CONVICTION_THRESHOLD", CONVICTION_THRESHOLD)
            
            for symbol, data in tickers.items():
                if not symbol.endswith('_idr'): continue
                
                conviction = calculate_conviction(symbol, data)
                
                if conviction >= min_conviction:
                    send_signal(symbol, conviction, float(data.get("last", 0) or 0))
                    print(f"[{datetime.now()}] HIGH CONVICTION SIGNAL: {symbol} @ {conviction} (threshold={min_conviction})")
        else:
            print(f"[{datetime.now()}] BTC Trend Warning - Signal Generation Paused")
                
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
