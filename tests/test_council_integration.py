import asyncio, json, logging
from Core.sovereign_council import SovereignCouncil

logging.basicConfig(level=logging.INFO)

async def test_deliberation():
    council = SovereignCouncil()
    
    # Simulate a strong trading signal
    context = {
        "signals": [
            {
                "base_symbol": "BTC/IDR",
                "confidence": 0.92,
                "pump_probability": 0.88,
                "lag_sec": 0.5,
                "exchange": "BINANCE",
                "source": "UNIVERSAL_LEAD"
            }
        ]
    }
    
    print("\n--- [TEST] Deliberating Trading Directive ---")
    directive = await council.deliberate_trading(context)
    print(f"RESULT: {json.dumps(directive, indent=2)}")
    
    # Simulate a system issue
    issue = {
        "type": "ANOMALY",
        "snapshot": {
            "executor_status": "DISCONNECTED",
            "uptime": 3600,
            "memory_usage": "85%"
        }
    }
    
    print("\n--- [TEST] Deliberating System Issue ---")
    system_action = await council.deliberate_system(issue)
    print(f"RESULT: {json.dumps(system_action, indent=2)}")

if __name__ == "__main__":
    asyncio.run(test_deliberation())
