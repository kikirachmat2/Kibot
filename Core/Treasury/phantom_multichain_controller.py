import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("PhantomMultichainController")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PHANTOM_TREASURY_FILE = STATE_DIR / "phantom_treasury.json"
PHANTOM_RECONCILIATION_FILE = STATE_DIR / "TREASURY_RECONCILIATION_REQUIRED"

class PhantomMultichainController:
    """Sovereign multichain router for Phantom capital."""

    def __init__(self):
        self.registry: Dict[str, Dict[str, Any]] = {
            "solana": {"status": "SCOUTING", "balance_reader": True, "opportunity_scanner": True, "swap_executor": True, "risk_guard": True},
            "base": {"status": "BLOCKED_WITH_REASON", "balance_reader": True, "opportunity_scanner": True, "quote_router": True, "swap_executor": True, "executor": True, "risk_guard": True, "reason": "base_not_refreshed"},
            "polymarket": {"status": "SCOUTING", "balance_reader": True, "opportunity_scanner": True, "executor": True, "risk_guard": True},
            "future_web3": {"status": "BLOCKED_WITH_REASON", "balance_reader": False, "opportunity_scanner": True, "swap_executor": False, "executor": False, "risk_guard": True, "reason": "registry_not_refreshed"},
        }

    def _load_treasury_state(self) -> Dict[str, Any]:
        if not PHANTOM_TREASURY_FILE.exists():
            return {}
        try:
            return json.loads(PHANTOM_TREASURY_FILE.read_text())
        except Exception as e:
            logger.error("Failed to load phantom treasury state: %s", e)
            return {}

    def _reconciliation_blocked(self) -> bool:
        if PHANTOM_RECONCILIATION_FILE.exists():
            try:
                payload = json.loads(PHANTOM_RECONCILIATION_FILE.read_text())
                return not bool(payload.get("matches_user_wallet"))
            except Exception:
                return True
        treasury = self._load_treasury_state()
        recon = treasury.get("reconciliation", {}) if isinstance(treasury, dict) else {}
        return not bool(recon.get("matches_user_wallet", False))

    def _apply_base_gate(self, treasury: Dict[str, Any]) -> None:
        blocked = self._reconciliation_blocked()
        base = self.registry["base"]
        base["status"] = "BLOCKED_WITH_REASON" if blocked else "LIVE_READY"
        base["reason"] = "treasury_reconciliation_required" if blocked else ""
        base["balance_reader"] = bool(treasury.get("chains", {}).get("base", {}).get("rpc_ok"))
        base["quote_router"] = bool(base["balance_reader"])
        base["swap_executor"] = bool(base["balance_reader"] and not blocked)
        base["executor"] = bool(base["swap_executor"])

    def refresh(self) -> Dict[str, Dict[str, Any]]:
        treasury = self._load_treasury_state()
        blocked = self._reconciliation_blocked()
        self.registry["solana"]["status"] = "LIVE_READY" if not blocked else "BLOCKED"
        self.registry["solana"]["balance_reader"] = True
        self.registry["solana"]["swap_executor"] = True
        self.registry["solana"]["opportunity_scanner"] = True
        self.registry["solana"]["risk_guard"] = True

        self._apply_base_gate(treasury)

        poly = self.registry["polymarket"]
        bucket_poly = float(treasury.get("buckets", {}).get("polymarket_idr", 0.0) or 0.0)
        poly["status"] = "LIVE_READY" if (not blocked and bucket_poly > 0) else "BLOCKED" if blocked else "SCOUTING"
        poly["balance_reader"] = True
        poly["opportunity_scanner"] = True
        poly["executor"] = True
        poly["risk_guard"] = True

        future = self.registry["future_web3"]
        try:
            from Core.Web3.future_web3_registry import FutureWeb3Registry
            registry = FutureWeb3Registry().refresh()
            adapters = registry.get("adapters", {}) if isinstance(registry, dict) else {}
            executable = [name for name, item in adapters.items() if isinstance(item, dict) and str(item.get("status", "")).upper() == "LIVE_READY"]
            future["adapters"] = adapters
            future["status"] = "LIVE_READY" if executable else "BLOCKED_WITH_REASON"
            future["executor"] = bool(executable)
            future["swap_executor"] = bool(executable)
            future["reason"] = "" if executable else registry.get("reason") or "adapter_registry_missing"
            future["balance_reader"] = bool(executable)
        except Exception as exc:
            future.update({"status": "BLOCKED_WITH_REASON", "balance_reader": False, "swap_executor": False, "executor": False, "risk_guard": True, "reason": f"future_web3_registry_error:{exc}"})
        return self.registry

    def get_route(self, network: str) -> Dict[str, Any]:
        return self.refresh().get(str(network or "").lower(), {})

    def route_opportunity(self, network: str, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        registry = self.refresh()
        network = str(network or "").lower()
        node = registry.get(network)
        if not node:
            return {"allowed": False, "reason": "unsupported network", "network": network}
        if node.get("status") != "LIVE_READY":
            return {"allowed": False, "reason": "network blocked", "network": network}
        if not node.get("balance_reader") or not node.get("risk_guard"):
            return {"allowed": False, "reason": "gates missing", "network": network}
        if network == "base" and not node.get("executor"):
            return {"allowed": False, "reason": str(node.get("reason") or "base_blocked"), "network": network}
        if network == "future_web3" and not node.get("executor"):
            return {"allowed": False, "reason": str(node.get("reason") or "future_web3_blocked"), "network": network}
        if network == "solana" and not node.get("swap_executor"):
            return {"allowed": False, "reason": "swap_executor_disabled", "network": network}
        if network == "polymarket" and not node.get("executor"):
            return {"allowed": False, "reason": "executor_disabled", "network": network}
        return {"allowed": True, "reason": "route ready", "network": network, "opportunity": opportunity}

    def get_summary(self) -> Dict[str, Any]:
        return {"registry": self.refresh(), "reconciliation_blocked": self._reconciliation_blocked(), "treasury_state": self._load_treasury_state()}
