#!/usr/bin/env python3
"""Trace today's Indodax-only equity and PnL source.

This diagnostic intentionally ignores retired wallet and cross-venue state. The
canonical money truth for KiBot is now the Indodax account plus any Indodax
open-position mark-to-market value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "state"


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(str(value).replace(",", "").strip() or default)
    except Exception:
        return default


def wib_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


@dataclass
class Row:
    source: str
    current_value_idr: float
    start_value_idr: float
    change_idr: float
    type: str
    note: str = ""


def load_sources() -> Dict[str, Any]:
    return {
        "live_truth": read_json(STATE / "live_truth.json", {}),
        "capital_governor": read_json(STATE / "capital_governor.json", {}),
        "daily_anchor": read_json(STATE / "daily_equity_anchor.json", {}),
        "telemetry_snapshot": read_json(STATE / "telemetry_snapshot.json", {}),
        "active_trades": read_json(STATE / "active_trades.json", {}),
    }


def build_reconciliation(data: Dict[str, Any]) -> Tuple[List[Row], Dict[str, Any]]:
    truth: Dict[str, Any] = data["live_truth"] if isinstance(data.get("live_truth"), dict) else {}
    gov: Dict[str, Any] = data["capital_governor"] if isinstance(data.get("capital_governor"), dict) else {}
    anchor: Dict[str, Any] = data["daily_anchor"] if isinstance(data.get("daily_anchor"), dict) else {}
    telemetry: Dict[str, Any] = data["telemetry_snapshot"] if isinstance(data.get("telemetry_snapshot"), dict) else {}
    raw_portfolio = telemetry.get("portfolio")
    portfolio: Dict[str, Any] = raw_portfolio if isinstance(raw_portfolio, dict) else {}

    cash = safe_float(
        truth.get("cash_idr"),
        safe_float(portfolio.get("idr_cash"), safe_float(portfolio.get("cash_idr"))),
    )
    held_coin = safe_float(
        truth.get("held_coin_value_idr"),
        safe_float(portfolio.get("coin_holdings_idr"), safe_float(portfolio.get("held_coin_value_idr"))),
    )
    total_equity = safe_float(
        truth.get("total_equity_idr"),
        safe_float(gov.get("current_total_equity_idr"), cash + held_coin),
    )
    start_equity = safe_float(
        truth.get("starting_equity_today_idr"),
        safe_float(gov.get("start_total_equity_idr"), safe_float(anchor.get("start_equity_idr"))),
    )
    realized = safe_float(truth.get("realized_pnl_today_idr"), safe_float(gov.get("realized_pnl_today_idr")))
    unrealized = safe_float(truth.get("unrealized_pnl_idr"), safe_float(portfolio.get("unrealized_pnl_idr")))
    fees = safe_float(truth.get("fees_today_idr"), safe_float(gov.get("fees_today_idr")))
    net_pnl = safe_float(truth.get("net_pnl_today_idr"), total_equity - start_equity)

    rows = [
        Row("Indodax cash", cash, cash, 0.0, "balance", "live cash"),
        Row("Indodax held coins", held_coin, 0.0, held_coin, "mark-to-market", "repriced holdings"),
        Row("Realized trading PnL", realized, 0.0, realized, "realized_pnl", "filled exits"),
        Row("Unrealized open PnL", unrealized, 0.0, unrealized, "unrealized_pnl", "open positions"),
        Row("Fees today", fees, 0.0, fees, "cost", "netted from PnL"),
    ]

    meta = {
        "source_selected": "live_truth" if truth else "capital_governor_or_telemetry",
        "classification": "INDODAX_ONLY_EQUITY_TRACE",
        "current_equity_idr": total_equity,
        "start_equity_idr": start_equity,
        "net_pnl_today_idr": net_pnl,
        "realized_pnl_idr": realized,
        "unrealized_pnl_idr": unrealized,
        "fees_today_idr": fees,
        "open_positions_count": len(truth.get("open_positions") or []),
        "generated_at": wib_now(),
    }
    return rows, meta


def main() -> int:
    rows, meta = build_reconciliation(load_sources())
    print("BEGIN_EQUITY_SOURCE_TRACE_REPORT")
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    print("\n| Source | Current Value IDR | Start Value IDR | Change | Type | Note |")
    print("|---|---:|---:|---:|---|---|")
    for row in rows:
        print(
            f"| {row.source} | {row.current_value_idr:,.2f} | {row.start_value_idr:,.2f} | "
            f"{row.change_idr:,.2f} | {row.type} | {row.note} |"
        )
    print("END_EQUITY_SOURCE_TRACE_REPORT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
