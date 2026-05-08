import socket
import json
import time

TARGET_IP = "127.0.0.1"
TARGET_PORT = 9998

def send_mock_signal(symbol, price, change, obi=0.0, regime="TRENDING_BULL"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = {
        "s": symbol,
        "p": price,
        "c": change,
        "obi": obi,
        "regime": regime,
        "ts": time.time()
    }
    print(f"Sending Mock Signal: {symbol} | Price: {price} | Change: {change}% | Regime: {regime}")
    sock.sendto(json.dumps(payload).encode(), (TARGET_IP, TARGET_PORT))

if __name__ == "__main__":
    print("--- STARTING LIVE WHAT-IF SCENARIO TESTS ---")
    
    # SCENARIO 1: Healthy Bull (Should Pass if Sentiment is Good)
    send_mock_signal("BTC_IDR", 1500000000, 3.5, obi=0.4, regime="TRENDING_BULL")
    time.sleep(2)

    # SCENARIO 2: Panic Sell / Bear (Should be Vetoed by Regime)
    send_mock_signal("ETH_IDR", 50000000, -5.0, obi=-0.7, regime="TRENDING_BEAR")
    time.sleep(2)

    # SCENARIO 3: Fake Pump (High Change but Negative OBI/Consensus)
    send_mock_signal("SOL_IDR", 3000000, 15.0, obi=-0.8, regime="SIDEWAYS_VOLATILE")
    
    print("\n--- TESTS SENT. CHECK kibot_brain_gateway.py LOGS ---")
