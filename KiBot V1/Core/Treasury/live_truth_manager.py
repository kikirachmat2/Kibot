from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Support.ki_config import KiConfig, STATE_DIR
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


def _today_wib() -> str:
    return datetime.now(timezone(timedelta(hours=7))).date().isoformat()


def _dict_get(payload: Dict[str, Any], *path: str, default: Any = None) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return default if node is None else node


def _position_value_idr(trade: Dict[str, Any]) -> float:
    amount = _safe_float(trade.get("amount") or trade.get("coin_amount") or trade.get("size"), 0.0)
    explicit = _safe_float(trade.get("value_idr") or trade.get("current_value_idr") or trade.get("market_value_idr"), 0.0)
    if explicit > 0.0:
        return explicit
    price = _safe_float(
        trade.get("mark_price")
        or trade.get("current_price")
        or trade.get("last_price")
        or trade.get("price")
        or trade.get("entry_price")
        or trade.get("fill_price"),
        0.0,
    )
    return amount * price if amount > 0.0 and price > 0.0 else 0.0


def _is_dust_trade(trade: Dict[str, Any], value_idr: float) -> bool:
    reason_blob = " ".join(
        str(trade.get(key) or "")
        for key in ("exit_blocked_reason", "partial_tp_blocked_reason", "reason", "status", "state")
    ).upper()
    if "EXIT_MINIMUM_NOT_MET" in reason_blob or "PARTIAL_EXIT_MINIMUM_NOT_MET" in reason_blob:
        return True
    if "DUST" in reason_blob or "RESIDUAL" in reason_blob or "UNSELLABLE" in reason_blob:
        return True
    return 0.0 < value_idr < 10_000.0


def _trade_history_summary_today() -> Dict[str, Any]:
    try:
        from Core.Intelligence.trade_history import summarize_today

        summary = summarize_today(limit=5000)
        return summary if isinstance(summary, dict) else {}
    except Exception:
        return {}


def _fees_today_idr() -> float:
    explicit = _safe_float(_read_json(STATE_DIR / "trade_fees_today.json", {}).get("total_fee_idr"), 0.0)
    if explicit > 0.0:
        return explicit
    summary_fee = _safe_float(_trade_history_summary_today().get("fee_paid_idr"), 0.0)
    if summary_fee > 0.0:
        return summary_fee

    # Last resort: scan today's normalized trade journal directly. This keeps
    # the live truth useful even if the summary helper is not warm yet.
    history_file = STATE_DIR / "trade_history" / f"{_today_wib()}.jsonl"
    total = 0.0
    if not history_file.exists():
        return 0.0
    try:
        seen: set[str] = set()
        for line in history_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            fee = _safe_float(row.get("fee_idr") or row.get("fee"), 0.0)
            if fee <= 0.0:
                continue
            key = str(row.get("order_id") or row.get("exchange_order_id") or row.get("ts") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            total += fee
    except Exception:
        return 0.0
    return round(total, 8)


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def build_live_truth() -> Dict[str, Any]:
    assert_runtime_live_only()
    governor = _read_json(STATE_DIR / "capital_governor.json", {})
    portfolio = _read_json(STATE_DIR / "portfolio_summary.json", {})
    active_trades = _read_json(STATE_DIR / "active_trades.json", {})
    order_tracker = _read_json(STATE_DIR / "orders" / "_index.json", {})
    pnl_recon = _read_json(STATE_DIR / "pnl_reconciliation.json", {})

    indodax_venue = _dict_get(governor, "venues", "indodax", default={})
    indodax_venue = indodax_venue if isinstance(indodax_venue, dict) else {}
    indodax_equity = _safe_float(
        indodax_venue.get("equity_idr"),
        _safe_float(governor.get("current_total_equity_idr"), _safe_float(portfolio.get("equity_idr"), 0.0)),
    )
    wallet_equity = indodax_equity
    explicit_cash_present = "idr_cash" in portfolio or "cash_idr" in portfolio
    portfolio_cash = _safe_float(portfolio.get("idr_cash"), _safe_float(portfolio.get("cash_idr"), 0.0))
    open_buy_reserve = _safe_float(governor.get("open_buy_order_reserve_idr"), _safe_float(indodax_venue.get("open_buy_order_reserve_idr"), 0.0))
    portfolio_coin_holdings = _safe_float(portfolio.get("coin_holdings_idr"), 0.0)
    equity_daily_pnl = _safe_float(governor.get("daily_pnl_idr"), _safe_float(portfolio.get("daily_pnl_idr"), 0.0))
    trade_summary = _trade_history_summary_today()
    trade_realized = _safe_float(trade_summary.get("realized_pnl_idr"), 0.0)
    realized = trade_realized if _safe_float(trade_summary.get("sell_fills"), 0.0) > 0 else equity_daily_pnl
    fees = _fees_today_idr()

    open_positions: List[Dict[str, Any]] = []
    dust_positions: List[Dict[str, Any]] = []
    active_mark_value = 0.0
    dust_value_idr = 0.0
    if isinstance(active_trades, dict):
        for pair, trade in active_trades.items():
            if not isinstance(trade, dict):
                continue
            amount = _safe_float(trade.get("amount") or trade.get("coin_amount") or trade.get("size"), 0.0)
            entry_price = _safe_float(trade.get("price") or trade.get("entry_price") or trade.get("fill_price"), 0.0)
            value_idr = _position_value_idr(trade)
            is_dust = _is_dust_trade(trade, value_idr)
            entry = {
                "pair": pair,
                "amount": amount,
                "entry_price": entry_price,
                "value_idr": value_idr,
                "status": "DUST_UNSELLABLE" if is_dust else str(trade.get("status") or trade.get("state") or "OPEN"),
                "reason": str(trade.get("reason") or trade.get("exit_blocked_reason") or ""),
            }
            if is_dust:
                dust_value_idr += max(0.0, value_idr)
                dust_positions.append(entry)
            else:
                active_mark_value += max(0.0, value_idr)
                open_positions.append(entry)

    held_coin_value_idr = portfolio_coin_holdings if portfolio_coin_holdings > 0.0 else active_mark_value + dust_value_idr
    inferred_cash = max(0.0, indodax_equity - held_coin_value_idr - open_buy_reserve)
    cash_idr = portfolio_cash if explicit_cash_present and portfolio_cash > 0.0 else inferred_cash
    cash_source = "portfolio_summary" if explicit_cash_present and portfolio_cash > 0.0 else "capital_governor_inferred"
    unrealized = _safe_float(portfolio.get("unrealized_pnl_idr"), 0.0)
    if unrealized == 0.0 and open_positions and trade_realized:
        unrealized = equity_daily_pnl - trade_realized
    # CapitalGovernor PnL is already equity-based and therefore already includes
    # fees/spread/slippage effects. Fees are displayed as a cost breakdown, not
    # subtracted a second time from the canonical net PnL.
    net = equity_daily_pnl

    indodax_status = str((governor.get("venues", {}) or {}).get("indodax", {}).get("status") or "OK").upper()
    if indodax_status in {"BLOCKED_WITH_REASON", "DOWN", "ERROR", "LOCKED"}:
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
        "platform_mode": "INDODAX_ONLY" if KiConfig.INDODAX_ONLY else "MULTI_VENUE",
        "updated_at": _today_iso(),
        "wallet_equity_idr": wallet_equity,
        "cash_idr": cash_idr,
        "liquid_cash_idr": cash_idr,
        "coin_holdings_idr": held_coin_value_idr,
        "held_coin_value_idr": held_coin_value_idr,
        "open_buy_order_reserve_idr": open_buy_reserve,
        "dust_value_idr": dust_value_idr,
        "total_equity_idr": wallet_equity,
        "indodax": {
            "enabled": True,
            "status": indodax_status,
            "equity_idr": indodax_equity,
            "cash_idr": cash_idr,
            "liquid_cash_idr": cash_idr,
            "held_coin_value_idr": held_coin_value_idr,
            "open_buy_order_reserve_idr": open_buy_reserve,
            "dust_value_idr": dust_value_idr,
            "open_positions": open_positions,
            "last_error": None,
        },
        "indodax_equity_idr": indodax_equity,
        "realized_pnl_today_idr": realized,
        "unrealized_pnl_idr": unrealized,
        "fees_today_idr": fees,
        "fee_paid_today_idr": fees,
        "net_pnl_today_idr": net,
        "open_positions": open_positions,
        "dust_positions": dust_positions,
        "blocked_pairs": _read_json(STATE_DIR / "pair_quarantine.json", {}).get("blocked_pairs", []),
        "risk_state": risk_state,
        "venue_locks": {
            "indodax": indodax_status,
        },
        "last_trade": _read_json(STATE_DIR / "last_trade.json", {}),
        "last_error": _read_json(STATE_DIR / "last_error.json", {}).get("error"),
        "last_exception": _read_json(STATE_DIR / "last_error.json", {}).get("error"),
        "accounting_breakdown": {
            "cash_source": cash_source,
            "portfolio_cash_idr": portfolio_cash,
            "inferred_cash_idr": inferred_cash,
            "indodax_equity_idr": indodax_equity,
            "held_coin_value_idr": held_coin_value_idr,
            "open_buy_order_reserve_idr": open_buy_reserve,
            "dust_value_idr": dust_value_idr,
            "equity_daily_pnl_idr": equity_daily_pnl,
            "trade_realized_pnl_idr": trade_realized,
            "fees_are_breakdown_not_double_subtracted": True,
        },
        "sources": {
            "capital_governor": governor,
            "pnl_reconciliation": pnl_recon,
            "orders_index": order_tracker,
        },
    }
    try:
        _atomic_write_json(LIVE_TRUTH_FILE, payload)
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
