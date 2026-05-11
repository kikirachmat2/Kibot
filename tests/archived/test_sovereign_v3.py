import asyncio
import time
import json
import logging
from Core.sovereign_council import SovereignCouncil
from Core.sovereign_state import load_strategy, clear_urgency

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("V3FinalTest")

async def run_v3_test():
    council = SovereignCouncil()
    clear_urgency()
    
    print("\n" + "="*50)
    print("🏆 KIBOT SOVEREIGN V3: FINAL INTEGRATION TEST")
    print("="*50)

    # --- 1. TEST STRATEGIC PLANNING (Council Brain) ---
    print("\n[STEP 1] Council Strategic Debate (5-min Cycle Sim)")
    market_snapshot = {
        "indodax": {"BTC_IDR": {"price": 1000000000, "change_24h": 2.5}},
        "polymarket": {"US_ELECTION": {"volume": 500000, "odds": 0.55}}
    }
    
    start = time.time()
    await council.run_strategic_planning(market_snapshot)
    print(f"Strategic Cycle Latency: {time.time() - start:.2f}s (Expected: Slow, Deep Thinking)")

    # --- 2. TEST SCRIPT EXECUTION (The Reflex) ---
    print("\n[STEP 2] Executor Script Logic (Fast Reflex Sim)")
    strategy = load_strategy()
    print(f"Active Mode: {strategy.get('global_mode')}")
    print(f"Indodax Hard Stop: {strategy.get('indodax', {}).get('hard_stop_pct')}%")

    # Simulate a signal that fits the new strategy
    from Core.Executors.indodax_executor import IndodaxExecutor
    executor = IndodaxExecutor()
    executor.running = True
    
    test_signal = {
        "symbol": "BTC_IDR",
        "side": "BUY",
        "price": 990000000,
        "confidence": 0.95,
        "change_pct": 0.7
    }
    
    print("\nProcessing signal via Script (No AI Call)...")
    start = time.time()
    await executor.process_signal(test_signal)
    print(f"Script Execution Latency: {(time.time() - start)*1000:.2f}ms (Expected: < 10ms)")

    # --- 3. TEST ACTIVE GUARDIAN (War Room) ---
    print("\n[STEP 3] Active Guardian (War Room Sim)")
    await council.monitor_active_position("BTC_IDR", 990000000)

if __name__ == "__main__":
    asyncio.run(run_v3_test())
