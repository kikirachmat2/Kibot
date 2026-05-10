import asyncio
import json
import logging
import time
import os

# Set up logging to see the Council's thought process
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

async def run_sensory_simulation():
    print("\n" + "="*50)
    print("🛰️ STARTING SENSORY SIMULATION: INFRASTRUCTURE ANOMALY")
    print("="*50)
    
    from SERVER_BATAM.Core.sovereign_council import SovereignCouncil
    
    # Simulate a degraded telemetry snapshot
    telemetry_snapshot = {
        "timestamp": time.time(),
        "os_load": (5.20, 4.80, 4.50), # High load
        "redis": "OFFLINE",           # REDIS DOWN!
        "tailscale": "NeedsAuth",      # MESH DEGRADED!
        "heartbeat": "ACTIVE"
    }
    
    issue = {
        "type": "SYSTEM_ANOMALY",
        "snapshot": telemetry_snapshot
    }
    
    print("📡 Watchman (Observer) is scanning telemetry...")
    council = SovereignCouncil()
    
    # Deliberate based on the anomaly
    decision = await council.deliberate(issue)
    
    print("\n" + "="*50)
    print("🏛️ COUNCIL FINAL DECISION")
    print(f"Action     : {decision.get('action')}")
    print(f"Confidence : {decision.get('confidence', 0)*100:.1f}%")
    print(f"Risk Level : {decision.get('risk')}")
    print(f"Reasoning  : {decision.get('reasoning')}")
    print("="*50)

if __name__ == "__main__":
    asyncio.run(run_sensory_simulation())
