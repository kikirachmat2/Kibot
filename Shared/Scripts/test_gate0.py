import sys
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "SERVER_BATAM" / "Core_Logic"))

# Mock os.environ for test
os.environ["KIBOT_MANAGER_DATA_DIR"] = "/tmp/kibot_data"
os.environ["SUPABASE_URL"] = "https://example.supabase.co"
os.environ["SUPABASE_ANON_KEY"] = "fake-key"

# Mock classes that kibot_manager uses at top level
import kibot_manager

def test_gate0():
    print("Testing Trinity Gate 0...")
    
    # Reset state
    kibot_manager._ai_healthy = True
    kibot_manager._entry_loss_count = {}
    kibot_manager._last_entry = {}
    kibot_manager._hard_stop.hard_stopped = False
    kibot_manager._gate_state["mode"] = "NORMAL"
    
    # 1. Test Normal Entry
    allowed, reason = kibot_manager._can_enter("btc_idr", "SIGNAL")
    assert allowed, f"Expected allowed, got {reason}"
    print("✅ Normal entry passed")
    
    # 2. Test Hard Stop
    kibot_manager._hard_stop.hard_stopped = True
    allowed, reason = kibot_manager._can_enter("btc_idr", "SIGNAL")
    assert not allowed and "HARD_STOP" in reason, f"Expected blocked by hard stop, got {allowed}, {reason}"
    print("✅ Hard stop blocked OK")
    kibot_manager._hard_stop.hard_stopped = False
    
    # 3. Test AI Health
    kibot_manager._ai_healthy = False
    allowed, reason = kibot_manager._can_enter("btc_idr", "SIGNAL")
    assert not allowed and "AI_HEALTH" in reason, f"Expected blocked by AI health, got {allowed}, {reason}"
    print("✅ AI offline blocked OK")
    kibot_manager._ai_healthy = True
    
    # 4. Test Quarantine
    kibot_manager._last_entry["eth_idr"] = time.time() - 100 # 100s ago
    allowed, reason = kibot_manager._can_enter("eth_idr", "SIGNAL")
    assert not allowed and "QUARANTINE" in reason, f"Expected blocked by quarantine, got {allowed}, {reason}"
    print("✅ Quarantine blocked OK")
    
    # 5. Test Blacklist (2 losses)
    kibot_manager._entry_loss_count["sol_idr"] = 2
    allowed, reason = kibot_manager._can_enter("sol_idr", "SIGNAL")
    assert not allowed and "BLACKLIST" in reason, f"Expected blocked by blacklist, got {allowed}, {reason}"
    print("✅ Blacklist blocked OK")
    
    print("\n" + "="*50)
    print("✅ TRINITY GATE 0 TEST PASSED")
    print("="*50)

if __name__ == "__main__":
    try:
        test_gate0()
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        sys.exit(1)
