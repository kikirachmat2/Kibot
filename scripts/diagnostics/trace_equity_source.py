#!/usr/bin/env python3
"""
Trace the source of today's equity / PnL movement.

This utility is intentionally conservative:
- it prefers the consolidated Capital Governor ledger when fresh
- it classifies changes into realized PnL, unrealized PnL, balance reconciliation,
  internal transfers, and dashboard mismatch
- it does not invent profit from stale or mixed-mode ledgers
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
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
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def short(addr: str, keep: int = 6) -> str:
    if not addr:
        return ""
    addr = str(addr)
    if len(addr) <= keep * 2 + 3:
        return addr
    return f"{addr[:keep]}...{addr[-keep:]}"


def wib_now() -> str:
    # Keep this script self-contained; timezone formatting is not critical here.
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
        "capital_governor": read_json(STATE / "capital_governor.json", {}),
        "daily_anchor": read_json(STATE / "daily_equity_anchor.json", {}),
        "venue_ledger": read_json(STATE / "venue_ledger.json", {}),
        "phantom_treasury": read_json(STATE / "phantom_treasury.json", {}),
        "base_executor_state": read_json(STATE / "base_executor_state.json", {}),
        "base_positions": read_json(STATE / "base_positions.json", []),
        "future_web3_registry": read_json(STATE / "future_web3_registry.json", {}),
        "pumpfun_positions": read_json(STATE / "pumpfun_positions.json", []),
        "web3_positions": read_json(STATE / "web3_positions.json", []),
        "active_trades": read_json(STATE / "active_trades.json", {}),
        "autonomous_sizing": read_json(STATE / "autonomous_sizing.json", {}),
        "control_plane": read_json(STATE / "control_plane.json", {}),
        "telemetry_snapshot": read_json(STATE / "telemetry_snapshot.json", {}),
    }


def parse_active_positions(telemetry: Dict[str, Any]) -> List[Dict[str, Any]]:
    portfolio = telemetry.get("portfolio") if isinstance(telemetry, dict) else {}
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    return portfolio.get("active_positions") if isinstance(portfolio.get("active_positions"), list) else []


def build_reconciliation(data: Dict[str, Any]) -> Tuple[List[Row], Dict[str, Any]]:
    gov = data["capital_governor"] if isinstance(data["capital_governor"], dict) else {}
    anchor = data["daily_anchor"] if isinstance(data["daily_anchor"], dict) else {}
    venue = data["venue_ledger"] if isinstance(data["venue_ledger"], dict) else {}
    pt = data["phantom_treasury"] if isinstance(data["phantom_treasury"], dict) else {}
    telemetry = data["telemetry_snapshot"] if isinstance(data["telemetry_snapshot"], dict) else {}
    active_trades = data["active_trades"] if isinstance(data["active_trades"], dict) else {}

    indodax_cash = safe_float((telemetry.get("portfolio") or {}).get("idr_cash"), safe_float((telemetry.get("portfolio") or {}).get("equity_idr")))
    indodax_coin = safe_float((telemetry.get("portfolio") or {}).get("coin_holdings_idr"), 0.0)
    indodax_equity = indodax_cash + indodax_coin

    phantom_value = safe_float(pt.get("total_value_idr"), 0.0)
    phantom_solana = safe_float(pt.get("sol_balance"), 0.0) * 0.0
    phantom_base = safe_float(pt.get("base_idrx_balance"), 0.0)
    phantom_ui_warning = str(pt.get("reconciliation", {}).get("reason") or "")

    poly = (telemetry.get("portfolio") or {}).get("polymarket") if isinstance(telemetry.get("portfolio"), dict) else {}
    poly_value = safe_float((poly or {}).get("equity_idr"), 0.0)

    # Position ledgers
    realized_pnl = safe_float((gov or {}).get("daily_pnl_idr"), 0.0)
    unrealized_pnl = safe_float((telemetry.get("portfolio") or {}).get("unrealized_pnl_idr"), 0.0)
    open_positions = parse_active_positions(telemetry)
    open_trade_pnl = safe_float((telemetry.get("portfolio") or {}).get("unrealized_pnl_idr"), 0.0)

    # Venue ledger values are often legacy / shadow; preserve them for audit only.
    rows = [
        Row("Indodax cash", indodax_cash, indodax_cash, 0.0, "balance", "live cash"),
        Row("Indodax coin holdings", indodax_coin, 0.0, indodax_coin, "mark-to-market", "repriced holdings"),
        Row("Phantom IDRX / treasury", phantom_value, safe_float(anchor.get("start_equity_idr"), 0.0), phantom_value - safe_float(anchor.get("start_equity_idr"), 0.0), "balance_reconciliation", phantom_ui_warning or "phantom treasury"),
        Row("Phantom SOL", phantom_solana, 0.0, phantom_solana, "balance", "solana leg"),
        Row("Polymarket", poly_value, 0.0, poly_value, "position/realized", "usdc bucket"),
        Row("Realized trading PnL", realized_pnl, 0.0, realized_pnl, "realized_pnl", "capital governor"),
        Row("Unrealized open PnL", unrealized_pnl, 0.0, unrealized_pnl, "unrealized_pnl", "open positions"),
        Row("Internal transfer", 0.0, 0.0, 0.0, "internal_transfer", "exclude from pnl"),
    ]

    # Strictly compute the consolidated truth from current visible components.
    current_equity = indodax_equity + phantom_value + poly_value
    start_equity = safe_float(gov.get("start_total_equity_idr"), safe_float(anchor.get("start_equity_idr"), 0.0))
    gov_daily = safe_float(gov.get("daily_pnl_idr"), 0.0)
    dashboard_pnl = current_equity - start_equity

    # Determine mismatch / classification.
    if gov and gov.get("status") == "RECONCILED" and safe_float(gov.get("current_total_equity_idr"), 0.0) > 0:
        source = "capital_governor"
        verified_daily = gov_daily
    else:
        source = "dashboard_recompute"
        verified_daily = dashboard_pnl

    classification = "PNL_MISMATCH_NEEDS_FIX"
    if verified_daily > 0 and abs(verified_daily - realized_pnl) < 1e-6 and abs(unrealized_pnl) < 1e-6:
        classification = "PNL_VERIFIED_REALIZED_PROFIT"
    elif verified_daily > 0 and abs(verified_daily - dashboard_pnl) < 1e-6 and unrealized_pnl != 0:
        classification = "PNL_VERIFIED_UNREALIZED_MARK_TO_MARKET"
    elif abs(verified_daily) < 1e-6 and (
        "internal transfer" in (pt.get("reconciliation", {}) or {}).get("reason", "").lower()
        or abs(safe_float(pt.get("base_idrx_balance"), 0.0)) > 0
    ):
        classification = "PNL_FROM_BALANCE_RECONCILIATION_NOT_TRADING_PROFIT"

    meta = {
        "source_selected": source,
        "classification": classification,
        "current_equity_idr": current_equity,
        "start_equity_idr": start_equity,
        "dashboard_pnl_idr": dashboard_pnl,
        "capital_governor_daily_pnl_idr": gov_daily,
        "realized_pnl_idr": realized_pnl,
        "unrealized_pnl_idr": unrealized_pnl,
        "open_positions_count": len(open_positions),
        "phantom_warning": phantom_ui_warning,
        "wallet_match": bool((pt.get("reconciliation") or {}).get("matches_user_wallet")),
        "phantom_address": short(str(pt.get("address") or pt.get("evm_address") or "")),
        "evm_address": short(str(pt.get("evm_address") or "")),
        "solana_address": short(str(pt.get("chains", {}).get("solana", {}).get("address") or "")),
        "generated_at": wib_now(),
        "venue_ledger_has_legacy_modes": any(
            str((v or {}).get("mode", "")).upper() in {"PAPER", "SIMULATION", "SHADOW"}
            for v in (venue.values() if isinstance(venue, dict) else [])
            if isinstance(v, dict)
        ),
    }
    return rows, meta


def main() -> int:
    data = load_sources()
    rows, meta = build_reconciliation(data)
    print("BEGIN_EQUITY_SOURCE_TRACE_REPORT")
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    print("\n| Source | Current Value IDR | Start Value IDR | Change | Type | Note |")
    print("|---|---:|---:|---:|---|---|")
    for r in rows:
        print(
            f"| {r.source} | {r.current_value_idr:,.2f} | {r.start_value_idr:,.2f} | {r.change_idr:,.2f} | {r.type} | {r.note} |"
        )
    print("END_EQUITY_SOURCE_TRACE_REPORT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
