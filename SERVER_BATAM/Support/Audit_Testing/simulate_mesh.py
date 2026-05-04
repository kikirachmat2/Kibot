import socket
import json
import time
import hmac
import hashlib
import base64
import os

# --- CONFIG ---
MANAGER_HOST = "127.0.0.1"
MANAGER_PORT = 9999
SIGNAL_KEY = "SOVEREIGN_DEFAULT_SIGNAL_SECRET"

EXCHANGES = [
    "BINANCE", "BYBIT", "KUCOIN", "OKX", "BITHUMB", 
    "UPBIT", "MEXC", "GATE", "HUOBI", "KRAKEN",
    "COINBASE", "BITSTAMP", "BITFINEX", "GEMINI", "BITTREX",
    "POLONIEX", "DERIBIT", "DYDX", "PANNEX", "INDODAX_BACKUP"
]
# +1 for Listing Hunter
EXCHANGES.append("LISTING_HUNTER")

def send_signal(exchange, seq, pair="btc_idr", score=0.85):
    msg = {
        "type": "MULTI_SCANNER_SIGNAL",
        "exchange": exchange,
        "pair_indodax": pair,
        "detection_score": score,
        "sequence_num": seq,
        "sentAtEpochMs": int(time.time() * 1000)
    }
    
    # Sign
    canonical = json.dumps(msg, separators=(',', ':'), sort_keys=True)
    signature = base64.b64encode(
        hmac.new(SIGNAL_KEY.encode(), canonical.encode(), hashlib.sha256).digest()
    ).decode()
    msg["signature"] = signature
    
    payload = json.dumps(msg).encode()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(payload, (MANAGER_HOST, MANAGER_PORT))

if __name__ == "__main__":
    print(f"🚀 Starting Mesh Simulation for {len(EXCHANGES)} nodes...")
    
    # 1. Register all nodes
    for exc in EXCHANGES:
        send_signal(exc, 1)
        print(f"  [+] Registered {exc}")
        time.sleep(0.05)
    
    print("\n✅ Registration complete. Sending live signals with 5% simulated packet loss...")
    
    seqs = {exc: 1 for exc in EXCHANGES}
    
    try:
        while True:
            for exc in EXCHANGES:
                import random
                # Simulate packet loss
                if random.random() < 0.05:
                    seqs[exc] += 1
                    print(f"  [!] Simulating packet loss for {exc} (Skipped seq {seqs[exc]})")
                    seqs[exc] += 1
                    send_signal(exc, seqs[exc])
                else:
                    seqs[exc] += 1
                    send_signal(exc, seqs[exc])
            
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n🛑 Simulation stopped.")
