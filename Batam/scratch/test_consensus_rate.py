from pathlib import Path
import sys
import os

# Setup paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "Core_Logic"))
sys.path.append(str(ROOT / "Security"))

import sovereign_arbitrator
import logging

logging.basicConfig(level=logging.INFO)

def test_consensus_rate():
    print("--- Testing Consensus Sovereign Rate ---")
    arb = sovereign_arbitrator.SovereignArbitrator(ROOT / "state")
    
    # Force refresh
    arb.refresh_usd_rate()
    
    print(f"Final Consensus Rate: Rp {arb.usd_idr_rate:,.2f}")
    if arb.usd_idr_rate > 15000:
        print("SUCCESS: Rate is within realistic bounds.")
    else:
        print("FAILURE: Rate seems incorrect.")

if __name__ == "__main__":
    test_consensus_rate()
