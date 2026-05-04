#!/usr/bin/env python3
import time
import json
import socket
import os
import sys
import math
from datetime import datetime, timezone
from typing import Dict, List
from collections import deque

# Add paths for stats
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Support"))
from ki_stats import calculate_ema, calculate_rsi, calculate_z_score

# CONFIGURATION
# Batam sekarang mendengar di port 9999 untuk data mentah dari Scanner
BIND_IP = "0.0.0.0"
BIND_PORT = 9999 
# Output sinyal internal ke Manager
MANAGER_UDP_IP = "127.0.0.1"
MANAGER_UDP_PORT = 9998

MAX_HISTORY_LEN = 200 # Lebih panjang untuk akurasi indikator
_price_history: Dict[str, deque] = {}

def calculate_advanced_score(symbol: str, raw_data: dict) -> float:
    """
    The 'Brain' logic: Processes raw sensory data into a conviction score.
    """
    last_price = float(raw_data.get('price_usdt', 0) or raw_data.get('price', 0))
    if last_price == 0: return 0.0

    # 1. Update Persistent History
    if symbol not in _price_history:
        _price_history[symbol] = deque(maxlen=MAX_HISTORY_LEN)
    
    history_deque = _price_history[symbol]
    history_deque.append(last_price)
    history = list(history_deque)

    if len(history) < 20: return 0.0 # Warm-up period

    # 2. Multi-Factor Analysis
    ema20 = calculate_ema(history, 20)
    rsi = calculate_rsi(history, 14)
    z_score_val = calculate_z_score(history, 20)
    
    # Trend (40%) + Momentum (30%) + Volatility (30%)
    trend_score = 1.0 if last_price > ema20 else 0.0
    rsi_score = 1.0 if 45 <= rsi <= 75 else (0.5 if rsi > 75 else 0.0)
    vol_score = 1.0 if 1.0 <= z_score_val <= 3.0 else 0.2
    
    raw_score = (trend_score * 0.4) + (rsi_score * 0.3) + (vol_score * 0.3)
    
    # Sigmoid smoothing for non-linear decision making
    conviction = 1 / (1 + math.exp(-15 * (raw_score - 0.6)))
    return round(conviction, 4)

def send_to_manager(pair, conviction, price):
    payload = {
        "kind": "batam_intelligence",
        "pair": pair,
        "conviction": conviction,
        "price": price,
        "timestamp": int(time.time()),
        "source": "batam_brain_v9"
    }
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(json.dumps(payload).encode(), (MANAGER_UDP_IP, MANAGER_UDP_PORT))
    except Exception as e:
        print(f"Error reporting to manager: {e}")

def main():
    print(f"🧠 BATAM BRAIN v9.0: Waiting for Sensory Data on {BIND_IP}:{BIND_PORT}")
    
    # UDP Socket for receiving Scanner data
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((BIND_IP, BIND_PORT))
    
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            msg = json.loads(data.decode())
            
            # Hanya proses data dari Scanner (SENSORY_DATA_STREAM)
            if msg.get("type") == "SENSORY_DATA_STREAM":
                symbol = msg.get("pair_indodax")
                if not symbol: continue
                
                conviction = calculate_advanced_score(symbol, msg)
                
                if conviction >= 0.85:
                    send_to_manager(symbol, conviction, msg.get("price_usdt", 0))
                    print(f"🔥 OPPORTUNITY DETECTED: {symbol} | Conviction: {conviction}")
                    
        except Exception as e:
            print(f"Brain Loop Error: {e}")
            time.sleep(0.1)

if __name__ == "__main__":
    main()
