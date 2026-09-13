"""Withdrawal Notification CLI helper — invoked via `bin/kibotctl withdraw-notify <amount_idr> [note]`."""

import sys
import logging
from Core.Treasury.deposit_event_manager import get_deposit_manager
from Core.Treasury.capital_governor import get_capital_governor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    if len(sys.argv) < 2:
        print("Usage: kibotctl withdraw-notify <amount_idr> [note]")
        print("Example: bin/kibotctl withdraw-notify 250000 'Withdraw profit to bank'")
        sys.exit(1)

    try:
        amount_idr = float(sys.argv[1])
    except ValueError:
        print(f"Error: Invalid amount '{sys.argv[1]}'. Must be a positive number.")
        sys.exit(1)

    note = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Operator manual withdrawal"

    mgr = get_deposit_manager()
    event = mgr.record_withdrawal(amount_idr=amount_idr, note=note)

    import asyncio
    gov = get_capital_governor()
    try:
        asyncio.run(gov.reconcile_governor())
    except Exception:
        gov._load_governor_state()

    print(f"✅ Withdrawal notification recorded successfully!")
    print(f"   Event ID   : {event['event_id']}")
    print(f"   Amount IDR : Rp{amount_idr:,.2f}")
    print(f"   Note       : {event['note']}")
    allow_orders = gov.status not in ("HALTED", "DRAWDOWN_HALT", "OVERALL_DRAWDOWN_BREAKER_TRIPPED")
    print(f"   Governor Status : {gov.status} (Allow orders: {allow_orders})")


if __name__ == "__main__":
    main()
