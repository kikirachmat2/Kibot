import asyncio
import logging
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from Core.Support.ki_config import KiConfig

logger = logging.getLogger("PhantomTreasury")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PHANTOM_STATE_FILE = STATE_DIR / "phantom_treasury.json"
PHANTOM_RECONCILIATION_FILE = STATE_DIR / "TREASURY_RECONCILIATION_REQUIRED"
USD_IDR_RATE = 16000.0  # Manifesto standard conversion rate

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
        self.base_idrx_symbol = "IDRX"
        self.base_idrx_decimals = 0
        self.base_latest_block = 0
        self.base_raw_balance = "0"
        self.base_rpc_ok = False
        self.base_status = "MISSING_CONFIG"
        self.solana_status = "MISSING"
        self.status = "MISSING_CONFIG"
        self.total_value_idr = 0.0
        self.reconciliation = {
            "expected_from_user_idr": 30074,
            "actual_value_idr": 0.0,
            "matches_user_wallet": False,
            "tolerance_pct": 2,
            "reason": "",
        }
        self.chains = {
            "solana": {
                "address": "",
                "sol_balance": 0.0,
                "usdc_balance": 0.0,
                "value_idr": 0.0,
                "status": "MISSING",
            },
            "base": {
                "evm_address": "",
                "rpc_ok": False,
                "idrx_token_address": "",
                "idrx_symbol": "IDRX",
                "idrx_decimals": 0,
                "raw_balance": "0",
                "normalized_idrx": 0.0,
                "value_idr": 0.0,
                "latest_block": 0,
                "status": "MISSING_CONFIG",
            },
        }
        
        # Load EVM Wallet Credentials from Environment
        self.evm_address = os.getenv("PHANTOM_EVM_ADDRESS", "0x...").strip()
        self.base_rpc_url = os.getenv("BASE_RPC_URL", "").strip()
        self.idrx_token_address = os.getenv("IDRX_BASE_TOKEN_ADDRESS", "").strip()
        self.expected_from_user_idr = float(os.getenv("PHANTOM_EXPECTED_IDRX_IDR", "30074") or 30074)
        self.force_live_base_reconciliation = os.getenv("PHANTOM_FORCE_LIVE_BASE_RECONCILIATION", "1").strip().lower() in {"1", "true", "yes", "on"}
        
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
                    "address": self.router.wallet_address if self.router else "",
                    "evm_address": self.evm_address,
                    "sol_balance": self.sol_balance,
                    "usdc_balance": self.usdc_balance,
                    "base_idrx_balance": self.base_idrx_balance,
                    "base_idrx_symbol": self.base_idrx_symbol,
                    "base_idrx_decimals": self.base_idrx_decimals,
                    "base_latest_block": self.base_latest_block,
                    "base_raw_balance": self.base_raw_balance,
                    "base_rpc_ok": self.base_rpc_ok,
                    "status": self.status,
                    "total_value_idr": self.total_value_idr,
                    "bucket_percentages": self.bucket_percentages,
                    "buckets": self.buckets,
                    "chains": self.chains,
                    "reconciliation": self.reconciliation,
                }, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save Phantom Treasury state: {e}")

    async def _rpc_call(self, method: str, params: list[Any]) -> Dict[str, Any]:
        if not self.base_rpc_url:
            return {}
        import aiohttp

        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                async with session.post(
                    self.base_rpc_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=8.0,
                ) as resp:
                    if resp.status == 200:
                        try:
                            return await resp.json()
                        except Exception:
                            return {}
                    if resp.status != 429:
                        logger.error("❌ Base RPC returned error status: %s", resp.status)
                        return {}
                await asyncio.sleep(0.5 * (attempt + 1))
        logger.error("❌ Base RPC rate-limited after retries for method %s", method)
        return {}

    async def _erc20_call(self, selector: str) -> str:
        if not self.evm_address or not self.base_rpc_url or not self.idrx_token_address:
            return "0x"
        clean_addr = self.evm_address.lower().replace("0x", "")
        padded_addr = clean_addr.rjust(64, "0")
        data = selector + padded_addr if selector == "0x70a08231" else selector
        res = await self._rpc_call("eth_call", [{"to": self.idrx_token_address, "data": data}, "latest"])
        result_hex = str(res.get("result") or "0x")
        if isinstance(res.get("error"), dict):
            logger.error("❌ Base RPC error: %s", res["error"])
        return result_hex

    async def _fetch_base_metadata(self) -> None:
        try:
            symbol_hex = await self._erc20_call("0x95d89b41")
            decimals_hex = await self._erc20_call("0x313ce567")
            block_hex = await self._rpc_call("eth_blockNumber", [])
            self.base_rpc_ok = bool(self.base_rpc_url and self.idrx_token_address and self.evm_address)

            if symbol_hex and symbol_hex.startswith("0x"):
                try:
                    raw = bytes.fromhex(symbol_hex[2:])
                    if len(raw) >= 64:
                        sym = raw[-4:].decode("utf-8", errors="ignore").strip("\x00")
                        self.base_idrx_symbol = sym or "IDRX"
                except Exception:
                    pass

            if decimals_hex and decimals_hex.startswith("0x"):
                try:
                    self.base_idrx_decimals = int(decimals_hex, 16)
                except Exception:
                    self.base_idrx_decimals = 0

            try:
                self.base_latest_block = int(str(block_hex.get("result") or "0x0"), 16)
            except Exception:
                self.base_latest_block = 0
        except Exception as e:
            logger.error("❌ Failed to fetch Base metadata: %s", e)
            self.base_rpc_ok = False

    async def get_base_idrx_balance(self) -> float:
        """Fetch real IDRX token balance on Base chain using EVM JSON-RPC."""
        if not self.evm_address or not self.base_rpc_url or not self.idrx_token_address:
            self.base_status = "MISSING_CONFIG"
            logger.warning("⚠️ EVM credentials (address, RPC, or IDRX token) are not fully configured.")
            return 0.0

        try:
            await self._fetch_base_metadata()
            result_hex = await self._erc20_call("0x70a08231")
            self.base_raw_balance = result_hex
            if result_hex in ("0x", "", None):
                self.base_status = "MISMATCH"
                return 0.0
            try:
                raw_value = int(result_hex, 16) if str(result_hex).startswith("0x") else int(result_hex)
            except ValueError:
                logger.error("❌ Failed to parse hex balance: %s", result_hex)
                self.base_status = "MISMATCH"
                return 0.0

            decimals = self.base_idrx_decimals if self.base_idrx_decimals > 0 else 2
            normalized = raw_value / float(10 ** decimals)
            self.base_idrx_balance = normalized
            self.base_status = "OK"
            return normalized
        except Exception as e:
            logger.error("❌ Exception fetching Base IDRX balance: %s", e)
            self.base_status = "MISMATCH"
            return 0.0

    def _evaluate_reconciliation(self, actual_value_idr: float) -> None:
        expected = float(self.expected_from_user_idr or 0.0)
        tolerance_pct = float(self.reconciliation.get("tolerance_pct", 2))
        allowed_delta = expected * (tolerance_pct / 100.0)
        delta = abs(actual_value_idr - expected)
        matches = expected > 0 and delta <= allowed_delta
        reason = ""
        if not self.evm_address or not self.base_rpc_url or not self.idrx_token_address:
            reason = "missing Base / EVM configuration"
        elif not self.base_rpc_ok:
            reason = "Base RPC unavailable"
        elif not matches:
            reason = f"wallet value mismatch: expected ~Rp{expected:,.0f}, actual Rp{actual_value_idr:,.0f}"

        self.reconciliation = {
            "expected_from_user_idr": round(expected, 0),
            "actual_value_idr": round(actual_value_idr, 0),
            "matches_user_wallet": matches,
            "tolerance_pct": tolerance_pct,
            "reason": reason,
        }
        if matches and self.base_rpc_ok:
            self.status = "OK"
            self.base_status = "OK"
        elif actual_value_idr > 0.0:
            # Balance is real, but our wallet reconciliation is degraded.
            # This should not behave like a missing wallet because the trading
            # engine still needs a truthful mark-to-market snapshot.
            self.status = "DEGRADED"
            self.base_status = "DEGRADED"
        elif not self.base_rpc_ok:
            self.status = "MISSING_CONFIG"
            self.base_status = "MISSING_CONFIG"
        else:
            self.status = "SCOUTING"
            self.base_status = "SCOUTING"

    def _write_reconciliation_flag(self) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            if self.status == "OK" and self.reconciliation.get("matches_user_wallet"):
                if PHANTOM_RECONCILIATION_FILE.exists():
                    PHANTOM_RECONCILIATION_FILE.unlink()
                return
            with open(PHANTOM_RECONCILIATION_FILE, "w") as f:
                json.dump({
                    "status": self.status,
                    "reason": self.reconciliation.get("reason", ""),
                    "expected_from_user_idr": self.reconciliation.get("expected_from_user_idr", 0),
                    "actual_value_idr": self.reconciliation.get("actual_value_idr", 0),
                    "matches_user_wallet": self.reconciliation.get("matches_user_wallet", False),
                    "tolerance_pct": self.reconciliation.get("tolerance_pct", 2),
                }, f, indent=2)
        except Exception as e:
            logger.error("❌ Failed to write reconciliation flag: %s", e)

    def _is_live_router(self) -> bool:
        return self.router is not None and self.router.__class__.__name__ == "PhantomRouter"

    async def reconcile_balances(self):
        """Fetch real balances from PhantomRouter and Base RPC, and recalculate buckets."""
        if self.router:
            try:
                balances = await self.router.get_balances()
                self.sol_balance = balances.get("sol_balance", 0.0)
                self.usdc_balance = balances.get("usdc_balance", 0.0)
                self.chains["solana"].update({
                    "address": getattr(self.router, "wallet_address", "") or "",
                    "sol_balance": self.sol_balance,
                    "usdc_balance": self.usdc_balance,
                    "status": "OK" if self.sol_balance >= 0 and self.usdc_balance >= 0 else "DEGRADED",
                })
            except Exception as e:
                logger.error(f"❌ Failed to query balances from PhantomRouter: {e}")
                self.chains["solana"]["status"] = "DEGRADED"
        
        # Fetch Base chain IDRX balance
        if self.force_live_base_reconciliation and self._is_live_router():
            self.base_idrx_balance = await self.get_base_idrx_balance()
        else:
            self.base_idrx_balance = 0.0
            self.base_raw_balance = "0x0"
            self.base_idrx_symbol = "IDRX"
            self.base_idrx_decimals = 0
            self.base_latest_block = 0
            self.base_rpc_ok = False
            self.base_status = "SCOUTING"

        # Calculate IDR equivalencies
        # SOL is valued at $170 USD for IDR conversion (assuming roughly stable Sol price)
        sol_value_usd = 170.0 
        sol_value_idr = self.sol_balance * sol_value_usd * USD_IDR_RATE
        usdc_value_idr = self.usdc_balance * USD_IDR_RATE
        base_idrx_value_idr = self.base_idrx_balance  # 1 IDRX = 1 IDR
        
        self.total_value_idr = sol_value_idr + usdc_value_idr + base_idrx_value_idr
        self._update_allocation_percentages()
        if self.force_live_base_reconciliation and self._is_live_router():
            self._evaluate_reconciliation(base_idrx_value_idr)
        else:
            self.reconciliation = {
                "expected_from_user_idr": round(self.expected_from_user_idr, 0),
                "actual_value_idr": 0.0,
                "matches_user_wallet": True,
                "tolerance_pct": 2,
                "reason": "scouting-only mode",
            }
            self.status = "SCOUTING"
        self._write_reconciliation_flag()
        
        # Split into buckets
        self.buckets = {
            "swap_idr": self.total_value_idr * self.bucket_percentages.get("swap", 0.0),
            "polymarket_idr": self.total_value_idr * self.bucket_percentages.get("polymarket", 0.0),
            "reserve_idr": self.total_value_idr * self.bucket_percentages.get("reserve", 0.0),
            "future_web3_idr": self.total_value_idr * self.bucket_percentages.get("future_web3", 0.0)
        }
        self.chains["base"].update({
            "evm_address": self.evm_address,
            "rpc_ok": self.base_rpc_ok,
            "idrx_token_address": self.idrx_token_address,
            "idrx_symbol": self.base_idrx_symbol,
            "idrx_decimals": self.base_idrx_decimals,
            "raw_balance": self.base_raw_balance,
            "normalized_idrx": self.base_idrx_balance,
            "value_idr": base_idrx_value_idr,
            "latest_block": self.base_latest_block,
            "status": self.base_status,
        })
        self.save()

    def get_summary(self) -> Dict[str, Any]:
        return {
            "address": self.router.wallet_address if self.router else "",
            "evm_address": self.evm_address,
            "sol_balance": self.sol_balance,
            "usdc_balance": self.usdc_balance,
            "base_idrx_balance": self.base_idrx_balance,
            "base_idrx_symbol": self.base_idrx_symbol,
            "base_idrx_decimals": self.base_idrx_decimals,
            "base_raw_balance": self.base_raw_balance,
            "base_latest_block": self.base_latest_block,
            "base_rpc_ok": self.base_rpc_ok,
            "status": self.status,
            "total_value_idr": self.total_value_idr,
            "bucket_percentages": self.bucket_percentages,
            "buckets": self.buckets,
            "chains": self.chains,
            "reconciliation": self.reconciliation,
        }
