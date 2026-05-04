#!/usr/bin/env python3
import time
import json
import socket
import requests
import math
import os
from datetime import datetime

# CONFIGURATION
INDODAX_TICKER_API = "https://indodax.com/api/tickers"
MANAGER_UDP_IP = os.getenv("KIBOT_MANAGER_HOST", os.getenv("KIBOT_MANAGER_UDP_HOST", "168.110.201.228"))
MANAGER_UDP_PORT = int(
    os.getenv("KIBOT_MANAGER_UDP_TARGET_PORT")
    or os.getenv("KIBOT_MANAGER_UDP_BIND_PORT")
    or os.getenv("KIBOT_MANAGER_PORT")
    or "9998"
)
SCAN_INTERVAL = int(os.getenv("KIBOT_LOCAL_SIGNAL_SCAN_INTERVAL_SEC", "30"))
CONVICTION_THRESHOLD = float(os.getenv("KIBOT_LOCAL_SIGNAL_CONVICTION_THRESHOLD", "0.85"))
SIGNAL_SOURCE = os.getenv("KIBOT_LOCAL_SIGNAL_SOURCE", "kibot_local_signal")

def get_tickers():
    try:
        response = requests.get(INDODAX_TICKER_API, timeout=10)
        return response.json().get('tickers', {})
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching tickers: {e}")
        return {}

def calculate_conviction(symbol, ticker, history):
    """
    Gaussian-based ConvictionScore calculation.
    Factors: 24h Volatility, 1h Momentum, Volume Spike, and Spread.
    """
    last = float(ticker.get('last', 0))
    high = float(ticker.get('high', 0))
    low = float(ticker.get('low', 0))
    vol_idr = float(ticker.get('vol_idr', 0))
    
    if last == 0 or vol_idr < 50_000_000: # Min 50jt volume for local bucket
        return 0.0

    # 1. Momentum (Distance from 24h Low)
    range_24h = high - low
    if range_24h == 0: return 0.0
    dist_from_low = (last - low) / range_24h
    
    # 2. Volume Spike (Relative to history if available)
    # Simplified for v7.0: purely based on 24h intensity
    vol_score = min(vol_idr / 500_000_000, 1.0) 

    # 3. Spread Factor
    buy = float(ticker.get('buy', 0))
    sell = float(ticker.get('sell', 0))
    spread = (sell - buy) / last if last > 0 else 1.0
    spread_score = max(0, 1.0 - (spread / 0.02)) # Penalty if spread > 2%

    # Final Gaussian-like smoothing
    raw_score = (dist_from_low * 0.4) + (vol_score * 0.4) + (spread_score * 0.2)
    conviction = 1 / (1 + math.exp(-10 * (raw_score - 0.5))) # Sigmoid centered at 0.5
    
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
        print(f"[{datetime.now()}] SIGNAL SENT: {pair} -> {MANAGER_UDP_IP}:{MANAGER_UDP_PORT} (Conviction: {conviction})")
    except Exception as e:
        print(f"[{datetime.now()}] UDP Send failed: {e}")

def main():
    print(f"[{datetime.now()}] KiBot Local Signal Engine v7.0 Started target={MANAGER_UDP_IP}:{MANAGER_UDP_PORT}")
    history = {}
    
    while True:
        tickers = get_tickers()
        for symbol, data in tickers.items():
            if not symbol.endswith('_idr'): continue
            
            conviction = calculate_conviction(symbol, data, history)
            
            if conviction >= CONVICTION_THRESHOLD:
                send_signal(symbol, conviction, float(data.get("last", 0) or 0))
                
        # Simple history tracking for next cycle volume delta
        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
