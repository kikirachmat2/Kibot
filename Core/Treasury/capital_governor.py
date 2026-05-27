import logging
import json
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from Core.Support.ki_config import WIB, KiConfig
from Core.Treasury.venue_ledger import VenueLedger
from Core.Treasury.phantom_treasury import PhantomTreasury
from Core.Treasury.allocation_policy import AllocationPolicy

logger = logging.getLogger("CapitalGovernor")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
GOVERNOR_FILE = STATE_DIR / "capital_governor.json"
ANCHOR_FILE = STATE_DIR / "daily_equity_anchor.json"

def _today_wib() -> str:
    """Business day boundary follows WIB."""
    return str(datetime.now(WIB).date())


def _safe_json_load(path: Path) -> Dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.debug("Failed to load %s: %s", path, exc)
    return {}


def _count_live_inventory_entries(payload: Any) -> int:
    """Best-effort count of open inventory entries in generic position payloads."""
    terminal_states = {"CLOSED", "FILLED", "RECONCILED", "CANCELLED", "FAILED", "DONE"}
    if payload is None:
        return 0
    if isinstance(payload, list):
        total = 0
        for item in payload:
            if isinstance(item, dict):
                if _is_residual_inventory_entry(item):
                    continue
                state = str(item.get("status") or item.get("state") or "").upper()
                amount = 0.0
                for key in ("amount", "size", "quantity", "coin_amount", "position_size"):
                    try:
                        amount = float(item.get(key) or 0.0)
                    except Exception:
                        amount = 0.0
                    if amount > 0:
                        break
                if state in terminal_states:
                    continue
                if amount > 0 or state or item.get("pair") or item.get("symbol") or item.get("market"):
                    total += 1
            elif item not in (None, "", 0, 0.0, False):
                total += 1
        return total
    if isinstance(payload, dict):
        total = 0
        for key in ("open_positions", "positions", "active_positions", "active_trades", "open_orders"):
            value = payload.get(key)
            if isinstance(value, (list, dict)):
                total += _count_live_inventory_entries(value)
        if total > 0:
            return total
        state = str(payload.get("status") or payload.get("state") or "").upper()
        amount = 0.0
        for key in ("amount", "size", "quantity", "coin_amount", "position_size"):
            try:
                amount = float(payload.get(key) or 0.0)
            except Exception:
                amount = 0.0
            if amount > 0:
                break
        if _is_residual_inventory_entry(payload):
            return 0
        if state and state not in terminal_states and (amount > 0 or payload.get("pair") or payload.get("symbol") or payload.get("market")):
            return 1
        return 0
    return 0


def _inventory_notional_idr(payload: Any) -> float:
    """Best-effort estimate of position notional in IDR."""
    if not isinstance(payload, dict):
        return 0.0
    amount = 0.0
    for key in ("amount", "coin_amount", "size", "quantity", "position_size"):
        try:
            amount = float(payload.get(key) or 0.0)
        except Exception:
            amount = 0.0
        if amount > 0:
            break
    price = 0.0
    for key in ("price", "fill_price", "entry_price_idr", "last_price", "mark_price", "current_price"):
        try:
            price = float(payload.get(key) or 0.0)
        except Exception:
            price = 0.0
        if price > 0:
            break
    if amount > 0 and price > 0:
        return amount * price
    for key in ("cost", "budget_idr", "notional_idr", "value_idr", "exit_value_idr"):
        try:
            value = float(payload.get(key) or 0.0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _is_residual_inventory_entry(payload: Any, *, min_notional_idr: float = 10_000.0) -> bool:
    """
    Identify tiny unsellable residuals that should not block the daily reset.

    These are usually dust balances or legacy wallet leftovers that sit below
    the exchange minimum exit notional. They still belong in the audit trail,
    but they should not keep the system pinned in EXIT_ALL forever.
    """
    if not isinstance(payload, dict):
        return False
    reason_blob = " ".join(
        str(payload.get(key) or "")
        for key in ("exit_blocked_reason", "partial_tp_blocked_reason", "reason", "status", "state")
    ).upper()
    if "EXIT_MINIMUM_NOT_MET" in reason_blob or "PARTIAL_EXIT_MINIMUM_NOT_MET" in reason_blob:
        return True
    if "DUST" in reason_blob or "RESIDUAL" in reason_blob or "UNSELLABLE" in reason_blob:
        return True
    notional = _inventory_notional_idr(payload)
    return 0.0 < notional < float(min_notional_idr)


def _pending_buy_order_reserve_idr(state_dir: Optional[Path] = None) -> float:
    """
    Estimate IDR reserved by open BUY orders that have not settled yet.

    This is added back into consolidated equity so the total balance stays
    stable while limit entries are working through the exchange.
    """
    base_dir = state_dir or STATE_DIR
    reserve = 0.0
    seen_keys: set[str] = set()

    def _to_float(value: Any) -> float:
        try:
            if value in (None, "", "None", "nan"):
                return 0.0
            return float(value)
        except Exception:
            return 0.0

    def _register(key: str, value: float) -> None:
        nonlocal reserve
        if value <= 0.0:
            return
        key = str(key or "").strip()
        if key and key in seen_keys:
            return
        if key:
            seen_keys.add(key)
        reserve += float(value)

    active_trades_file = base_dir / "active_trades.json"
    if active_trades_file.exists():
        try:
            active_trades = json.loads(active_trades_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed to load active_trades.json for reserve estimate: %s", exc)
            active_trades = {}
        if isinstance(active_trades, dict):
            for symbol, trade in active_trades.items():
                if not isinstance(trade, dict):
                    continue
                pending_marker = any(
                    bool(trade.get(key))
                    for key in (
                        "entry_pending_order_id",
                        "entry_pending_exchange_order_id",
                        "entry_pending_status",
                        "entry_pending_since",
                    )
                )
                if not pending_marker:
                    continue
                state = str(trade.get("entry_pending_status") or trade.get("status") or trade.get("state") or "").upper().strip()
                if state in {"CANCELLED", "FAILED", "FILLED", "RECONCILED"}:
                    continue
                budget = _to_float(
                    trade.get("entry_pending_budget_idr")
                    or trade.get("budget_idr")
                    or trade.get("cost")
                    or trade.get("notional_idr"),
                )
                if budget <= 0.0:
                    continue
                reserve_key = next(
                    (
                        str(trade.get(field) or "").strip()
                        for field in (
                            "entry_pending_order_id",
                            "entry_pending_exchange_order_id",
                            "sovereign_order_id",
                        )
                        if str(trade.get(field) or "").strip()
                    ),
                    f"BUY_RESERVE:{str(symbol).upper()}:{budget:.2f}",
                )
                _register(reserve_key, budget)

    orders_dir = base_dir / "orders"
    index_file = orders_dir / "_index.json"
    if index_file.exists():
        try:
            index_data = json.loads(index_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Failed to load order index for reserve estimate: %s", exc)
            index_data = {}
        open_ids = index_data.get("open", []) if isinstance(index_data, dict) else []
        if isinstance(open_ids, list):
            for order_id in open_ids:
                if not order_id:
                    continue
                order_file = orders_dir / f"{order_id}.json"
                if not order_file.exists():
                    continue
                try:
                    order = json.loads(order_file.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.debug("Failed to load order %s for reserve estimate: %s", order_id, exc)
                    continue
                if not isinstance(order, dict):
                    continue
                side = str(order.get("side") or order.get("type") or "").upper().strip()
                state = str(order.get("state") or "").upper().strip()
                if side != "BUY" or state in {"FILLED", "RECONCILED", "CANCELLED", "FAILED"}:
                    continue
                budget = _to_float(order.get("budget_idr") or order.get("amount_idr") or order.get("notional_idr"))
                if budget <= 0.0:
                    continue
                if state == "PARTIAL_FILL":
                    fill_price = _to_float(order.get("fill_price"))
                    coin_amount = _to_float(order.get("coin_amount"))
                    if fill_price > 0.0 and coin_amount > 0.0:
                        budget = max(0.0, budget - (fill_price * coin_amount))
                reserve_key = next(
                    (
                        str(order.get(field) or "").strip()
                        for field in ("exchange_order_id", "order_id")
                        if str(order.get(field) or "").strip()
                    ),
                    f"BUY_RESERVE:{str(order.get('pair') or '').upper()}:{budget:.2f}",
                )
                _register(reserve_key, budget)

    return round(reserve, 8)


def load_daily_inventory_snapshot(state_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return a conservative snapshot of live inventory that still needs flattening."""
    base_dir = state_dir or STATE_DIR
    repo_state_dir = (Path.cwd() / "state").resolve()
    snapshot: Dict[str, Any] = {
        "has_open_inventory": False,
        "open_count": 0,
        "open_symbols": [],
        "residual_count": 0,
        "residual_symbols": [],
        "locked_count": 0,
        "locked_symbols": [],
        "locked_sources": {},
        "open_sources": {},
        "errors": [],
    }
    open_symbol_set: set[str] = set()
    locked_symbol_set: set[str] = set()

    def _mark_open(source: str, count: int, symbols: Optional[list[str]] = None) -> None:
        if count <= 0:
            return
        snapshot["has_open_inventory"] = True
        snapshot["open_sources"][source] = int(count)
        if symbols:
            added = 0
            for raw_symbol in symbols:
                symbol = str(raw_symbol or "").upper().strip()
                if not symbol or symbol in open_symbol_set:
                    continue
                open_symbol_set.add(symbol)
                snapshot["open_symbols"].append(symbol)
                added += 1
            snapshot["open_count"] += added
        else:
            snapshot["open_count"] += int(count)

    def _mark_locked(source: str, count: int, symbols: Optional[list[str]] = None) -> None:
        if count <= 0:
            return
        snapshot["locked_sources"][source] = int(count)
        if symbols:
            added = 0
            for raw_symbol in symbols:
                symbol = str(raw_symbol or "").upper().strip()
                if not symbol or symbol in locked_symbol_set:
                    continue
                locked_symbol_set.add(symbol)
                snapshot["locked_symbols"].append(symbol)
                added += 1
            snapshot["locked_count"] += added
        else:
            snapshot["locked_count"] += int(count)

    def _is_externally_locked_inventory(trade: Dict[str, Any]) -> bool:
        reason = str(trade.get("exit_blocked_reason") or trade.get("reason") or "").upper()
        route_status = str(trade.get("route_status") or "").upper()
        return route_status == "BLOCKED_WITH_REASON" and any(
            marker in reason
            for marker in (
                "EXIT_ROUTE_TEMPORARILY_UNAVAILABLE",
                "PAIR_UNAVAILABLE",
                "MAINTENANCE",
                "SUSPENDED",
            )
        )

    active_trades_file = base_dir / "active_trades.json"
    if active_trades_file.exists():
        try:
            active_trades = json.loads(active_trades_file.read_text(encoding="utf-8"))
        except Exception as exc:
            snapshot["errors"].append(f"active_trades.json:{exc}")
            snapshot["has_open_inventory"] = True
        else:
            if isinstance(active_trades, dict):
                symbols: list[str] = []
                count = 0
                residual_symbols: list[str] = []
                residual_count = 0
                for symbol, trade in active_trades.items():
                    if not isinstance(trade, dict):
                        continue
                    if _is_residual_inventory_entry(trade):
                        residual_count += 1
                        residual_symbols.append(str(symbol).upper())
                        continue
                    if _is_externally_locked_inventory(trade):
                        _mark_locked("active_trades", 1, [str(symbol).upper()])
                        continue
                    pending = any(
                        bool(trade.get(key))
                        for key in (
                            "entry_pending_order_id",
                            "entry_pending_exchange_order_id",
                            "exit_pending_order_id",
                            "exit_pending_exchange_order_id",
                        )
                    )
                    amount = 0.0
                    for key in ("amount", "coin_amount", "size", "quantity"):
                        try:
                            amount = float(trade.get(key) or 0.0)
                        except Exception:
                            amount = 0.0
                        if amount > 0:
                            break
                    if amount > 0 or pending:
                        count += 1
                        symbols.append(str(symbol).upper())
                _mark_open("active_trades", count, symbols)
                if residual_count:
                    snapshot["residual_count"] += residual_count
                    snapshot["residual_symbols"].extend(residual_symbols)
            elif active_trades not in ({}, []):
                snapshot["has_open_inventory"] = True
                snapshot["errors"].append("active_trades.json:unexpected_format")

    # Only consult the live order tracker when we are looking at the canonical
    # repo state directory. Tests and isolated maintenance flows may point the
    # governor at a temp state dir, and in that case we must not leak live Batam
    # inventory into the isolated snapshot.
    try:
        if base_dir.resolve().is_relative_to(repo_state_dir):
            from Core.Intelligence.order_tracker import get_tracker

            tracker = get_tracker()
            open_orders = tracker.get_open_orders()
            order_symbols: list[str] = []
            for order in open_orders:
                if not isinstance(order, dict):
                    continue
                pair = str(order.get("pair") or order.get("symbol") or "").upper().strip()
                if pair:
                    order_symbols.append(pair)
            _mark_open("order_tracker", len(order_symbols), order_symbols)
    except Exception as exc:
        # Missing tracker information should keep the reset in pending mode so
        # we never reset the day while inventory might still be live.
        snapshot["errors"].append(f"order_tracker:{exc}")
        snapshot["has_open_inventory"] = True

    for position_file in sorted(base_dir.glob("*positions*.json")):
        try:
            payload = json.loads(position_file.read_text(encoding="utf-8"))
        except Exception as exc:
            snapshot["errors"].append(f"{position_file.name}:{exc}")
            snapshot["has_open_inventory"] = True
            continue
        count = _count_live_inventory_entries(payload)
        if count > 0:
            symbols: list[str] = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        if _is_residual_inventory_entry(item):
                            residual_symbol = str(item.get("pair") or item.get("symbol") or item.get("market") or "").upper().strip()
                            if residual_symbol:
                                snapshot["residual_symbols"].append(residual_symbol)
                            snapshot["residual_count"] += 1
                            continue
                        pair = str(item.get("pair") or item.get("symbol") or item.get("market") or "").upper().strip()
                        if pair:
                            symbols.append(pair)
            elif isinstance(payload, dict):
                for key in ("open_positions", "positions", "active_positions"):
                    value = payload.get(key)
                    if isinstance(value, list):
                        for item in value:
                            if isinstance(item, dict):
                                if _is_residual_inventory_entry(item):
                                    residual_symbol = str(item.get("pair") or item.get("symbol") or item.get("market") or "").upper().strip()
                                    if residual_symbol:
                                        snapshot["residual_symbols"].append(residual_symbol)
                                    snapshot["residual_count"] += 1
                                    continue
                                pair = str(item.get("pair") or item.get("symbol") or item.get("market") or "").upper().strip()
                                if pair:
                                    symbols.append(pair)
            _mark_open(position_file.name, count, symbols)

    snapshot["open_symbols"] = sorted({symbol for symbol in snapshot["open_symbols"] if symbol})
    snapshot["residual_symbols"] = sorted({symbol for symbol in snapshot["residual_symbols"] if symbol})
    snapshot["locked_symbols"] = sorted({symbol for symbol in snapshot["locked_symbols"] if symbol})
    if snapshot["open_symbols"]:
        snapshot["open_count"] = len(snapshot["open_symbols"])
    else:
        snapshot["open_count"] = int(snapshot["open_count"])
    snapshot["residual_count"] = int(snapshot["residual_count"])
    snapshot["locked_count"] = int(snapshot["locked_count"])
    return snapshot


def _load_daily_reset_state(state_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Read the daily reset coordinator state if it exists."""
    base_dir = state_dir or STATE_DIR
    path = base_dir / "daily_reset_state.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}

class CapitalGovernor:
    """
    Sovereign Capital Governor
    =========================
    The central coordinator of KiBot's capital distribution, target allocations,
    and the global 1.5% daily drawdown cap.
    """
    def __init__(self, indodax_gateway=None, phantom_router=None):
        self.indodax = indodax_gateway
        self.phantom_router = phantom_router
        
        # Initialize internal modules
        self.ledger = VenueLedger()
        self.phantom_treasury = PhantomTreasury(phantom_router)
        self.policy = AllocationPolicy()
        
        # Core metrics
        self.start_total_equity_idr = 0.0
        self.max_daily_loss_idr = 0.0
        self.current_total_equity_idr = 0.0
        self.daily_pnl_idr = 0.0
        self.daily_pnl_pct = 0.0
        self.trading_pnl_idr = 0.0
        self.trading_pnl_pct = 0.0
        self.start_indodax_equity_idr = 0.0
        self.start_phantom_equity_idr = 0.0
        self.indodax_daily_pnl_idr = 0.0
        self.indodax_daily_pnl_pct = 0.0
        self.phantom_daily_pnl_idr = 0.0
        self.phantom_daily_pnl_pct = 0.0
        self.external_deposits_today = 0.0
        self.external_withdrawals_today = 0.0
        self.reset_deposits_offset = 0.0
        self.reset_withdrawals_offset = 0.0
        self.status = "UNRECONCILED"
        self.last_reset_date = _today_wib()
        self.pending_daily_reset = False
        self.daily_reset_reason = ""
        
        self._load_governor_state()

    def _load_daily_anchor(self) -> Dict[str, Any]:
        """Return today's daily equity anchor. The anchor is the PnL baseline source of truth."""
        if not ANCHOR_FILE.exists():
            return {}
        try:
            data = json.loads(ANCHOR_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"❌ Failed to load daily equity anchor: {e}")
            return {}
        if data.get("date") != _today_wib():
            return {}
        return data if isinstance(data, dict) else {}

    def _write_daily_anchor(self) -> None:
        """Keep the healthcheck anchor aligned with the governor baseline."""
        if self.start_total_equity_idr <= 0.0:
            return
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            ANCHOR_FILE.write_text(json.dumps({
                "date": self.last_reset_date,
                "start_equity_idr": self.start_total_equity_idr,
                "max_daily_loss_pct": KiConfig.MAX_DAILY_LOSS_PERCENT,
                "max_daily_loss_idr": self.max_daily_loss_idr,
                "source": "capital_governor",
            }, indent=4), encoding="utf-8")
        except Exception as e:
            logger.error(f"❌ Failed to write daily equity anchor: {e}")

    def _load_governor_state(self):
        self.status = "UNRECONCILED"
        if GOVERNOR_FILE.exists():
            try:
                with open(GOVERNOR_FILE, "r") as f:
                    data = json.load(f)
                    today = _today_wib()
                    stored_date = str(data.get("date") or "").strip()
                    self.last_reset_date = stored_date or today
                    self.start_total_equity_idr = float(data.get("start_total_equity_idr", 0.0))
                    self.max_daily_loss_idr = float(data.get("max_daily_loss_idr", 0.0))
                    self.status = data.get("status", "UNRECONCILED")
                    self.daily_pnl_idr = float(data.get("daily_pnl_idr", 0.0))
                    self.daily_pnl_pct = float(data.get("daily_pnl_pct", 0.0))
                    self.trading_pnl_idr = float(data.get("trading_pnl_idr", self.daily_pnl_idr))
                    self.trading_pnl_pct = float(data.get("trading_pnl_pct", self.daily_pnl_pct))
                    self.start_indodax_equity_idr = float(data.get("start_indodax_equity_idr", 0.0))
                    self.start_phantom_equity_idr = float(data.get("start_phantom_equity_idr", 0.0))
                    self.indodax_daily_pnl_idr = float(data.get("indodax_daily_pnl_idr", 0.0))
                    self.indodax_daily_pnl_pct = float(data.get("indodax_daily_pnl_pct", 0.0))
                    self.phantom_daily_pnl_idr = float(data.get("phantom_daily_pnl_idr", 0.0))
                    self.phantom_daily_pnl_pct = float(data.get("phantom_daily_pnl_pct", 0.0))
                    self.external_deposits_today = float(data.get("external_deposits_today", 0.0))
                    self.external_withdrawals_today = float(data.get("external_withdrawals_today", 0.0))
                    self.reset_deposits_offset = float(data.get("reset_deposits_offset", 0.0))
                    self.reset_withdrawals_offset = float(data.get("reset_withdrawals_offset", 0.0))
                    self.pending_daily_reset = bool(data.get("daily_reset_pending", False)) or (stored_date not in {"", today})
                    self.daily_reset_reason = str(
                        data.get("daily_reset_reason")
                        or (
                            f"daily_rollover_exit_pending ({stored_date or 'unknown'} -> {today})"
                            if self.pending_daily_reset
                            else ""
                        )
                    ).strip()
            except Exception as e:
                logger.error(f"❌ Failed to load Capital Governor state: {e}")
        else:
            self.last_reset_date = _today_wib()

        anchor = self._load_daily_anchor()
        anchor_equity = float(anchor.get("start_equity_idr", 0.0) or 0.0)
        if anchor_equity > 0.0:
            # The healthcheck anchor is the canonical daily baseline. If the
            # governor file drifted, trust the anchor and force one PnL source.
            self.start_total_equity_idr = anchor_equity
            self.max_daily_loss_idr = float(
                anchor.get("max_daily_loss_idr", anchor_equity * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)) or 0.0
            )
            self.last_reset_date = str(anchor.get("date") or _today_wib())

    def save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            global_hard_stop = bool(self.max_daily_loss_idr > 0.0 and self.daily_pnl_idr <= -self.max_daily_loss_idr)
            daily_reset_block = bool(getattr(self, "pending_daily_reset", False))
            allow_new_orders = bool(getattr(self, "allow_new_orders", False)) and not global_hard_stop and not daily_reset_block
            base_reason = str(getattr(self, "allow_new_orders_reason", ""))
            venues_snapshot = getattr(self, "venue_states", {}) if isinstance(getattr(self, "venue_states", {}), dict) else {}
            indodax_snapshot = venues_snapshot.get("indodax", {}) if isinstance(venues_snapshot.get("indodax", {}), dict) else {}
            phantom_snapshot = venues_snapshot.get("phantom", {}) if isinstance(venues_snapshot.get("phantom", {}), dict) else {}
            allow_indodax_orders = bool(indodax_snapshot.get("allow_orders", allow_new_orders))
            allow_phantom_orders = bool(phantom_snapshot.get("allow_orders", allow_new_orders))
            reasons = [reason for reason in [
                base_reason,
                (
                    f"global_daily_loss_cap_breached ({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                    if global_hard_stop else ""
                ),
                (self.daily_reset_reason or "daily_rollover_exit_pending") if daily_reset_block else "",
            ] if reason]
            allow_reason = "; ".join(dict.fromkeys(reasons))
            status = "BLOCKED_WITH_REASON" if (global_hard_stop or daily_reset_block) else self.status
            with open(GOVERNOR_FILE, "w") as f:
                json.dump({
                    "date": self.last_reset_date,
                    "start_total_equity_idr": self.start_total_equity_idr,
                    "reset_total_balance_idr": self.start_total_equity_idr,
                    "max_daily_loss_pct": KiConfig.MAX_DAILY_LOSS_PERCENT,
                    "max_daily_loss_idr": self.max_daily_loss_idr,
                    "current_total_equity_idr": self.current_total_equity_idr,
                    "total_balance_idr": self.current_total_equity_idr,
                    "daily_pnl_idr": self.daily_pnl_idr,
                    "combined_pnl_idr": self.daily_pnl_idr,
                    "daily_return_idr": self.daily_pnl_idr,
                    "daily_pnl_pct": self.daily_pnl_pct,
                    "daily_return_pct": self.daily_pnl_pct,
                    "trading_pnl_idr": self.trading_pnl_idr,
                    "trading_pnl_pct": self.trading_pnl_pct,
                    "start_indodax_equity_idr": self.start_indodax_equity_idr,
                    "start_phantom_equity_idr": self.start_phantom_equity_idr,
                    "indodax_daily_pnl_idr": self.indodax_daily_pnl_idr,
                    "indodax_daily_pnl_pct": self.indodax_daily_pnl_pct,
                    "phantom_daily_pnl_idr": self.phantom_daily_pnl_idr,
                    "phantom_daily_pnl_pct": self.phantom_daily_pnl_pct,
                    "external_deposits_today": self.external_deposits_today,
                    "external_withdrawals_today": self.external_withdrawals_today,
                    "reset_deposits_offset": self.reset_deposits_offset,
                    "reset_withdrawals_offset": self.reset_withdrawals_offset,
                    "daily_reset_pending": daily_reset_block,
                    "daily_reset_reason": self.daily_reset_reason if daily_reset_block else "",
                    "locked_inventory_count": int(getattr(self, "locked_inventory_count", 0) or 0),
                    "locked_inventory_symbols": list(getattr(self, "locked_inventory_symbols", []) or []),
                    "status": status,
                    "global_hard_stop": global_hard_stop,
                    "allow_new_orders": allow_new_orders,
                    "allow_new_orders_reason": allow_reason,
                    "allow_indodax_orders": allow_indodax_orders,
                    "allow_phantom_orders": allow_phantom_orders,
                    "venues": venues_snapshot,
                    "targets": getattr(self, "targets_snapshot", {}),
                    "phantom_details": getattr(self, "phantom_details_snapshot", {}),
                }, f, indent=4)
            self._write_daily_anchor()
        except Exception as e:
            logger.error(f"❌ Failed to save Capital Governor state: {e}")

    def _read_daily_transfers(self, date_str: str) -> tuple[float, float]:
        """Read state/treasury_transfers.jsonl and sum external deposits and withdrawals for the given date."""
        transfers_file = STATE_DIR / "treasury_transfers.jsonl"
        deposits = 0.0
        withdrawals = 0.0
        if not transfers_file.exists():
            return 0.0, 0.0
        try:
            with open(transfers_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        tx = json.loads(line)
                        if tx.get("date") == date_str:
                            txtype = tx.get("type", "").strip().lower()
                            amount = float(tx.get("amount_idr", 0.0))
                            if txtype == "deposit":
                                deposits += amount
                            elif txtype == "withdrawal":
                                withdrawals += amount
                    except Exception as e:
                        logger.error(f"Error parsing transfer line: {e}")
        except Exception as e:
            logger.error(f"Error reading treasury_transfers.jsonl: {e}")
        return deposits, withdrawals

    def _read_in_flight_transfers(self, date_str: str, phantom_equity_idr: float) -> float:
        """
        Read state/treasury_transfers.jsonl and calculate the total in-flight internal transfer amount
        destined for Phantom that is not yet reflected in its balance.
        """
        transfers_file = STATE_DIR / "treasury_transfers.jsonl"
        in_flight = 0.0
        if not transfers_file.exists():
            return 0.0
        try:
            with open(transfers_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        tx = json.loads(line)
                        if tx.get("date") == date_str:
                            txtype = tx.get("type", "").strip().lower()
                            if txtype == "internal":
                                to_venue = tx.get("to_venue", "").strip().lower()
                                amount = float(tx.get("amount_idr", 0.0))
                                if to_venue == "phantom":
                                    # If the on-chain phantom balance is less than this transfer amount,
                                    # the difference is considered in-flight (in-transit).
                                    if phantom_equity_idr < amount:
                                        in_flight += (amount - phantom_equity_idr)
                    except Exception as e:
                        logger.error(f"Error parsing transfer line: {e}")
        except Exception as e:
            logger.error(f"Error reading treasury_transfers.jsonl: {e}")
        return in_flight

    async def _read_indodax_coin_holdings_from_active_trades(self) -> float:
        """
        Fallback for equity reconciliation when the exchange balance endpoint
        does not expose held coins consistently in the governor process.
        Uses open Indodax positions + live tickers to estimate mark-to-market.
        """
        if os.getenv("KIBOT_GOVERNOR_ACTIVE_TRADES_FALLBACK", "0").strip().lower() not in {"1", "true", "yes", "on"}:
            return 0.0
        active_trades_file = STATE_DIR / "active_trades.json"
        if not active_trades_file.exists():
            return 0.0
        try:
            with open(active_trades_file, "r") as f:
                active_trades = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load active_trades.json for governor fallback: {e}")
            return 0.0

        if not isinstance(active_trades, dict):
            return 0.0

        holdings_value = 0.0
        try:
            for symbol, trade in active_trades.items():
                if not isinstance(trade, dict):
                    continue
                pair = str(symbol or "").lower().replace("/", "_")
                if "_" not in pair:
                    pair = f"{pair}_idr"
                coin = pair.split("_", 1)[0]
                amount = float(trade.get("amount", 0.0) or 0.0)
                if amount <= 0:
                    continue
                try:
                    ticker = await asyncio.wait_for(self.indodax.get_ticker(pair), timeout=5)
                    if not isinstance(ticker, dict):
                        continue
                    price = float(ticker.get("last", 0.0) or 0.0)
                except Exception:
                    price = float(trade.get("price", 0.0) or 0.0)
                if price > 0:
                    holdings_value += amount * price
        except Exception as e:
            logger.error(f"Failed to compute active trade holdings fallback: {e}")
            return 0.0
        return holdings_value


    async def check_daily_reset(self, total_equity_idr: float):
        """Reset starting total equity anchor if a new WIB day has begun."""
        today = _today_wib()
        inventory = load_daily_inventory_snapshot()
        self.locked_inventory_count = int(inventory.get("locked_count", 0) or 0)
        self.locked_inventory_symbols = list(inventory.get("locked_symbols", []) or [])
        day_changed = self.last_reset_date != today
        pending_reset = bool(getattr(self, "pending_daily_reset", False))
        today_anchor = self._load_daily_anchor()
        anchor_equity = float(today_anchor.get("start_equity_idr", 0.0) or 0.0)

        if today_anchor and anchor_equity > 0.0:
            # The daily anchor is intentionally immutable for one WIB date.
            # Pending rollover can delay trading, but it must never rewrite
            # today's starting balance after inventory finally clears.
            self.last_reset_date = today
            self.start_total_equity_idr = anchor_equity
            self.max_daily_loss_idr = float(
                today_anchor.get(
                    "max_daily_loss_idr",
                    anchor_equity * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0),
                )
                or 0.0
            )
            if pending_reset and not inventory.get("has_open_inventory"):
                self.pending_daily_reset = False
                self.daily_reset_reason = ""
                self.status = "RECONCILED"
                self.allow_new_orders = True
                self.allow_new_orders_reason = ""
                self.save()
                logger.info(
                    "⚓ Daily anchor preserved for %s at Rp%,.2f; cleared pending rollover without resetting baseline.",
                    today,
                    self.start_total_equity_idr,
                )
            return

        if day_changed or pending_reset or self.start_total_equity_idr <= 0.0:
            if inventory.get("has_open_inventory"):
                self.pending_daily_reset = True
                open_count = int(inventory.get("open_count", 0) or 0)
                symbols = ", ".join(inventory.get("open_symbols", [])[:10]) or "unknown"
                sources = ", ".join(sorted(inventory.get("open_sources", {}).keys())) or "unknown"
                self.daily_reset_reason = (
                    f"daily_rollover_exit_pending ({open_count} open; symbols={symbols}; sources={sources})"
                )
                self.status = "BLOCKED_WITH_REASON"
                self.allow_new_orders = False
                self.allow_new_orders_reason = self.daily_reset_reason
                self.save()
                logger.warning(
                    "⏳ Daily reset deferred until inventory is flat: %s",
                    self.daily_reset_reason,
                )
                return

            self.last_reset_date = today
            self.start_total_equity_idr = total_equity_idr
            self.max_daily_loss_idr = total_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            self.reset_deposits_offset = 0.0
            self.reset_withdrawals_offset = 0.0
            self.pending_daily_reset = False
            self.daily_reset_reason = ""
            self.status = "RECONCILED"
            self.allow_new_orders = True
            self.allow_new_orders_reason = ""
            self._write_daily_anchor()
            self.save()
            logger.info(f"⚓ Daily Total Equity Anchor Reset: Rp{self.start_total_equity_idr:,.2f} (Cap: Rp{self.max_daily_loss_idr:,.2f})")

    def manual_pnl_reset(self):
        """
        Manually reset the daily PnL anchor to the current consolidated equity.
        Maintains an audit trail by logging and updating the governor state file,
        but does not delete trade or transfer history.
        """
        logger.info(f"🔄 Manual daily PnL anchor reset initiated. Current total equity: Rp{self.current_total_equity_idr:,.2f}")
        
        # Read the raw daily transfers so far to establish the offset
        raw_deposits, raw_withdrawals = self._read_daily_transfers(self.last_reset_date)
        
        self.start_total_equity_idr = self.current_total_equity_idr
        self.max_daily_loss_idr = self.current_total_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
        self.start_indodax_equity_idr = 0.0
        self.start_phantom_equity_idr = 0.0
        self.reset_deposits_offset = raw_deposits
        self.reset_withdrawals_offset = raw_withdrawals
        self.daily_pnl_idr = 0.0
        self.daily_pnl_pct = 0.0
        self.indodax_daily_pnl_idr = 0.0
        self.indodax_daily_pnl_pct = 0.0
        self.phantom_daily_pnl_idr = 0.0
        self.phantom_daily_pnl_pct = 0.0
        self.external_deposits_today = 0.0
        self.external_withdrawals_today = 0.0
        self.pending_daily_reset = False
        self.daily_reset_reason = ""
        self.save()
        self._write_daily_anchor()
        logger.info(f"⚓ PnL Anchor reset to current reconciled equity. Starting Equity: Rp{self.start_total_equity_idr:,.2f}. Offsets registered: Dep Rp{self.reset_deposits_offset:,.2f}, Wd Rp{self.reset_withdrawals_offset:,.2f}")

    async def reconcile_governor(self) -> Dict[str, Any]:
        """
        Orchestrate wallet balances, update the Venue Ledger,
        apply target allocation policies, and enforce global risk parameters.
        """
        self.status = "UNRECONCILED"
        try:
            # 1. Reconcile Phantom Web3 balances
            await self.phantom_treasury.reconcile_balances()
            phantom_summary = self.phantom_treasury.get_summary()
            phantom_equity_idr = phantom_summary.get("total_value_idr", 0.0)
            
            # 2. Reconcile Indodax balance
            indodax_real_balance = 0.0
            indodax_coin_holdings_idr = 0.0
            if self.indodax:
                try:
                    # Query real balance with 5 second timeout
                    indo_info = await asyncio.wait_for(self.indodax.get_info(), timeout=5)
                    if indo_info.get("success") == 1:
                        balances = indo_info.get("return", {}).get("balance", {})
                        indodax_real_balance = float(balances.get("idr", 0.0) or 0.0)
                        held_coins = []
                        for coin, amount in balances.items():
                            if coin == "idr":
                                continue
                            try:
                                amt = float(amount or 0.0)
                            except Exception:
                                continue
                            if amt > 1e-6:
                                held_coins.append((coin, amt))
                        if held_coins:
                            coin_tasks = []
                            for coin, amt in held_coins:
                                coin_tasks.append(self.indodax.get_ticker(f"{coin}_idr"))
                            try:
                                tickers = await asyncio.gather(*coin_tasks, return_exceptions=True)
                                for (coin, amt), ticker in zip(held_coins, tickers):
                                    if isinstance(ticker, Exception):
                                        continue
                                    try:
                                        price = float(ticker.get("last", 0.0) or 0.0)
                                    except Exception:
                                        price = 0.0
                                    if price > 0:
                                        indodax_coin_holdings_idr += amt * price
                            except Exception as e:
                                logger.error(f"❌ Failed to query Indodax coin holdings: {e}")
                    if indodax_coin_holdings_idr <= 0.0:
                        indodax_coin_holdings_idr = await self._read_indodax_coin_holdings_from_active_trades()
                except Exception as e:
                    logger.error(f"❌ Failed to query Indodax balance: {e}")
                    
            # Shadow reserve is only used when live trading is disabled.
            indodax_shadow_balance = 1000000.0
            shadow_ledger = self.ledger.get_venue("indodax_shadow")
            if shadow_ledger:
                indodax_shadow_balance = shadow_ledger.get("equity_idr", 1000000.0)

            # 3. Calculate Total Consolidated Equity
            # Controlled-live mode takes actual Indodax cash + mark-to-market coin holdings
            # + any pending buy reserve that is already part of the exchange account value.
            indodax_live_equity = indodax_real_balance + indodax_coin_holdings_idr
            phantom_reconciliation = phantom_summary.get("reconciliation", {}) if isinstance(phantom_summary, dict) else {}
            phantom_ready = bool(phantom_equity_idr > 0.0)
            phantom_status = str(phantom_summary.get("status") or "").upper() if isinstance(phantom_summary, dict) else ""
            if phantom_status in {"OK", "SCOUTING", "DEGRADED"} and phantom_equity_idr > 0.0:
                phantom_ready = True
            elif phantom_status in {"OK", "SCOUTING"} and bool(phantom_reconciliation.get("matches_user_wallet")):
                phantom_ready = True

            daily_reset_state = _load_daily_reset_state()
            daily_reset_status = str(daily_reset_state.get("status") or "").upper().strip()
            daily_reset_current_mode = str(daily_reset_state.get("current_global_mode") or "").upper().strip()
            daily_reset_active = bool(
                daily_reset_status in {"PRE_CLOSE", "EXITING", "PENDING_RESET"}
                or (
                    daily_reset_status == "MONITORING"
                    and daily_reset_current_mode == "EXIT_ALL"
                    and bool(daily_reset_state.get("forced_exit_all", False))
                )
            )
            if daily_reset_active:
                self.pending_daily_reset = True
                self.daily_reset_reason = str(
                    daily_reset_state.get("reason")
                    or self.daily_reset_reason
                    or "daily_rollover_exit_pending"
                ).strip()
            elif daily_reset_status == "RESET_DONE" and self.pending_daily_reset:
                self.pending_daily_reset = False
                if self.daily_reset_reason in {"", "daily_rollover_exit_pending"}:
                    self.daily_reset_reason = ""
            
            # Read in-flight internal transfers destined for Phantom
            in_flight_idr = self._read_in_flight_transfers(self.last_reset_date, phantom_equity_idr)
            pending_buy_reserve_idr = _pending_buy_order_reserve_idr()
            primary_indodax_balance = (
                indodax_live_equity + pending_buy_reserve_idr
                if KiConfig.LIVE_TRADING_ENABLED
                else indodax_shadow_balance
            )

            # Venue-specific anchors keep one venue's drawdown from blocking the others.
            if self.start_indodax_equity_idr <= 0.0:
                self.start_indodax_equity_idr = float(primary_indodax_balance or 0.0)
            if self.start_phantom_equity_idr <= 0.0:
                self.start_phantom_equity_idr = float(phantom_equity_idr or 0.0)

            venue_anchor_sum = self.start_indodax_equity_idr + self.start_phantom_equity_idr
            if (
                self.start_total_equity_idr > 0.0
                and venue_anchor_sum > 0.0
                and abs(venue_anchor_sum - self.start_total_equity_idr) > max(1000.0, self.start_total_equity_idr * 0.05)
            ):
                current_split_total = max(primary_indodax_balance + phantom_equity_idr, 1.0)
                self.start_indodax_equity_idr = self.start_total_equity_idr * (primary_indodax_balance / current_split_total)
                self.start_phantom_equity_idr = self.start_total_equity_idr * (phantom_equity_idr / current_split_total)
            if self.start_indodax_equity_idr <= 0.0:
                self.start_indodax_equity_idr = float(primary_indodax_balance or 0.0)
            if self.start_phantom_equity_idr <= 0.0:
                self.start_phantom_equity_idr = float(phantom_equity_idr or 0.0)

            indodax_daily_loss_cap_idr = self.start_indodax_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            phantom_daily_loss_cap_idr = self.start_phantom_equity_idr * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0)
            self.indodax_daily_pnl_idr = primary_indodax_balance - self.start_indodax_equity_idr
            self.phantom_daily_pnl_idr = phantom_equity_idr - self.start_phantom_equity_idr
            self.indodax_daily_pnl_pct = (self.indodax_daily_pnl_idr / max(self.start_indodax_equity_idr, 1.0)) * 100.0
            self.phantom_daily_pnl_pct = (self.phantom_daily_pnl_idr / max(self.start_phantom_equity_idr, 1.0)) * 100.0

            # Total Consolidated Equity = Primary Indodax Balance (including reserve) + Phantom Balance
            # + In-flight internal transfers.
            self.current_total_equity_idr = primary_indodax_balance + phantom_equity_idr + in_flight_idr
            
            # Check and initialize today's start anchor if needed
            await self.check_daily_reset(self.current_total_equity_idr)
            
            # Read daily transfers to adjust starting equity
            deposits, withdrawals = self._read_daily_transfers(self.last_reset_date)
            adjusted_deposits = deposits - self.reset_deposits_offset
            adjusted_withdrawals = withdrawals - self.reset_withdrawals_offset
            
            self.external_deposits_today = adjusted_deposits
            self.external_withdrawals_today = adjusted_withdrawals
            
            # Compute daily consolidated PnL (adjusted for capital flows and offset)
            self.daily_pnl_idr = self.current_total_equity_idr - self.start_total_equity_idr - adjusted_deposits + adjusted_withdrawals
            self.trading_pnl_idr = self.current_total_equity_idr - self.start_total_equity_idr
            
            # Compute PnL percentage
            if self.start_total_equity_idr > 0.0:
                self.daily_pnl_pct = (self.daily_pnl_idr / self.start_total_equity_idr) * 100.0
                self.trading_pnl_pct = (self.trading_pnl_idr / self.start_total_equity_idr) * 100.0
            else:
                self.daily_pnl_pct = 0.0
                self.trading_pnl_pct = 0.0
                
            indodax_ready = primary_indodax_balance > 0
            self.status = "RECONCILED" if (phantom_ready or indodax_ready) else "DEGRADED"
            if not phantom_ready:
                logger.warning("⚠️ Phantom treasury not yet reconciled; live Phantom routes remain venue-scoped.")
            
            # 4. Compute target allocation split
            targets = self.policy.compute_targets(phantom_equity_idr)
            
            # 5. Sync to Venue Ledger
            self.ledger.update_venue("indodax_real", equity_idr=primary_indodax_balance)
            self.ledger.update_venue("indodax_shadow", equity_idr=indodax_shadow_balance)
            self.ledger.update_venue("phantom", equity_idr=phantom_equity_idr)
            self.ledger.update_venue("cash_wait", equity_idr=self.current_total_equity_idr * targets.get("reserve", 0.20))

            global_hard_stop = bool(
                self.max_daily_loss_idr > 0.0 and self.daily_pnl_idr <= -self.max_daily_loss_idr
            )
            daily_reset_block = bool(getattr(self, "pending_daily_reset", False))

            indodax_local_allow = bool(indodax_ready and self.indodax_daily_pnl_idr > -indodax_daily_loss_cap_idr)
            phantom_local_allow = bool(phantom_ready and self.phantom_daily_pnl_idr > -phantom_daily_loss_cap_idr)
            indodax_allow_orders = bool(indodax_local_allow and not global_hard_stop and not daily_reset_block)
            phantom_allow_orders = bool(phantom_local_allow and not global_hard_stop and not daily_reset_block)

            indodax_reason = ""
            if not indodax_ready:
                indodax_reason = "indodax_balance_unavailable"
            elif daily_reset_block:
                indodax_reason = self.daily_reset_reason or "daily_rollover_exit_pending"
            elif global_hard_stop:
                indodax_reason = (
                    "global_daily_loss_cap_breached "
                    f"({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                )
            elif not indodax_allow_orders:
                indodax_reason = (
                    "indodax_daily_loss_cap_breached "
                    f"({self.indodax_daily_pnl_idr:.2f} < -{indodax_daily_loss_cap_idr:.2f})"
                )

            phantom_reason = ""
            if not phantom_ready:
                if phantom_equity_idr > 0.0:
                    phantom_reason = "phantom_reconciliation_degraded"
                else:
                    phantom_reason = "phantom_balance_unavailable"
            elif daily_reset_block:
                phantom_reason = self.daily_reset_reason or "daily_rollover_exit_pending"
            elif global_hard_stop:
                phantom_reason = (
                    "global_daily_loss_cap_breached "
                    f"({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                )
            elif not phantom_allow_orders:
                phantom_reason = (
                    "phantom_daily_loss_cap_breached "
                    f"({self.phantom_daily_pnl_idr:.2f} < -{phantom_daily_loss_cap_idr:.2f})"
                )

            allow_new_orders = bool(indodax_allow_orders or phantom_allow_orders)
            if global_hard_stop or daily_reset_block:
                allow_new_orders = False
                if daily_reset_block:
                    allow_reason = self.daily_reset_reason or "daily_rollover_exit_pending"
                else:
                    allow_reason = (
                        "global_daily_loss_cap_breached "
                        f"({self.daily_pnl_idr:.2f} <= -{self.max_daily_loss_idr:.2f})"
                    )
            elif allow_new_orders:
                ready_bits = []
                if indodax_allow_orders:
                    ready_bits.append("indodax")
                if phantom_allow_orders:
                    ready_bits.append("phantom")
                allow_reason = "venue-scoped allowances active: " + ", ".join(ready_bits)
            else:
                blocked_bits = []
                if indodax_reason:
                    blocked_bits.append(f"indodax={indodax_reason}")
                if phantom_reason:
                    blocked_bits.append(f"phantom={phantom_reason}")
                allow_reason = "; ".join(blocked_bits) or "no venue ready for orders"
            self.status = "BLOCKED_WITH_REASON" if (global_hard_stop or daily_reset_block) else ("RECONCILED" if allow_new_orders else "DEGRADED")
            
            payload = {
                "date": self.last_reset_date,
                "global_status": self.status,
                "start_total_equity_idr": self.start_total_equity_idr,
                "reset_total_balance_idr": self.start_total_equity_idr,
                "current_total_equity_idr": self.current_total_equity_idr,
                "total_balance_idr": self.current_total_equity_idr,
                "open_buy_order_reserve_idr": pending_buy_reserve_idr,
                "max_daily_loss_idr": self.max_daily_loss_idr,
                "daily_pnl_idr": self.daily_pnl_idr,
                "combined_pnl_idr": self.daily_pnl_idr,
                "daily_return_idr": self.daily_pnl_idr,
                "daily_pnl_pct": self.daily_pnl_pct,
                "daily_return_pct": self.daily_pnl_pct,
                "external_deposits_today": self.external_deposits_today,
                "external_withdrawals_today": self.external_withdrawals_today,
                "reset_deposits_offset": self.reset_deposits_offset,
                "reset_withdrawals_offset": self.reset_withdrawals_offset,
                "in_flight_idr": in_flight_idr,
                "daily_reset_pending": daily_reset_block,
                "daily_reset_reason": self.daily_reset_reason,
                "locked_inventory_count": int(getattr(self, "locked_inventory_count", 0) or 0),
                "locked_inventory_symbols": list(getattr(self, "locked_inventory_symbols", []) or []),
                "status": self.status,
                "global_hard_stop": global_hard_stop,
                "global_hard_stop_reason": allow_reason if global_hard_stop else "",
                "allow_new_orders": allow_new_orders,
                "allow_new_orders_reason": allow_reason,
                "venues": {
                    "indodax": {
                        "status": "RECONCILED" if indodax_allow_orders else "BLOCKED_WITH_REASON",
                        "equity_idr": primary_indodax_balance,
                        "open_buy_order_reserve_idr": pending_buy_reserve_idr,
                        "start_equity_idr": self.start_indodax_equity_idr,
                        "daily_pnl_idr": self.indodax_daily_pnl_idr,
                        "daily_pnl_pct": self.indodax_daily_pnl_pct,
                        "daily_loss_cap_idr": indodax_daily_loss_cap_idr,
                        "allow_orders": indodax_allow_orders,
                        "reason": indodax_reason,
                    },
                    "phantom": {
                        "status": "RECONCILED" if phantom_allow_orders else "BLOCKED_WITH_REASON",
                        "equity_idr": phantom_equity_idr,
                        "start_equity_idr": self.start_phantom_equity_idr,
                        "daily_pnl_idr": self.phantom_daily_pnl_idr,
                        "daily_pnl_pct": self.phantom_daily_pnl_pct,
                        "daily_loss_cap_idr": phantom_daily_loss_cap_idr,
                        "allow_orders": phantom_allow_orders,
                        "reason": phantom_reason,
                    },
                },
                "allow_indodax_orders": indodax_allow_orders,
                "allow_phantom_orders": phantom_allow_orders,
                "bridge": "ON",
                "withdrawal": "ON",
                "targets": targets,
                "phantom_details": phantom_summary
            }
            self.allow_new_orders = allow_new_orders
            self.allow_new_orders_reason = allow_reason
            self.venue_states = payload.get("venues", {})
            self.targets_snapshot = targets
            self.phantom_details_snapshot = phantom_summary
            self.save()
            return payload
        except Exception as e:
            logger.error(f"❌ Error in reconcile_governor: {e}", exc_info=True)
            self.status = "UNRECONCILED"
            self.save()
            raise e

if __name__ == "__main__":
    import asyncio
    import argparse
    import sys
    
    # Configure logging to stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    )
    
    parser = argparse.ArgumentParser(description="KiBot Capital Governor CLI/Service")
    parser.add_argument("--reset-pnl", action="store_true", help="Trigger manual PnL reset to current reconciled equity")
    args = parser.parse_args()
    
    async def run_governor_service(reset_only=False):
        # Instantiate gateways
        try:
            from Core.Exchange.indodax import IndodaxGateway
            indodax = IndodaxGateway()
        except Exception as e:
            logger.error(f"Failed to import/instantiate IndodaxGateway: {e}")
            indodax = None
            
        try:
            from Core.Exchange.phantom_router import PhantomRouter
            phantom_router = PhantomRouter()
        except Exception as e:
            logger.error(f"Failed to import/instantiate PhantomRouter: {e}")
            phantom_router = None
            
        gov = CapitalGovernor(indodax, phantom_router)
        
        if reset_only:
            logger.info("Executing initial reconciliation to get current consolidated equity...")
            await gov.reconcile_governor()
            gov.manual_pnl_reset()
            logger.info("✅ Manual Daily PnL Reset completed successfully.")
            return

        logger.info("Initializing Capital Governor standalone service loop...")
        # Infinite reconciliation loop (every 10 seconds)
        while True:
            try:
                logger.info("Executing capital reconciliation cycle...")
                res = await gov.reconcile_governor()
                logger.info(
                    f"Consolidated Reconciled: Total Equity Rp{res['current_total_equity_idr']:,.2f} | "
                    f"Daily PnL Rp{res['daily_pnl_idr']:+,.2f} | Date: {res['date']}"
                )
            except Exception as e:
                logger.error(f"Error in reconciliation cycle: {e}", exc_info=True)
            await asyncio.sleep(10)

    try:
        if args.reset_pnl:
            asyncio.run(run_governor_service(reset_only=True))
        else:
            asyncio.run(run_governor_service(reset_only=False))
    except KeyboardInterrupt:
        logger.info("Capital Governor Service stopped by user.")
