#!/usr/bin/env python3
import time
import json
import socket
import os
import sys
import math
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Dict, List
from collections import deque

# Add paths for stats and security
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Support"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Security"))
from ki_stats import calculate_ema, calculate_rsi, calculate_z_score
import kibot_security

# CONFIGURATION
BIND_IP = "0.0.0.0"
BIND_PORT = 9999 
MANAGER_UDP_IP = "127.0.0.1"
MANAGER_UDP_PORT = 9998

# SECURITY WHITELIST (IP Scanner Kamu)
# Kita ambil dari config atau hardcode yang sudah kita tahu
ALLOWED_SCANNER_IPS = ["152.69.218.198"] # Server Scanner

MAX_HISTORY_LEN = 200 
_price_history: Dict[str, deque] = {}

def verify_packet(data: bytes, addr: tuple) -> bool:
    """
    The Guardian: Validates if the packet is from a trusted source and untampered.
    """
    # 1. IP Whitelisting
    if addr[0] not in ALLOWED_SCANNER_IPS and addr[0] != "127.0.0.1":
        kibot_security.append_secure_log("NETWORK_INTRUSION", f"Rejected packet from unauthorized IP: {addr[0]}", "CRITICAL")
        return False
        
    # 2. Structure Validation
    try:
        msg = json.loads(data.decode())
        if "type" not in msg or "signature" not in msg:
            return False
            
        # 3. HMAC Signature Validation (Future implementation with Scanners)
        # Untuk sekarang kita fokus pada IP Whitelist agar tidak memutus koneksi
        return True
    except:
        return False

def calculate_advanced_score(symbol: str, raw_data: dict) -> float:
    last_price = float(raw_data.get('price_usdt', 0) or raw_data.get('price', 0))
    if last_price == 0: return 0.0

    if symbol not in _price_history:
        _price_history[symbol] = deque(maxlen=MAX_HISTORY_LEN)
    
    history_deque = _price_history[symbol]
    history_deque.append(last_price)
    history = list(history_deque)

    if len(history) < 20: return 0.0 

    ema20 = calculate_ema(history, 20)
    rsi = calculate_rsi(history, 14)
    z_score_val = calculate_z_score(history, 20)
    
    trend_score = 1.0 if last_price > ema20 else 0.0
    rsi_score = 1.0 if 45 <= rsi <= 75 else (0.5 if rsi > 75 else 0.0)
    vol_score = 1.0 if 1.0 <= z_score_val <= 3.0 else 0.2
    
    raw_score = (trend_score * 0.4) + (rsi_score * 0.3) + (vol_score * 0.3)
    conviction = 1 / (1 + math.exp(-15 * (raw_score - 0.6)))
    return round(conviction, 4)

def send_to_manager(pair, conviction, price):
    payload = {
        "kind": "batam_intelligence",
        "pair": pair,
        "conviction": conviction,
        "price": price,
        "timestamp": int(time.time()),
        "source": "batam_brain_v9_secure"
    }
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(json.dumps(payload).encode(), (MANAGER_UDP_IP, MANAGER_UDP_PORT))
    except Exception as e:
        print(f"Error reporting to manager: {e}")

def main():
    print(f"🧠 BATAM SECURE BRAIN v9.1: Guarding {BIND_IP}:{BIND_PORT}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((BIND_IP, BIND_PORT))
    
    while True:
        try:
            data, addr = sock.recvfrom(65535)
            
            # Security Check
            if not verify_packet(data, addr):
                continue
                
            msg = json.loads(data.decode())
            if msg.get("type") == "SENSORY_DATA_STREAM":
                symbol = msg.get("pair_indodax")
                if not symbol: continue
                
                conviction = calculate_advanced_score(symbol, msg)
                
                if conviction >= 0.85:
                    send_to_manager(symbol, conviction, msg.get("price_usdt", 0))
                    print(f"🔥 SECURE OPPORTUNITY: {symbol} | Conviction: {conviction}")
                    
        except Exception as e:
            print(f"Brain Loop Error: {e}")
            time.sleep(0.1)

if __name__ == "__main__":
    main()
