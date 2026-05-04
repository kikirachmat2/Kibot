import sys
import os
from pathlib import Path

# Setup paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "Intelligence"))
sys.path.append(str(ROOT / "Indicators_Math"))

import kibot_rotation_engine

def test_rotation_v8():
    print("--- Testing Rotation Engine v8.0 ---")
    re = kibot_rotation_engine.RotationEngine()
    
    # 1. Normal Regime Test
    pos = {"symbol": "eth_idr", "pnl_pct": 2.0, "confidence": 60, "entry_time": 0}
    sig = {"symbol": "sol_idr", "confidence": 90}
    ctx = {"regime": "BULLISH"}
    
    res = re.evaluate_rotation(pos, sig, ctx)
    print(f"BULLISH Profit Rotation: {res['approved']}, Score: {res['rotation_score']}, Reason: {res['reason']}")
    
    # 2. Panic Regime Correlation Test
    # Assuming eth_idr and sol_idr are NOT in the same sector (checked universe overlay)
    # Let's mock the universe to put them in the same sector
    re.universe["sectors"]["eth_idr"] = "layer1"
    re.universe["sectors"]["sol_idr"] = "layer1"
    
    ctx_panic = {"regime": "PANIC_BREAKDOWN"}
    pos_loser = {"symbol": "eth_idr", "pnl_pct": -5.0, "confidence": 40, "entry_time": 0}
    sig_high = {"symbol": "sol_idr", "confidence": 95}
    
    res_panic = re.evaluate_rotation(pos_loser, sig_high, ctx_panic)
    print(f"PANIC Correlation Veto: {res_panic['approved']}, Reason: {res_panic['reason']}")
    
    if not res_panic['approved'] and "CORRELATION_VETO" in res_panic['reason']:
        print("SUCCESS: Rotation Engine correctly vetoed correlated rotation during panic.")
    else:
        print("FAILURE: Correlation veto failed.")

if __name__ == "__main__":
    test_rotation_v8()
