import logging
from typing import Dict, Any

logger = logging.getLogger("AllocationPolicy")

class AllocationPolicy:
    """
    Sovereign Allocation Policy
    Applies rules to determine how capital should be partitioned among venues:
    - Phantom Balance = 0: Indodax 80%, Phantom 0%, Reserve 20%
    - Phantom Balance > 0: Indodax 60%, Phantom 25%, Reserve 15%
    """
    def __init__(self):
        pass

    def compute_targets(self, phantom_balance_idr: float) -> Dict[str, float]:
        """
        Computes targets based on absolute Phantom wallet balance in IDR.
        Returns percentage targets for each venue.
        """
        if phantom_balance_idr <= 0.0:
            return {
                "indodax": 0.80,
                "phantom": 0.00,
                "reserve": 0.20
            }
        else:
            return {
                "indodax": 0.60,
                "phantom": 0.25,
                "reserve": 0.15
            }
