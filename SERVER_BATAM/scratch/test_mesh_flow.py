#!/usr/bin/env python3
import socket
import json
import time
import os
import sys
from pathlib import Path

# Paths
BASE_DIR = Path("/Users/kiki/Documents/Web Develop/KiBot/SERVER_BATAM")
sys.path.append(str(BASE_DIR / "Support"))
sys.path.append(str(BASE_DIR / "AI_Orchestration"))

from kibot_ai_coordinator import query_ai
from ki_config import KIBOT_UDP_PORT

def simulate_mesh_flow():
    print("--- [MESH VALIDATION START] ---")
    
    # 1. Simulate Scanner Signal
    signal = {
        "type": "SCAN_SIGNAL",
        "pair": "SOL/IDR",
        "price": 2450000,
        "indicator": "RSI_OVERSOLD",
        "value": 28.5,
        "timestamp": time.time()
    }
    print(f"[STEP 1] Scanner Signal Generated: {signal['pair']} @ {signal['indicator']}")

    # 2. Batam Brain - AI Analysis (Dify)
    print(f"[STEP 2] Routing to Batam Brain (AI Orchestration)...")
    
    # We use VETO_ANALYSIS template: "Kamu adalah AI veto gate KiBot.\nSignal: {signal_data}\nMarket: {market_state}\nSystem: {system_health}\n"
    context = {
        "signal_data": signal,
        "market_state": {"trend": "BULLISH", "volatility": "LOW"},
        "system_health": {"cpu": "20%", "ram": "40%"}
    }
    
    try:
        # Note: query_ai signature is (prompt_type, context, ...)
        analysis = query_ai(prompt_type="VETO_ANALYSIS", context=context)
        
        # Check if we got a response
        if not analysis:
            print("[ERROR] No response from AI Coordinator.")
            return

        provider = analysis.get('provider', 'unknown')
        print(f"[STEP 2.1] AI Response received via {provider}")
        
        # 3. Simulate Executor Relay
        if analysis.get("approved") is True:
            print(f"[STEP 3] SENSORY MESH -> EXECUTOR: Relaying trade command...")
            # In a real scenario, kibot_manager would send this via UDP
            # Here we just simulate the UDP packet formation
            exec_msg = {
                "type": "TRADE_EXEC",
                "pair": signal["pair"],
                "side": "BUY",
                "amount": 1.0,
                "reason": analysis.get('answer')
            }
            payload = json.dumps(exec_msg).encode()
            print(f"[SUCCESS] UDP Packet Ready ({len(payload)} bytes): {exec_msg['pair']} {exec_msg['side']}")
        else:
            print("[INFO] Analysis suggests HOLD. No execution sent.")

    except Exception as e:
        print(f"[ERROR] Mesh Flow failed: {e}")

    print("--- [MESH VALIDATION COMPLETE] ---")

if __name__ == "__main__":
    simulate_mesh_flow()
