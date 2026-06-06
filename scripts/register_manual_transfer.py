#!/usr/bin/env python3
import os
import sys
import json
import argparse
from datetime import datetime
import pytz

def get_today_wib():
    wib = pytz.timezone('Asia/Jakarta')
    return datetime.now(wib).strftime('%Y-%m-%d')

def main():
    parser = argparse.ArgumentParser(description="Register manual treasury transfers for KiBot.")
    parser.add_argument("--date", help="Date of transfer (YYYY-MM-DD), default is today WIB", default=None)
    parser.add_argument("--type", choices=["deposit", "withdrawal", "internal"], required=True, help="Type of transfer")
    parser.add_argument("--amount", type=float, required=True, help="Amount in IDR")
    parser.add_argument("--description", required=True, help="Short description of the transfer")
    parser.add_argument("--from-venue", help="Source venue (e.g. indodax, bank)")
    parser.add_argument("--to-venue", help="Destination venue (e.g. indodax, bank)")

    args = parser.parse_args()

    date_str = args.date if args.date else get_today_wib()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print(f"❌ Error: Invalid date format '{date_str}'. Must be YYYY-MM-DD.")
        sys.exit(1)

    transfer_record = {
        "date": date_str,
        "timestamp": datetime.now(pytz.timezone('Asia/Jakarta')).isoformat(),
        "type": args.type,
        "amount_idr": args.amount,
        "description": args.description,
        "from_venue": args.from_venue or "unknown",
        "to_venue": args.to_venue or "unknown"
    }

    # Locate/create state directory
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state_dir = os.path.join(base_dir, "state")
    os.makedirs(state_dir, exist_ok=True)
    transfers_file = os.path.join(state_dir, "treasury_transfers.jsonl")

    try:
        with open(transfers_file, "a") as f:
            f.write(json.dumps(transfer_record) + "\n")
        print(f"✅ Successfully registered {args.type} of Rp{args.amount:,.2f} on {date_str}.")
        print(f"📝 Record: {json.dumps(transfer_record)}")
    except Exception as e:
        print(f"❌ Failed to write to {transfers_file}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
