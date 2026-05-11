import asyncio
import time
import json
import logging
from Core.sovereign_council import SovereignCouncil

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("HybridSim")

async def run_hybrid_test():
    council = SovereignCouncil()
    
    print("\n" + "="*50)
    print("🚀 HYBRID-ORACLE V2 STRESS TEST")
    print("="*50)

    # --- CASE 1: SCRIPTED VETO (Low Spread) ---
    print("\n[CASE 1] Low Spread Signal (0.05%)")
    low_signal = [{
        "type": "GLOBAL_LEAD",
        "symbol": "BTC",
        "change_pct": 0.05,
        "confidence": 5.0
    }]
    start = time.time()
    res1 = await council.deliberate_trading({"signals": low_signal})
    print(f"Result: {res1.get('action')} - Reason: {res1.get('reason')}")
    print(f"Latency: {(time.time() - start)*1000:.2f}ms (Should be near zero)")

    # --- CASE 2: FAST-TRACK APPROVAL (High Spread) ---
    print("\n[CASE 2] High Spread Signal (0.85%) - Expecting Fast-Track")
    high_signal = [{
        "type": "GLOBAL_LEAD",
        "symbol": "ETH",
        "change_pct": 0.85,
        "confidence": 9.0
    }]
    start = time.time()
    res2 = await council.deliberate_trading({"signals": high_signal})
    print(f"Result: {res2.get('action')}")
    print(f"Oracle Verdict: {res2.get('oracle_verdict')}")
    print(f"Total Latency: {res2.get('latency_sec')}s (Expected: Much lower than 27s)")

if __name__ == "__main__":
    asyncio.run(run_hybrid_test())
