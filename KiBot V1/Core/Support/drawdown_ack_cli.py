"""Drawdown Acknowledgement CLI helper — invoked via `bin/kibotctl drawdown-ack --reason "..."`."""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from Core.Support.ki_config import STATE_DIR
from Core.Treasury.capital_governor import get_capital_governor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
WIB_TZ = timezone(timedelta(hours=7))


def main():
    parser = argparse.ArgumentParser(
        description="Acknowledge and reset the KiBot Overall Drawdown Circuit Breaker."
    )
    parser.add_argument(
        "--reason",
        "-r",
        required=True,
        help="Mandatory operator explanation for acknowledging the drawdown and resuming trading.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Acknowledge even if breaker is not currently tripped (e.g. to rebase peak equity).",
    )

    args = parser.parse_args()
    reason = (args.reason or "").strip()

    if not reason:
        print("❌ Error: --reason must not be empty. Operator justification is strictly required.")
        sys.exit(1)

    gov = get_capital_governor()
    peak_before = float(getattr(gov, "peak_total_equity_idr", 0.0) or 0.0)
    current_equity = float(getattr(gov, "current_total_equity_idr", 0.0) or 0.0)
    drawdown_pct_before = float(getattr(gov, "overall_drawdown_pct", 0.0) or 0.0)
    breaker_tripped = bool(getattr(gov, "circuit_breaker_tripped", False))

    if not breaker_tripped and not args.force:
        print(f"ℹ️ Overall Drawdown Circuit Breaker is NOT currently tripped (status: {gov.status}, drawdown: {drawdown_pct_before:.2f}%).")
        print("   If you intentionally want to rebase the High-Water Mark peak to current equity, use --force.")
        sys.exit(0)

    # Perform acknowledgement in CapitalGovernor
    result = gov.acknowledge_drawdown_breaker(reason=reason)

    # Write persistent audit log
    audit_dir = STATE_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / "drawdown_ack_audit.jsonl"

    audit_entry = {
        "event": "OVERALL_DRAWDOWN_BREAKER_ACK",
        "timestamp_wib": datetime.now(WIB_TZ).isoformat(),
        "ts": time.time(),
        "operator_reason": reason,
        "peak_before_idr": peak_before,
        "current_equity_idr": current_equity,
        "drawdown_pct_before": drawdown_pct_before,
        "new_peak_idr": result.get("new_peak_idr", current_equity),
        "new_status": result.get("new_status", "RECONCILED"),
    }

    try:
        with open(audit_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(audit_entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️ Warning: Could not write to audit log {audit_file}: {e}")

    print("\n========================================================================================")
    print("                OVERALL DRAWDOWN CIRCUIT BREAKER ACKNOWLEDGED")
    print("========================================================================================")
    print(f"   Timestamp         : {audit_entry['timestamp_wib']}")
    print(f"   Peak Before       : Rp{peak_before:,.2f}")
    print(f"   Current Equity    : Rp{current_equity:,.2f}")
    print(f"   Drawdown Before   : {drawdown_pct_before:.2f}%")
    print(f"   New Peak Baseline : Rp{result.get('new_peak_idr', current_equity):,.2f}")
    print(f"   Governor Status   : {result.get('new_status', 'RECONCILED')}")
    print(f"   Operator Reason   : \"{reason}\"")
    print(f"   Audit Log         : {audit_file}")
    print("========================================================================================")
    print("✅ Circuit Breaker unlocked. Orders permitted once daily risk parameters pass.\n")


if __name__ == "__main__":
    main()
