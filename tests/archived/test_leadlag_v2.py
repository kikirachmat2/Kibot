import asyncio
import time
import json
import logging
from Core.sovereign_council import SovereignCouncil

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger("LeadLagSim")

async def run_simulation():
    council = SovereignCouncil()
    
    print("\n" + "="*50)
    print("🚀 STARTING LEAD-LAG STRESS TEST (V2 MESH)")
    print("="*50)
    
    # SIMULATING A BRUTAL PRICE SPIKE ON BINANCE
    # Binance moves +1.2% in 1 second, while local stays flat.
    simulated_signals = [
        {
            "type": "GLOBAL_LEAD",
            "symbol": "BTC",
            "source": "BINANCE",
            "price": 65000.0,
            "change_pct": 1.25,  # Brutal Spike
            "verdict": "BULLISH",
            "confidence": 9.5,
            "ts": int(time.time() * 1000),
            "priority": "HIGH",
            "market_context": {
                "local_price": 64200.0,
                "global_spread": 0.0125,
                "order_book_depth": "MEDIUM",
                "volatility": "HIGH"
            }
        }
    ]
    
    context = {"signals": simulated_signals}
    
    print("\n[STEP 1] Detecting Lead signal from Binance...")
    print(f"Signal: BTC +1.25% (Global Lead Detected)")
    
    print("\n[STEP 2] Launching Parallel Deliberation (Hawk & Sentinel)...")
    start_time = time.time()
    
    directive = await council.deliberate_trading(context)
    
    end_time = time.time()
    total_latency = end_time - start_time
    
    print("\n[STEP 3] Final Decision Results:")
    print(f"Action: {directive.get('action')}")
    print(f"Confidence: {directive.get('confidence')}")
    print(f"Oracle Verdict: {directive.get('oracle_verdict')}")
    print(f"Total Logic Latency: {total_latency:.2f} seconds")
    
    print("\n[DEBATE SUMMARY]")
    print(f"Hawk View: {directive.get('hawk_view', {}).get('thesis')}")
    print(f"Sentinel View: {directive.get('sentinel_view', {}).get('risk_critique')}")
    print(f"Speaker Logic: {directive.get('logic')}")
    
    if directive.get('action') == "BUY" and directive.get('oracle_verdict') == "APPROVED":
        print("\n✅ RESULT: SUCCESSFUL LEAD-LAG CAPTURE. MANDATE ISSUED.")
    elif directive.get('oracle_verdict') == "REJECTED":
        print("\n🛡️ RESULT: RISK VETOED. TRADE PREVENTED BY ORACLE.")
    else:
        print("\n⏸️ RESULT: NO ACTION TAKEN.")

if __name__ == "__main__":
    asyncio.run(run_simulation())
