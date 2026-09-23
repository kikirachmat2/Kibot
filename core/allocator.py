"""Module: core.allocator — Fixed-ratio buy allocation. No multiplier, no regime."""
from typing import Dict


def allocate(topup_amount_idr: float) -> Dict[str, float]:
    """Split a topup amount 70% BTC / 30% ETH. No conditions, no exceptions."""
    if topup_amount_idr <= 0:
        return {"BTC": 0.0, "ETH": 0.0}
    return {
        "BTC": round(0.70 * topup_amount_idr, 2),
        "ETH": round(0.30 * topup_amount_idr, 2),
    }
