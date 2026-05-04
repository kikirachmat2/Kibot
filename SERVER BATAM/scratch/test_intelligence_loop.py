import sys
import os
import json
from pathlib import Path

# Setup paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "Core_Logic"))
sys.path.append(str(ROOT / "Intelligence"))
sys.path.append(str(ROOT / "Security"))

import sovereign_arbitrator
import kibot_learning_engine

def test_intelligence_feedback():
    print("--- Testing Intelligence Loop ---")
    
    # 1. Setup Learning Engine with some "Bad" stats for a pair
    learn = kibot_learning_engine.get_engine()
    pair = "fartcoin_idr"
    stats = learn.get_stats(pair)
    # Simulate losses
    for _ in range(5):
        stats.record_trade(-0.05, "NORMAL")
    learn.save_stats(stats)
    
    health = learn.get_pair_health(pair)
    print(f"Pair Health for {pair}: {health} (Expect < 0.5)")
    
    # 2. Setup Arbitrator
    arb = sovereign_arbitrator.get_arbitrator(ROOT / "state")
    arb.update_balances(10_000_000, 100) # Rp 10M, 100 USDC
    
    # 3. Request allocation for the "Bad" pair
    req = sovereign_arbitrator.AllocationRequest(
        source="INDODAX",
        asset=pair,
        signal_score=0.9, # High score signal
        ev_estimate=0.02,
        metadata={"price": 100, "market_mid_price": 100, "side": "BUY"}
    )
    
    ok, size, reason = arb.request_allocation(req)
    print(f"Request result for {pair}: approved={ok}, size={size}, reason={reason}")
    
    # 4. Request allocation for a "Good" pair
    pair2 = "btc_idr"
    stats2 = learn.get_stats(pair2)
    for _ in range(5):
        stats2.record_trade(0.05, "NORMAL")
    learn.save_stats(stats2)
    
    req2 = sovereign_arbitrator.AllocationRequest(
        source="INDODAX",
        asset=pair2,
        signal_score=0.9,
        ev_estimate=0.02,
        metadata={"price": 1000, "market_mid_price": 1000, "side": "BUY"}
    )
    ok2, size2, reason2 = arb.request_allocation(req2)
    print(f"Request result for {pair2}: approved={ok2}, size={size2}, reason={reason2}")
    
    if size2 > size:
        print("SUCCESS: Arbitrator correctly allocated more to the healthy pair.")
    else:
        print("FAILURE: Sizing logic did not differentiate based on health.")

if __name__ == "__main__":
    test_intelligence_feedback()
