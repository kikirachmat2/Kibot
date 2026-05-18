import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional

from Core.Support.ki_config import KiConfig

logger = logging.getLogger("PhantomTreasury")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PHANTOM_STATE_FILE = STATE_DIR / "phantom_treasury.json"
USD_IDR_RATE = 16000.0  # Manifesto standard conversion rate

import os

class PhantomTreasury:
    """
    Sovereign Phantom Treasury Manager
    Interfaces with PhantomRouter to fetch SOL & USDC, converts to IDR,
    queries Base EVM wallet for IDRX balance, and dynamically allocates
    capital into Swap, Polymarket, Reserve, and future Web3.
    """
    def __init__(self, phantom_router=None):
        self.router = phantom_router
        self.sol_balance = 0.0
        self.usdc_balance = 0.0
        self.base_idrx_balance = 0.0
        self.total_value_idr = 0.0
        
        # Load EVM Wallet Credentials from Environment
        self.evm_address = os.getenv("PHANTOM_EVM_ADDRESS", "0x...").strip()
        self.base_rpc_url = os.getenv("BASE_RPC_URL", "").strip()
        self.idrx_token_address = os.getenv("IDRX_BASE_TOKEN_ADDRESS", "").strip()
        
        # Default bucket percentages
        self.bucket_percentages = {
            "swap": 0.40,
            "polymarket": 0.20,
            "reserve": 0.40,
            "future_web3": 0.00
        }
        self.buckets = {
            "swap_idr": 0.0,
            "polymarket_idr": 0.0,
            "reserve_idr": 0.0,
            "future_web3_idr": 0.0
        }
        self._load_state()

    def _load_state(self):
        if PHANTOM_STATE_FILE.exists():
            try:
                with open(PHANTOM_STATE_FILE, "r") as f:
                    data = json.load(f)
                    self.bucket_percentages = data.get("bucket_percentages", self.bucket_percentages)
                    self.buckets = data.get("buckets", self.buckets)
                    self.base_idrx_balance = data.get("base_idrx_balance", 0.0)
                    logger.info("✅ Phantom Treasury state loaded successfully.")
            except Exception as e:
                logger.error(f"❌ Failed to load Phantom Treasury state: {e}")
        self._update_allocation_percentages()

    def _update_allocation_percentages(self):
        """Derive sub-bucket allocation percentages based on user instructions."""
        # Allocate Phantom Base funding to buckets (Swap 40%, Polymarket 20%, Reserve 40%, Future Web3 0%)
        self.bucket_percentages = {
            "swap": 0.40,
            "polymarket": 0.20,
            "reserve": 0.40,
            "future_web3": 0.00
        }

    def save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(PHANTOM_STATE_FILE, "w") as f:
                json.dump({
                    "address": self.router.wallet_address if self.router else "0x...",
                    "evm_address": self.evm_address,
                    "sol_balance": self.sol_balance,
                    "usdc_balance": self.usdc_balance,
                    "base_idrx_balance": self.base_idrx_balance,
                    "total_value_idr": self.total_value_idr,
                    "bucket_percentages": self.bucket_percentages,
                    "buckets": self.buckets
                }, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save Phantom Treasury state: {e}")

    async def get_base_idrx_balance(self) -> float:
        """Fetch real IDRX token balance on Base chain using EVM JSON-RPC."""
        if not self.evm_address or not self.base_rpc_url or not self.idrx_token_address:
            logger.warning("⚠️ EVM credentials (address, RPC, or IDRX token) are not fully configured.")
            return 0.0
            
        clean_addr = self.evm_address.lower().replace("0x", "")
        padded_addr = clean_addr.rjust(64, '0')
        data = "0x70a08231" + padded_addr
        
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": self.idrx_token_address,
                    "data": data
                },
                "latest"
            ],
            "id": 1
        }
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.base_rpc_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=5.0
                ) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        result_hex = res_json.get("result", "0x0")
                        if result_hex == "0x" or not result_hex:
                            return 0.0
                        try:
                            val = int(result_hex, 16) if result_hex.startswith("0x") else int(result_hex)
                            return val / 100.0  # IDRX token has 2 decimals
                        except ValueError:
                            logger.error(f"❌ Failed to parse hex balance: {result_hex}")
                            return 0.0
                    else:
                        logger.error(f"❌ Base RPC returned error status: {resp.status}")
        except Exception as e:
            logger.error(f"❌ Exception fetching Base IDRX balance: {e}")
        return 0.0

    async def reconcile_balances(self):
        """Fetch real balances from PhantomRouter and Base RPC, and recalculate buckets."""
        if self.router:
            try:
                balances = await self.router.get_balances()
                self.sol_balance = balances.get("sol_balance", 0.0)
                self.usdc_balance = balances.get("usdc_balance", 0.0)
            except Exception as e:
                logger.error(f"❌ Failed to query balances from PhantomRouter: {e}")
        
        # Fetch Base chain IDRX balance
        self.base_idrx_balance = await self.get_base_idrx_balance()
        
        # Calculate IDR equivalencies
        # SOL is valued at $170 USD for IDR conversion (assuming roughly stable Sol price)
        sol_value_usd = 170.0 
        sol_value_idr = self.sol_balance * sol_value_usd * USD_IDR_RATE
        usdc_value_idr = self.usdc_balance * USD_IDR_RATE
        base_idrx_value_idr = self.base_idrx_balance  # 1 IDRX = 1 IDR
        
        self.total_value_idr = sol_value_idr + usdc_value_idr + base_idrx_value_idr
        self._update_allocation_percentages()
        
        # Split into buckets
        self.buckets = {
            "swap_idr": self.total_value_idr * self.bucket_percentages.get("swap", 0.0),
            "polymarket_idr": self.total_value_idr * self.bucket_percentages.get("polymarket", 0.0),
            "reserve_idr": self.total_value_idr * self.bucket_percentages.get("reserve", 0.0),
            "future_web3_idr": self.total_value_idr * self.bucket_percentages.get("future_web3", 0.0)
        }
        self.save()

    def get_summary(self) -> Dict[str, Any]:
        return {
            "address": self.router.wallet_address if self.router else "0x...",
            "evm_address": self.evm_address,
            "sol_balance": self.sol_balance,
            "usdc_balance": self.usdc_balance,
            "base_idrx_balance": self.base_idrx_balance,
            "total_value_idr": self.total_value_idr,
            "bucket_percentages": self.bucket_percentages,
            "buckets": self.buckets
        }
