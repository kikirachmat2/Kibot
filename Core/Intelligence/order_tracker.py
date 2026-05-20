"""
KiBot Order Lifecycle Tracker
==============================
§16.2 — Order Lifecycle State Tracking

Tracks every order from CREATED → RECONCILED.
Bridges the gap between SUBMITTED and actual FILLED state,
so the system knows what is real money at risk vs. pending intent.

States:
    CREATED          — mandate generated, not yet sent to exchange
    SUBMITTED        — market order sent, awaiting exchange ack
    ACCEPTED         — exchange accepted (limit) or acknowledged
    PARTIAL_FILL     — partially filled (limit orders)
    FILLED           — fully filled
    STALE            — not filled after max_hold_minutes
    CANCEL_REQUESTED — cancel sent to exchange
    CANCELLED        — exchange confirmed cancelled
    RECONCILED       — wallet balance delta matches order; closed P&L recorded
    FAILED           — exchange rejected or network error

All orders are persisted to state/orders/<order_id>.json (atomic write).
The tracker also maintains an index at state/orders/_index.json.
"""

from __future__ import annotations

import json
import os
import time
import uuid
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("OrderTracker")

try:
    from Core.Intelligence.trade_history import record_trade_event as _record_trade_event
except Exception:
    _record_trade_event = None

# ─────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────

WIB_UTC_OFFSET_HOURS = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))
WIB_TZ = timezone(timedelta(hours=WIB_UTC_OFFSET_HOURS))

ORDERS_DIR = Path("state/orders")
INDEX_FILE = ORDERS_DIR / "_index.json"

VALID_STATES = [
    "CREATED",
    "SUBMITTED",
    "ACCEPTED",
    "PARTIAL_FILL",
    "FILLED",
    "STALE",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "RECONCILED",
    "FAILED",
]

# Transitions that are allowed (from_state → set of valid next_states)
ALLOWED_TRANSITIONS: Dict[str, set] = {
    "CREATED":          {"SUBMITTED", "CANCELLED", "FAILED"},
    "SUBMITTED":        {"ACCEPTED", "FILLED", "PARTIAL_FILL", "STALE", "CANCELLED", "FAILED"},
    "ACCEPTED":         {"FILLED", "PARTIAL_FILL", "STALE", "CANCEL_REQUESTED", "CANCELLED", "FAILED"},
    "PARTIAL_FILL":     {"FILLED", "STALE", "CANCEL_REQUESTED", "CANCELLED"},
    "FILLED":           {"RECONCILED", "STALE"},
    "STALE":            {"CANCEL_REQUESTED", "CANCELLED", "RECONCILED", "FILLED"},
    "CANCEL_REQUESTED": {"CANCELLED", "FILLED"},
    "CANCELLED":        {"RECONCILED"},
    "RECONCILED":       set(),   # terminal
    "FAILED":           set(),   # terminal
}

TERMINAL_STATES = {"RECONCILED", "CANCELLED", "FAILED"}


def _emit_trade_history(event_type: str, payload: Dict[str, Any]) -> None:
    if _record_trade_event is None:
        return
    try:
        _record_trade_event(event_type, payload)
    except Exception as exc:
        logger.debug("Trade history emission failed for %s: %s", event_type, exc)


# ─────────────────────────────────────────────────────────
# Atomic I/O helpers
# ─────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
    return {}


def _load_active_trade_symbols() -> set[str]:
    """
    Return the currently tracked live position symbols.

    The order tracker is a lifecycle store, but the dispatcher and reset logic
    need a quicker way to detect whether a FILLED order still has live backing
    in active_trades.json. If it does not, the FILLED record is a ghost and
    should stop blocking open-order calculations.
    """
    active = _load_json(ORDERS_DIR.parent / "active_trades.json")
    symbols: set[str] = set()
    if isinstance(active, dict):
        for symbol, trade in active.items():
            if not isinstance(trade, dict):
                continue
            try:
                amount = 0.0
                for key in ("amount", "coin_amount", "size", "quantity"):
                    amount = float(trade.get(key) or 0.0)
                    if amount > 0:
                        break
            except Exception:
                amount = 0.0
            if amount > 0:
                symbols.add(str(symbol).upper().strip())
    return symbols


def _now_wib() -> datetime:
    return datetime.now(WIB_TZ)


def _now_ts() -> float:
    return time.time()


# ─────────────────────────────────────────────────────────
# Order record builder
# ─────────────────────────────────────────────────────────

def _order_path(order_id: str) -> Path:
    return ORDERS_DIR / f"{order_id}.json"


def _build_order_record(
    order_id: str,
    pair: str,
    side: str,
    budget_idr: float,
    price: float,
    mandate: Dict,
    exit_plan: Optional[Dict] = None,
    signal: Optional[Dict] = None,
) -> dict:
    now = _now_wib().isoformat()
    return {
        "order_id":          order_id,
        "pair":              pair.upper(),
        "side":              side.upper(),
        "budget_idr":        round(budget_idr, 2),
        "price_at_mandate":  round(price, 8),
        "coin_amount":       0.0,       # set on FILLED
        "fill_price":        None,      # set on FILLED
        "fill_ts":           None,
        "pnl_idr":           None,      # set on RECONCILED
        "pnl_pct":           None,

        # State machine
        "state":             "CREATED",
        "state_history": [
            {"state": "CREATED", "ts": now, "note": "mandate issued"}
        ],

        # Risk governance
        "lifecycle":         signal.get("lifecycle", "UNKNOWN") if signal else "UNKNOWN",
        "trade_grade":       signal.get("trade_grade", "?") if signal else "?",
        "confidence":        signal.get("confidence", 0.0) if signal else 0.0,
        "exit_plan":         exit_plan or {},
        "max_hold_minutes":  int((exit_plan or {}).get("max_hold_minutes", 120)),
        "stale_after_ts":    _now_ts() + int((exit_plan or {}).get("max_hold_minutes", 120)) * 60,

        # Exchange tracking
        "exchange":          "INDODAX",
        "exchange_order_id": None,      # set on SUBMITTED
        "raw_response":      None,

        # Mandate reference
        "mandate_source":    mandate.get("source", mandate.get("phase", "UNKNOWN")),
        "deadline_mode":     mandate.get("deadline_mode", "PATIENT"),
        "budget_fraction":   round(float(mandate.get("budget_fraction", 0.0)), 3),

        "created_at":        now,
        "updated_at":        now,
    }


# ─────────────────────────────────────────────────────────
# Index management
# ─────────────────────────────────────────────────────────

def _load_index() -> dict:
    return _load_json(INDEX_FILE)


def _update_index(order_id: str, pair: str, state: str, side: str) -> None:
    idx = _load_index()
    idx.setdefault("orders", {})[order_id] = {
        "pair":       pair,
        "side":       side,
        "state":      state,
        "updated_at": _now_wib().isoformat(),
    }
    # Keep open orders list current
    idx["open"] = [
        oid for oid, meta in idx.get("orders", {}).items()
        if meta.get("state") not in TERMINAL_STATES
    ]
    _atomic_write(INDEX_FILE, idx)


# ─────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────

class OrderTracker:
    """
    Sovereign Order Lifecycle Tracker — §16.2

    Usage:
        tracker = OrderTracker()

        # Create order on mandate
        order_id = tracker.create(pair, side, budget_idr, price, mandate, exit_plan, signal)

        # Update state as exchange responds
        tracker.transition(order_id, "SUBMITTED", exchange_order_id="xyz", note="sent")
        tracker.transition(order_id, "FILLED", fill_price=3500.0, coin_amount=14.28)

        # Reconcile after checking wallet
        tracker.reconcile(order_id, sell_value_idr=52000)
    """

    def create(
        self,
        pair: str,
        side: str,
        budget_idr: float,
        price: float,
        mandate: Dict,
        exit_plan: Optional[Dict] = None,
        signal: Optional[Dict] = None,
    ) -> str:
        """
        Create a new order record in CREATED state.
        Returns the new order_id.
        """
        order_id = f"{pair.lower().replace('/', '_')}_{int(_now_ts() * 1000)}_{uuid.uuid4().hex[:6]}"
        record = _build_order_record(order_id, pair, side, budget_idr, price, mandate, exit_plan, signal)
        _atomic_write(_order_path(order_id), record)
        _update_index(order_id, pair, "CREATED", side)
        _emit_trade_history("ORDER_CREATED", {
            "order_id": order_id,
            "pair": pair,
            "side": side,
            "budget_idr": budget_idr,
            "price_idr": price,
            "lifecycle": record.get("lifecycle"),
            "trade_grade": record.get("trade_grade"),
            "deadline_mode": record.get("deadline_mode"),
            "source": "order_tracker",
            "status": "CREATED",
        })
        logger.info(f"[OrderTracker] CREATED {order_id} | {pair} {side} {budget_idr:.0f} IDR @ {price}")
        return order_id

    def transition(
        self,
        order_id: str,
        new_state: str,
        *,
        note: str = "",
        exchange_order_id: Optional[str] = None,
        fill_price: Optional[float] = None,
        coin_amount: Optional[float] = None,
        raw_response: Any = None,
        trade_history_payload: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Move an order to a new state.
        Validates transition is allowed before writing.
        Returns updated order record.
        """
        record = self.load(order_id)
        if not record:
            raise ValueError(f"Order {order_id} not found")

        current = record.get("state", "CREATED")
        if new_state not in VALID_STATES:
            raise ValueError(f"Invalid state: {new_state}")
        if new_state not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ValueError(f"Transition {current} → {new_state} not allowed for {order_id}")

        now = _now_wib().isoformat()
        record["state"]      = new_state
        record["updated_at"] = now
        record["state_history"].append({
            "state": new_state,
            "ts":    now,
            "note":  note or "",
        })

        if exchange_order_id:
            record["exchange_order_id"] = exchange_order_id
        if raw_response is not None:
            record["raw_response"] = raw_response
        if fill_price is not None:
            record["fill_price"] = round(float(fill_price), 8)
            record["fill_ts"]    = now
        if coin_amount is not None:
            record["coin_amount"] = round(float(coin_amount), 8)

        # Auto stale check
        if new_state == "FILLED" and record.get("stale_after_ts"):
            record["stale_after_ts"] = None  # no longer relevant

        _atomic_write(_order_path(order_id), record)
        _update_index(order_id, record["pair"], new_state, record["side"])
        event_type = f"ORDER_{new_state}".upper()
        history_payload = {
            "order_id": order_id,
            "pair": record.get("pair"),
            "side": record.get("side"),
            "state": new_state,
            "status": new_state,
            "note": note,
            "exchange_order_id": record.get("exchange_order_id") or exchange_order_id or "",
            "price_idr": record.get("fill_price") if record.get("fill_price") is not None else record.get("price_at_mandate"),
            "amount_coin": record.get("coin_amount") or coin_amount or 0.0,
            "amount_idr": record.get("budget_idr"),
            "trade_grade": record.get("trade_grade"),
            "lifecycle": record.get("lifecycle"),
            "source": "order_tracker",
        }
        if isinstance(trade_history_payload, dict):
            history_payload.update(trade_history_payload)
        _emit_trade_history(event_type, history_payload)
        logger.info(f"[OrderTracker] {order_id} → {new_state}" + (f" | {note}" if note else ""))
        return record

    def reconcile(
        self,
        order_id: str,
        sell_value_idr: Optional[float] = None,
        pnl_idr: Optional[float] = None,
        fee_idr: Optional[float] = None,
        gross_pnl_idr: Optional[float] = None,
    ) -> dict:
        """
        Mark an order as RECONCILED after sell confirms.
        Either provide sell_value_idr (gross) or pnl_idr directly.
        """
        record = self.load(order_id)
        if not record:
            raise ValueError(f"Order {order_id} not found")

        budget    = float(record.get("budget_idr", 0))
        fill_px   = float(record.get("fill_price") or 0)
        coins     = float(record.get("coin_amount") or 0)

        if pnl_idr is None and sell_value_idr is not None:
            pnl_idr = round(sell_value_idr - budget - float(fee_idr or 0.0), 2)
        if pnl_idr is None:
            pnl_idr = 0.0
        if gross_pnl_idr is None and sell_value_idr is not None:
            gross_pnl_idr = round(sell_value_idr - budget, 2)

        pnl_pct = round((pnl_idr / budget) * 100, 3) if budget > 0 else 0.0

        record["pnl_idr"] = round(pnl_idr, 2)
        record["pnl_pct"] = pnl_pct
        exit_price = round(sell_value_idr / max(coins, 1e-9), 8) if sell_value_idr is not None and coins > 0 else None
        reconciled_record = self.transition(
            order_id,
            "RECONCILED",
            note=f"PnL={pnl_idr:+.0f} IDR ({pnl_pct:+.2f}%)",
            trade_history_payload={
                "state": "RECONCILED",
                "status": "CLOSED",
                "entry_price_idr": fill_px,
                "exit_price_idr": exit_price or 0.0,
                "amount_coin": coins,
                "amount_idr": budget,
                "fee_idr": float(fee_idr or 0.0),
                "gross_realized_pnl_idr": float(gross_pnl_idr or 0.0),
                "net_realized_pnl_idr": pnl_idr,
                "realized_pnl_idr": pnl_idr,
                "realized_pnl_pct": pnl_pct,
                "trade_grade": record.get("trade_grade"),
                "lifecycle": record.get("lifecycle"),
                "reason": "sell_value_reconciled",
            },
        )
        reconciled_record["pnl_idr"] = round(pnl_idr, 2)
        reconciled_record["pnl_pct"] = pnl_pct
        reconciled_record["updated_at"] = _now_wib().isoformat()
        _atomic_write(_order_path(order_id), reconciled_record)
        _update_index(order_id, reconciled_record["pair"], "RECONCILED", reconciled_record["side"])

        # Feed to learning engine
        try:
            from Core.Intelligence.kibot_learning_engine import get_engine
            engine = get_engine()
            pair_key = reconciled_record["pair"].lower().replace("/", "_")
            won = pnl_idr > 0
            gain_pct = pnl_pct / 100.0
            engine.record_trade(pair_key, gain_pct, regime=reconciled_record.get("trade_grade", "NORMAL"), won=won, pnl_idr=pnl_idr)
            logger.info(f"[OrderTracker] Recorded trade to learning engine: {pair_key} PnL={pnl_idr:+.0f} IDR")
        except Exception as e:
            logger.warning(f"[OrderTracker] Learning engine update failed: {e}")

        return reconciled_record

    def mark_stale(self, order_id: str) -> Optional[dict]:
        """Mark an order as STALE if it has exceeded max_hold_minutes."""
        record = self.load(order_id)
        if not record:
            return None
        state = record.get("state")
        stale_ts = float(record.get("stale_after_ts") or 0)
        if state in TERMINAL_STATES or state in ("STALE", "CANCEL_REQUESTED"):
            return record
        if stale_ts > 0 and _now_ts() > stale_ts:
            logger.warning(f"[OrderTracker] {order_id} is STALE (max hold exceeded)")
            _emit_trade_history("ORDER_STALE", {
                "order_id": order_id,
                "pair": record.get("pair"),
                "side": record.get("side"),
                "state": "STALE",
                "status": "STALE",
                "price_idr": record.get("fill_price") if record.get("fill_price") is not None else record.get("price_at_mandate"),
                "amount_coin": record.get("coin_amount") or 0.0,
                "amount_idr": record.get("budget_idr"),
                "trade_grade": record.get("trade_grade"),
                "lifecycle": record.get("lifecycle"),
                "source": "order_tracker",
                "reason": "max_hold_minutes exceeded",
            })
            return self.transition(order_id, "STALE", note="max_hold_minutes exceeded")
        return record

    def load(self, order_id: str) -> Optional[dict]:
        """Load an order record by ID."""
        path = _order_path(order_id)
        data = _load_json(path)
        return data if data else None

    def get_open_orders(self) -> List[dict]:
        """Return all non-terminal orders."""
        idx = _load_index()
        open_ids = idx.get("open", [])
        active_symbols = _load_active_trade_symbols()
        records = []
        kept_open_ids: List[str] = []
        pruned = False
        for oid in open_ids:
            r = self.load(oid)
            if r:
                state = str(r.get("state") or "").upper().strip()
                pair = str(r.get("pair") or r.get("symbol") or "").upper().strip()
                if state == "FILLED" and pair and pair not in active_symbols:
                    # Filled lifecycle records without active_trades backing are
                    # ghosts from a previous session; keep the order file as
                    # historical evidence, but stop treating them as live.
                    pruned = True
                    logger.info(
                        "[OrderTracker] pruning ghost FILLED order %s (%s) from open index",
                        oid,
                        pair,
                    )
                    continue
                records.append(r)
                kept_open_ids.append(oid)
            else:
                pruned = True
        if pruned:
            idx["open"] = kept_open_ids
            _atomic_write(INDEX_FILE, idx)
        return records

    def scan_stale(self) -> List[str]:
        """
        Scan all open orders for stale ones and mark them.
        Returns list of order IDs that were marked STALE.
        """
        now = _now_ts()
        staled = []
        for record in self.get_open_orders():
            order_id = record.get("order_id", "")
            stale_ts = float(record.get("stale_after_ts") or 0)
            state    = record.get("state", "")
            if state not in TERMINAL_STATES and stale_ts > 0 and now > stale_ts:
                self.mark_stale(order_id)
                staled.append(order_id)
        return staled

    def get_today_summary(self) -> dict:
        """Return today's order activity summary."""
        idx = _load_index()
        today = _now_wib().date().isoformat()
        all_orders = idx.get("orders", {})

        total = 0
        filled = 0
        reconciled = 0
        cancelled = 0
        stale = 0
        pnl_idr = 0.0

        for oid, meta in all_orders.items():
            r = self.load(oid)
            if not r:
                continue
            created = r.get("created_at", "")
            if not created.startswith(today):
                continue
            total += 1
            s = r.get("state", "")
            if s == "FILLED":
                filled += 1
            elif s == "RECONCILED":
                reconciled += 1
                pnl_idr += float(r.get("pnl_idr") or 0)
            elif s in ("CANCELLED", "CANCEL_REQUESTED"):
                cancelled += 1
            elif s == "STALE":
                stale += 1

        return {
            "date":        today,
            "total":       total,
            "filled":      filled,
            "reconciled":  reconciled,
            "cancelled":   cancelled,
            "stale":       stale,
            "pnl_idr":     round(pnl_idr, 2),
        }


# ─────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────

_tracker_instance: Optional[OrderTracker] = None

def get_tracker() -> OrderTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = OrderTracker()
    return _tracker_instance


# ─────────────────────────────────────────────────────────
# CLI smoke test
# ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    tracker = OrderTracker()

    # Simulate a full lifecycle
    mandate = {"source": "DEEP_COUNCIL", "phase": "DEEP_COUNCIL", "deadline_mode": "PATIENT", "budget_fraction": 0.20}
    exit_plan = {"hard_stop_pct": 2.5, "max_hold_minutes": 90, "trailing_profit_schedule": [(3.0, 1.5), (5.0, 2.5)]}
    signal = {"lifecycle": "CONFIRMATION", "trade_grade": "B", "confidence": 0.72}

    oid = tracker.create("XRP/IDR", "BUY", 50000, 4200.0, mandate, exit_plan, signal)
    print(f"Created: {oid}")

    tracker.transition(oid, "SUBMITTED", exchange_order_id="IND-12345", note="market order sent")
    tracker.transition(oid, "FILLED", fill_price=4215.0, coin_amount=11.86, note="exchange filled")
    result = tracker.reconcile(oid, sell_value_idr=53200)
    print(f"Reconciled: PnL={result['pnl_idr']:+.0f} IDR ({result['pnl_pct']:+.2f}%)")

    print(f"\nToday summary: {tracker.get_today_summary()}")
