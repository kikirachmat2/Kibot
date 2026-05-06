import sys
import os
import json
from pathlib import Path

# Add directories to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "Core_Logic"))
sys.path.append(str(ROOT / "AI_Orchestration"))
sys.path.append(str(ROOT / "Support"))

from ki_brain import BrainManager

def test_brain_consensus():
    print("--- [KIBOT] Testing Brain Consensus (Pinter Mode) ---")
    brain = BrainManager()
    
    # Mock data for a "Bull Trap" scenario
    pair = "BTC_IDR"
    msg_type = "SIGNAL" # Buy Signal
    regime = "SIDEWAYS_VOLATILE"
    obi = -0.75 # Heavy sell pressure (negative OBI)
    session = "ASIAN_MORNING"
    
    print(f"Scenario: {pair} Buy Signal in {regime} with OBI={obi}")
    print("Running 7-Agent Consensus Debate...")
    
    decision, reason = brain._get_ai_consensus(pair, msg_type, regime, obi, session)
    
    print(f"\n[VERDICT] {decision}")
    print(f"[REASON] {reason}")
    
    if decision == "REJECT":
        print("\nSUCCESS: Brain correctly identified the OBI risk and rejected the bull trap.")
    else:
        print("\nWARNING: Brain approved a high-risk trade. Check agent weights.")

if __name__ == "__main__":
    test_brain_consensus()
