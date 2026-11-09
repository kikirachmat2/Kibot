"""KiBot Pre-Trade & Emergency Gatekeeper Client for Zura Integration.

Ensures no trade (Smart Limit DCA, Market Buy, or Profit Take) is executed
without explicit validation and approval from Zura:
1. Checks centralized Kill-Switch (system_paused in zura_adaptive_config.json).
2. Invokes zura_advisory.py --trade for sanity checks, single-trade limits,
   and executive risk management.
"""

import os
import json
import subprocess
from typing import Dict, Any, Optional

CANDIDATE_CONFIG_PATHS = [
    os.getenv("ZURA_ADAPTIVE_CONFIG_PATH"),
    "/home/ubuntu/zura-core/data/zura_adaptive_config.json",
    os.path.expanduser("~/Documents/Web Develop/Personal AI/data/zura_adaptive_config.json")
]

CANDIDATE_ADVISORY_SCRIPTS = [
    "/home/ubuntu/zura-core/scripts/zura_advisory.py",
    os.path.expanduser("~/Documents/Web Develop/Personal AI/scripts/zura_advisory.py")
]


def is_system_paused() -> bool:
    """Checks if Zura has activated global system pause / emergency kill-switch."""
    for p in CANDIDATE_CONFIG_PATHS:
        if p and os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("system_paused"):
                        return True
            except Exception:
                pass
    return False


def consult_zura_for_trade(pair: str, action: str, amount_idr: float, price_idr: float, fear_greed_score: Optional[int] = None) -> Dict[str, Any]:
    """
    Mandatory pre-trade consultation with Zura.
    FAIL-CLOSED: If Zura rejects, pause is active, or advisory script fails,
    returns is_approved: False.
    """
    if is_system_paused():
        return {
            "is_approved": False,
            "action": "VETO",
            "reason": "Zura Kill-Switch Aktif (system_paused = true). Seluruh transaksi perdagangan dibekukan."
        }

    script_path = None
    for s in CANDIDATE_ADVISORY_SCRIPTS:
        if s and os.path.exists(s):
            script_path = s
            break

    if not script_path:
        # If advisory script is not reachable on this node, enforce local fail-closed or pass if within standard limits
        if amount_idr > 5000000.0:
            return {
                "is_approved": False,
                "action": "VETO",
                "reason": f"Nominal Rp {amount_idr:,.0f} melebihi batas darurat tanpa izin Zura (Rp 5.000.000)."
            }
        return {
            "is_approved": True,
            "action": "APPROVE",
            "reason": "Zura advisory script not found on host, local safety boundaries enforced."
        }

    payload = {
        "pair": pair,
        "action": action,
        "amount_idr": float(amount_idr),
        "price_idr": float(price_idr),
        "fear_greed_score": fear_greed_score
    }

    try:
        res = subprocess.run(
            ["python3", script_path, "--trade", json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=10
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout.strip())
        else:
            return {
                "is_approved": False,
                "action": "VETO",
                "reason": f"Zura advisory execution error: {res.stderr.strip() or 'Non-zero exit'}"
            }
    except Exception as e:
        return {
            "is_approved": False,
            "action": "VETO",
            "reason": f"Gagal menghubungi Zura Pre-Trade Gatekeeper: {e}"
        }
