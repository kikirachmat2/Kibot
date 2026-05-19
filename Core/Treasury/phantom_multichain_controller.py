import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("PhantomMultichainController")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PHANTOM_TREASURY_FILE = STATE_DIR / "phantom_treasury.json"
PHANTOM_RECONCILIATION_FILE = STATE_DIR / "TREASURY_RECONCILIATION_REQUIRED"


class PhantomMultichainController:
    """
    Sovereign multichain router for Phantom capital.
    Scouting is allowed on all supported chains, execution only on live-ready routes.
    """

    def __init__(self):
        self.registry: Dict[str, Dict[str, Any]] = {
            "solana": {
                "status": "SCOUTING",
                "balance_reader": True,
                "opportunity_scanner": True,
                "swap_executor": True,
                "risk_guard": True,
            },
            "base": {
                "status": "SCOUTING",
                "balance_reader": True,
                "opportunity_scanner": False,
                "swap_executor": False,
                "risk_guard": True,
            },
            "polymarket": {
                "status": "SCOUTING",
                "balance_reader": True,
                "opportunity_scanner": True,
                "executor": True,
                "risk_guard": True,
            },
            "future_web3": {
                "status": "SCOUTING",
                "balance_reader": False,
                "executor": False,
                "risk_guard": True,
            },
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

    def refresh(self) -> Dict[str, Dict[str, Any]]:
        treasury = self._load_treasury_state()
        blocked = self._reconciliation_blocked()
        base_status = "BLOCKED" if blocked else "LIVE_READY"
        solana_status = "BLOCKED" if blocked else "LIVE_READY"
        poly_status = "BLOCKED" if blocked else "LIVE_READY"

        self.registry["base"]["status"] = base_status
        self.registry["solana"]["status"] = solana_status
        self.registry["polymarket"]["status"] = poly_status
        self.registry["future_web3"]["status"] = "SCOUTING"

        self.registry["base"]["balance_reader"] = bool(treasury.get("chains", {}).get("base", {}).get("rpc_ok"))
        self.registry["solana"]["balance_reader"] = True
        self.registry["polymarket"]["balance_reader"] = True
        return self.registry

    def route_opportunity(self, network: str, opportunity: Dict[str, Any]) -> Dict[str, Any]:
        registry = self.refresh()
        network = str(network or "").lower()
        node = registry.get(network)
        if not node:
            return {"allowed": False, "reason": "unsupported network", "network": network}

        if node.get("status") != "LIVE_READY":
            return {"allowed": False, "reason": "network blocked", "network": network}

        if not node.get("balance_reader"):
            return {"allowed": False, "reason": "balance reader missing", "network": network}

        if not node.get("risk_guard"):
            return {"allowed": False, "reason": "risk guard missing", "network": network}

        route_kind = "executor" if network in {"polymarket", "future_web3"} else "swap_executor"
        if not node.get(route_kind):
            return {"allowed": False, "reason": "executor unsupported", "network": network}

        return {
            "allowed": True,
            "reason": "route ready",
            "network": network,
            "opportunity": opportunity,
        }

    def get_summary(self) -> Dict[str, Any]:
        return {
            "registry": self.refresh(),
            "reconciliation_blocked": self._reconciliation_blocked(),
            "treasury_state": self._load_treasury_state(),
        }
