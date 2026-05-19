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
            "base": {"status": "SCOUTING", "balance_reader": True, "opportunity_scanner": True, "swap_executor": False, "risk_guard": True},
            "polymarket": {"status": "SCOUTING", "balance_reader": True, "opportunity_scanner": True, "executor": True, "risk_guard": True},
            "future_web3": {"status": "SCOUTING", "balance_reader": False, "opportunity_scanner": True, "swap_executor": False, "executor": False, "risk_guard": True},
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
        base["status"] = "BLOCKED" if blocked else "SCOUTING"
        base["balance_reader"] = bool(treasury.get("chains", {}).get("base", {}).get("rpc_ok"))
        base["swap_executor"] = False
        base["executor"] = False

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

        self.registry["future_web3"].update({"status": "SCOUTING", "balance_reader": False, "swap_executor": False, "executor": False, "risk_guard": True})
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
        if network == "base":
            return {"allowed": False, "reason": "base_executor_missing", "network": network}
        if network == "future_web3":
            return {"allowed": False, "reason": "future_web3_scout_only", "network": network}
        if network == "solana" and not node.get("swap_executor"):
            return {"allowed": False, "reason": "swap_executor_disabled", "network": network}
        if network == "polymarket" and not node.get("executor"):
            return {"allowed": False, "reason": "executor_disabled", "network": network}
        return {"allowed": True, "reason": "route ready", "network": network, "opportunity": opportunity}

    def get_summary(self) -> Dict[str, Any]:
        return {"registry": self.refresh(), "reconciliation_blocked": self._reconciliation_blocked(), "treasury_state": self._load_treasury_state()}
