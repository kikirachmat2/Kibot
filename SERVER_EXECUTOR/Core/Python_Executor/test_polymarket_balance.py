import os
import sys
from pathlib import Path
from web3 import Web3

# Setup paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
sys.path.append(str(ROOT_DIR))

from SERVER_BATAM.Support.ki_vault import load_sovereign_env

# ERC20 ABI (Minimal)
ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"}
]

USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

async def test_polygon_connectivity():
    load_sovereign_env()
    
    wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS")
    if not wallet_address:
        print("❌ POLYMARKET_WALLET_ADDRESS missing in environment!")
        return

    # Polygon RPC (Try multiple if one fails)
    rpcs = ["https://1rpc.io/matic", "https://polygon.meowrpc.com", "https://polygon-rpc.com"]
    w3 = None
    for rpc in rpcs:
        w3_temp = Web3(Web3.HTTPProvider(rpc))
        try:
            if w3_temp.is_connected():
                w3 = w3_temp
                print(f"✅ Connected via {rpc}")
                break
        except Exception:
            continue
    
    if not w3:
        print("❌ Failed to connect to all Polygon RPCs!")
        return

    print(f"🔗 Connected to Polygon. Checking wallet: {wallet_address}")
    
    # 1. MATIC Balance
    balance_wei = w3.eth.get_balance(wallet_address)
    balance_matic = w3.from_wei(balance_wei, 'ether')
    print(f"💎 MATIC: {balance_matic}")

    # 2. USDC Balance
    for usdc_addr in [USDC_NATIVE, USDC_E]:
        try:
            contract = w3.eth.contract(address=w3.to_checksum_address(usdc_addr), abi=ERC20_ABI)
            symbol = contract.functions.symbol().call()
            decimals = contract.functions.decimals().call()
            bal = contract.functions.balanceOf(wallet_address).call()
            print(f"💵 {symbol} ({usdc_addr[:6]}...): {bal / (10**decimals)}")
        except Exception as e:
            print(f"⚠️ Could not fetch balance for {usdc_addr}: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_polygon_connectivity())
