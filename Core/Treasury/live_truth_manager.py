from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR
from Core.Support.runtime_mode_guard import LIVE_ONLY, assert_runtime_live_only

LIVE_TRUTH_FILE = STATE_DIR / "live_truth.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _today_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def build_live_truth() -> Dict[str, Any]:
    assert_runtime_live_only()
    governor = _read_json(STATE_DIR / "capital_governor.json", {})
    portfolio = _read_json(STATE_DIR / "portfolio_summary.json", {})
    phantom = _read_json(STATE_DIR / "phantom_treasury.json", {})
    active_trades = _read_json(STATE_DIR / "active_trades.json", {})
    order_tracker = _read_json(STATE_DIR / "orders" / "_index.json", {})
    pnl_recon = _read_json(STATE_DIR / "pnl_reconciliation.json", {})

    indodax_equity = _safe_float(
        (governor.get("venues", {}) or {}).get("indodax", {}).get("equity_idr"),
        _safe_float(portfolio.get("equity_idr"), 0.0),
    )
    phantom_equity = _safe_float(
        (governor.get("venues", {}) or {}).get("phantom", {}).get("equity_idr"),
        _safe_float(phantom.get("total_value_idr"), 0.0),
    )
    wallet_equity = indodax_equity + phantom_equity
    cash_idr = _safe_float(portfolio.get("idr_cash"), 0.0)
    realized = _safe_float(governor.get("daily_pnl_idr"), _safe_float(portfolio.get("realized_pnl_idr"), 0.0))
    unrealized = _safe_float(portfolio.get("unrealized_pnl_idr"), 0.0)
    fees = _safe_float(_read_json(STATE_DIR / "trade_fees_today.json", {}).get("total_fee_idr"), 0.0)
    net = realized + unrealized - fees

    open_positions: List[Dict[str, Any]] = []
    dust_positions: List[Dict[str, Any]] = []
    if isinstance(active_trades, dict):
        for pair, trade in active_trades.items():
            if not isinstance(trade, dict):
                continue
            amount = _safe_float(trade.get("amount") or trade.get("coin_amount") or trade.get("size"), 0.0)
            entry_price = _safe_float(trade.get("price") or trade.get("entry_price") or trade.get("fill_price"), 0.0)
            value_idr = amount * entry_price if amount > 0 and entry_price > 0 else _safe_float(trade.get("value_idr"), 0.0)
            entry = {
                "pair": pair,
                "amount": amount,
                "entry_price": entry_price,
                "value_idr": value_idr,
                "status": str(trade.get("status") or trade.get("state") or "OPEN"),
                "reason": str(trade.get("reason") or trade.get("exit_blocked_reason") or ""),
            }
            if value_idr > 0 and value_idr < 10000:
                dust_positions.append(entry)
            else:
                open_positions.append(entry)

    indodax_status = str((governor.get("venues", {}) or {}).get("indodax", {}).get("status") or "OK").upper()
    phantom_status = str((governor.get("venues", {}) or {}).get("phantom", {}).get("status") or "OK").upper()
    if indodax_status in {"BLOCKED_WITH_REASON", "DOWN", "ERROR", "LOCKED"} and phantom_status in {"BLOCKED_WITH_REASON", "DOWN", "ERROR", "LOCKED"}:
        risk_state = "EMERGENCY"
    elif indodax_status in {"BLOCKED_WITH_REASON", "DOWN", "ERROR", "LOCKED"} or phantom_status in {"BLOCKED_WITH_REASON", "DOWN", "ERROR", "LOCKED"}:
        risk_state = "LOCKED"
    else:
        risk_state = "OK"

    gov_status = str(governor.get("status") or "").upper()
    if gov_status == "BLOCKED_WITH_REASON":
        risk_state = "LOCKED"
    elif _safe_float(governor.get("daily_pnl_idr"), 0.0) < 0:
        risk_state = "CAUTION"

    payload = {
        "runtime_mode": "LIVE_ONLY",
        "updated_at": _today_iso(),
        "wallet_equity_idr": wallet_equity,
        "cash_idr": cash_idr,
        "total_equity_idr": wallet_equity,
        "indodax": {
            "enabled": True,
            "status": indodax_status,
            "equity_idr": indodax_equity,
            "cash_idr": cash_idr,
            "open_positions": open_positions,
            "last_error": None,
        },
        "phantom": {
            "enabled": True,
            "status": phantom_status,
            "equity_idr": phantom_equity,
            "sol_balance": _safe_float((phantom.get("balances") or {}).get("sol"), 0.0) if isinstance(phantom, dict) else 0.0,
            "open_positions": _read_json(STATE_DIR / "phantom_positions.json", []),
            "last_error": None,
        },
        "indodax_equity_idr": indodax_equity,
        "phantom_equity_idr": phantom_equity,
        "realized_pnl_today_idr": realized,
        "unrealized_pnl_idr": unrealized,
        "fees_today_idr": fees,
        "net_pnl_today_idr": net,
        "open_positions": open_positions,
        "dust_positions": dust_positions,
        "blocked_pairs": _read_json(STATE_DIR / "pair_quarantine.json", {}).get("blocked_pairs", []),
        "risk_state": risk_state,
        "venue_locks": {
            "indodax": indodax_status,
            "phantom": phantom_status,
        },
        "last_trade": _read_json(STATE_DIR / "last_trade.json", {}),
        "last_error": _read_json(STATE_DIR / "last_error.json", {}).get("error"),
        "last_exception": _read_json(STATE_DIR / "last_error.json", {}).get("error"),
        "sources": {
            "capital_governor": governor,
            "pnl_reconciliation": pnl_recon,
            "orders_index": order_tracker,
        },
    }
    try:
        LIVE_TRUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        LIVE_TRUTH_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    except Exception:
        pass
    return payload


def load_live_truth() -> Dict[str, Any]:
    return _read_json(LIVE_TRUTH_FILE, {})


@dataclass
class LiveTruthManager:
    notifier: Any | None = None

    async def refresh(self) -> Dict[str, Any]:
        return build_live_truth()

    async def build_and_write(self) -> Dict[str, Any]:
        return build_live_truth()

    async def write_live_truth(self) -> Dict[str, Any]:
        return build_live_truth()
