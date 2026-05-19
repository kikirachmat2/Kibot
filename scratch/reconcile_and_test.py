import asyncio
import logging
import os
import sys
from pathlib import Path

# Add project root to python path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()

from Core.Treasury.phantom_treasury import PhantomTreasury
from Core.Exchange.phantom_router import PhantomRouter

logging.basicConfig(level=logging.INFO)

async def main():
    print("Initializing PhantomRouter...")
    router = PhantomRouter()
    
    print("Initializing PhantomTreasury...")
    treasury = PhantomTreasury(router)
    
    print("\n--- Current State before reconciliation ---")
    print(f"EVM Address: {treasury.evm_address}")
    print(f"Base RPC URL: {treasury.base_rpc_url}")
    print(f"IDRX Contract: {treasury.idrx_token_address}")
    print(f"Current base_idrx_balance from state: {treasury.base_idrx_balance}")
    print(f"Current total_value_idr from state: {treasury.total_value_idr}")
    
    print("\nRunning reconcile_balances()...")
    await treasury.reconcile_balances()
    
    print("\n--- Reconciled State ---")
    summary = treasury.get_summary()
    for k, v in summary.items():
        print(f"{k}: {v}")

    # Close router client session
    await router._close()

if __name__ == "__main__":
    asyncio.run(main())
