import logging
from typing import Dict, Any

logger = logging.getLogger("AllocationPolicy")

class AllocationPolicy:
    """
    Sovereign Allocation Policy for the Indodax-only runtime.
    """
    def __init__(self):
        pass

    def compute_targets(self, _removed_wallet_balance_idr: float = 0.0) -> Dict[str, float]:
        """
        Returns target percentages for active venues only.
        """
        return {"indodax": 0.85, "reserve": 0.15}
