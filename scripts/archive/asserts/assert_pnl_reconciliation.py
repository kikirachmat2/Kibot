#!/usr/bin/env python3
from __future__ import annotations

import sys

from Core.Treasury.pnl_reconciliation import reconcile_pnl_state


def main() -> int:
    state = reconcile_pnl_state(write=True)
    discrepancies = state.get("discrepancies", [])
    high = [d for d in discrepancies if d.get("severity") == "HIGH"]
    final = state.get("final_order_permission", {})
    canonical = state.get("canonical", {})

    if high:
        print("ASSERT_PNL_RECONCILIATION_BLOCKED")
        for item in high:
            print(f"- {item.get('type')}: {item}")
        if canonical.get("hard_stop") and not final.get("allow_new_orders", True):
            print("hard_stop_enforced=true")
            return 0
        return 1

    if canonical.get("hard_stop") and final.get("allow_new_orders", False):
        print("ASSERT_PNL_RECONCILIATION_FAILED: hard stop is true but final orders are allowed")
        return 1

    print("ASSERT_PNL_RECONCILIATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
