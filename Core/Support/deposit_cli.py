"""Deposit Notification CLI helper — invoked via `bin/kibotctl deposit-notify <amount_idr> [note]`."""

import sys
import logging
from Core.Treasury.deposit_event_manager import get_deposit_manager
from Core.Treasury.capital_governor import get_capital_governor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    if len(sys.argv) < 2:
        print("Usage: kibotctl deposit-notify <amount_idr> [note]")
        print("Example: bin/kibotctl deposit-notify 500000 'Top up Indodax balance'")
        sys.exit(1)

    try:
        amount_idr = float(sys.argv[1])
    except ValueError:
        print(f"Error: Invalid amount '{sys.argv[1]}'. Must be a positive number.")
        sys.exit(1)

    note = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Operator manual top-up"

    mgr = get_deposit_manager()
    event = mgr.record_deposit(amount_idr=amount_idr, note=note)

    # Immediately trigger CapitalGovernor reconciliation
    gov = get_capital_governor()
    gov.evaluate()

    print(f"✅ Deposit notification recorded successfully!")
    print(f"   Event ID   : {event['event_id']}")
    print(f"   Amount IDR : Rp{amount_idr:,.2f}")
    print(f"   Note       : {event['note']}")
    print(f"   Governor Status : {gov.status} (Allow orders: {gov.allow_new_orders})")


if __name__ == "__main__":
    main()
