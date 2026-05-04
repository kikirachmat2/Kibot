import time
import sys
from pathlib import Path

# Add project roots
_root = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(_root / "Core_Logic"))
sys.path.append(str(_root / "Support"))

try:
    from kibot_manager import _can_enter
    import kibot_manager
except ImportError:
    print("❌ ERROR: Could not import kibot_manager. Ensure paths are correct.")
    sys.exit(1)

def benchmark_can_enter():
    print("🚀 Starting Latency Benchmark for KiBot v7.0 Hot-Path...")
    
    # Mocking necessary states to pass early gates
    kibot_manager._ai_healthy = True
    kibot_manager._KiBot_healthy = True
    kibot_manager.AI_ROUTER_ENABLED = True
    
    pair = "BTC_IDR"
    msg_type = "SIGNAL"
    
    # 1. Warm up
    _can_enter(pair, msg_type)
    
    # 2. Benchmark Loop
    iterations = 1000
    start_time = time.perf_counter()
    
    for _ in range(iterations):
        _can_enter(pair, msg_type)
    
    end_time = time.perf_counter()
    
    avg_latency_ms = ((end_time - start_time) / iterations) * 1000
    
    print(f"\n--- Results ---")
    print(f"Total Iterations: {iterations}")
    print(f"Average Latency: {avg_latency_ms:.4f} ms")
    
    if avg_latency_ms < 1.0:
        print("✅ SUCCESS: Latency is SUB-MILLISECOND as promised!")
    else:
        print("⚠️ WARNING: Latency exceeds 1ms target.")

if __name__ == "__main__":
    benchmark_can_enter()
