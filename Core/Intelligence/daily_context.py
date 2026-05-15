"""
Daily Context Engine
=====================
Shared situational awareness payload injected into every subsystem each cycle.
Contract: PUMP_LIFECYCLE_STRATEGY.md §11 — Deadline Intelligence Layer

All agents — Scanner, Council, Executor, Risk Gate, Dashboard — must receive
the same daily_context so they speak the same language.
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger("DailyContext")

WIB = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))
STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
DAILY_STATE_FILE = STATE_DIR / "daily_state.json"

# ─────────────────────────────────────────────
# Thresholds (from strategy §9 + §11.1)
# ─────────────────────────────────────────────
GREEN_PNL_THRESHOLD_IDR    = 0          # Any positive PnL = GREEN
RECOVERY_PNL_THRESHOLD_PCT = -0.005     # -0.5% of equity = RECOVERY

URGENCY_LOW_MINUTES      = 240   # > 4h to midnight = LOW
URGENCY_NORMAL_MINUTES   = 120   # 2-4h = NORMAL
URGENCY_HIGH_MINUTES     = 60    # 1-2h = HIGH
                                 # < 1h = CRITICAL


def _now_wib() -> datetime:
    return datetime.now(WIB)


def _minutes_to_midnight_wib() -> int:
    now = _now_wib()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return max(0, int((midnight - now).total_seconds() / 60))


def _daily_color(realized_pnl_idr: float, equity_idr: float) -> str:
    """
    §9: Color drives aggressiveness.
    GREEN  → protect first, continue only on strong edge
    RECOVERY → careful hunt for quality recovery
    FLAT  → normal probe / green-builder search
    """
    if realized_pnl_idr > GREEN_PNL_THRESHOLD_IDR:
        return "GREEN"
    if equity_idr > 0 and (realized_pnl_idr / equity_idr) < RECOVERY_PNL_THRESHOLD_PCT:
        return "RECOVERY"
    return "FLAT"


def _urgency_level(minutes_to_midnight: int) -> str:
    if minutes_to_midnight > URGENCY_LOW_MINUTES:
        return "LOW"
    if minutes_to_midnight > URGENCY_NORMAL_MINUTES:
        return "NORMAL"
    if minutes_to_midnight > URGENCY_HIGH_MINUTES:
        return "HIGH"
    return "CRITICAL"


def _allowed_risk_mode(daily_color: str, urgency: str) -> str:
    """
    §11.2: Daily Color + Deadline Matrix → allowed risk mode
    """
    matrix = {
        ("GREEN",    "LOW"):      "PROTECT",
        ("GREEN",    "NORMAL"):   "PROTECT",
        ("GREEN",    "HIGH"):     "PROTECT",
        ("GREEN",    "CRITICAL"): "PROTECT",
        ("RECOVERY", "LOW"):      "RECOVERY",
        ("RECOVERY", "NORMAL"):   "RECOVERY",
        ("RECOVERY", "HIGH"):     "RECOVERY",
        ("RECOVERY", "CRITICAL"): "WAIT",
        ("FLAT",     "LOW"):      "NORMAL",
        ("FLAT",     "NORMAL"):   "NORMAL",
        ("FLAT",     "HIGH"):     "PROBE",
        ("FLAT",     "CRITICAL"): "PROBE",
    }
    return matrix.get((daily_color, urgency), "NORMAL")


def _required_trade_quality(daily_color: str, urgency: str) -> str:
    """
    §11.2: Quality gate increases as deadline + green pressure rise.
    """
    if daily_color == "GREEN" and urgency in ("HIGH", "CRITICAL"):
        return "EXCEPTIONAL"
    if daily_color == "GREEN":
        return "HIGH"
    if daily_color == "RECOVERY" and urgency == "CRITICAL":
        return "EXCEPTIONAL"
    if daily_color == "RECOVERY":
        return "HIGH"
    return "NORMAL"


def _exit_strictness(daily_color: str, urgency: str) -> str:
    if daily_color == "GREEN" and urgency in ("HIGH", "CRITICAL"):
        return "LOCK_GREEN"
    if daily_color == "GREEN":
        return "TIGHT"
    return "NORMAL"


def _deadline_mode(urgency: str, daily_color: str) -> str:
    """
    §11.4: Deadline mode for Council's deadline_mode field.
    """
    if daily_color == "GREEN" and urgency in ("HIGH", "CRITICAL"):
        return "LOCK_GREEN"
    if urgency == "CRITICAL":
        return "URGENT"
    if urgency == "HIGH":
        return "ACTIVE"
    return "PATIENT"


def _market_regime_from_state() -> str:
    """Read cached market regime from scout/brain state if available."""
    try:
        world_model_path = STATE_DIR / "world_model.json"
        if world_model_path.exists():
            data = json.loads(world_model_path.read_text())
            return data.get("market_regime", "NEUTRAL")
    except Exception:
        pass
    return "NEUTRAL"


def _load_daily_pnl_state() -> dict:
    """Load persisted daily PnL tracking."""
    try:
        if DAILY_STATE_FILE.exists():
            data = json.loads(DAILY_STATE_FILE.read_text())
            today = str(_now_wib().date())
            if data.get("date_wib") == today:
                return data
    except Exception as e:
        logger.debug(f"DailyContext: failed to load daily state: {e}")
    return {
        "date_wib": str(_now_wib().date()),
        "realized_pnl_idr": 0.0,
        "unrealized_pnl_idr": 0.0,
        "combined_equity_idr": 0.0,
        "available_cash_idr": 0.0,
        "current_positions": [],
    }


def update_daily_state(
    realized_pnl_idr: float = 0.0,
    unrealized_pnl_idr: float = 0.0,
    combined_equity_idr: float = 0.0,
    available_cash_idr: float = 0.0,
    current_positions: Optional[list] = None,
) -> None:
    """
    Called by MasterNode / Executor after each cycle to persist portfolio state.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "date_wib": str(_now_wib().date()),
        "realized_pnl_idr": realized_pnl_idr,
        "unrealized_pnl_idr": unrealized_pnl_idr,
        "combined_equity_idr": combined_equity_idr,
        "available_cash_idr": available_cash_idr,
        "current_positions": current_positions or [],
        "updated_at": _now_wib().isoformat(),
    }
    tmp = DAILY_STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(DAILY_STATE_FILE)


def get_daily_context(
    realized_pnl_idr: Optional[float] = None,
    unrealized_pnl_idr: Optional[float] = None,
    combined_equity_idr: Optional[float] = None,
    available_cash_idr: Optional[float] = None,
    current_positions: Optional[list] = None,
    market_regime: Optional[str] = None,
) -> dict:
    """
    Build and return the shared situational awareness payload.

    Callers may pass live values (from executor/portfolio snapshot) or
    leave them None to fall back to the last persisted daily state.

    Returns the full daily_context dict per §11 spec.
    """
    now = _now_wib()
    persisted = _load_daily_pnl_state()

    # Merge: prefer live values, fall back to persisted
    r_pnl   = realized_pnl_idr   if realized_pnl_idr   is not None else persisted.get("realized_pnl_idr", 0.0)
    ur_pnl  = unrealized_pnl_idr if unrealized_pnl_idr is not None else persisted.get("unrealized_pnl_idr", 0.0)
    equity  = combined_equity_idr if combined_equity_idr is not None else persisted.get("combined_equity_idr", 0.0)
    cash    = available_cash_idr  if available_cash_idr  is not None else persisted.get("available_cash_idr", 0.0)
    positions = current_positions if current_positions is not None else persisted.get("current_positions", [])
    regime  = market_regime or _market_regime_from_state()

    minutes = _minutes_to_midnight_wib()
    # Daily color must reflect the live mark-to-market state, not just closed
    # trades. This keeps the whole council aware when open holdings are already
    # GREEN or in RECOVERY before the executor realizes the PnL.
    color   = _daily_color(float(r_pnl or 0.0) + float(ur_pnl or 0.0), equity)
    urgency = _urgency_level(minutes)

    ctx = {
        "wib_time":             now.strftime("%H:%M"),
        "wib_date":             str(now.date()),
        "minutes_to_midnight":  minutes,
        "daily_color":          color,
        "realized_pnl_idr":     r_pnl,
        "unrealized_pnl_idr":   ur_pnl,
        "combined_equity_idr":  equity,
        "available_cash_idr":   cash,
        "current_positions":    positions,
        "market_regime":        regime,
        "urgency_level":        urgency,
        "allowed_risk_mode":    _allowed_risk_mode(color, urgency),
        "required_trade_quality": _required_trade_quality(color, urgency),
        "exit_strictness":      _exit_strictness(color, urgency),
        "deadline_mode":        _deadline_mode(urgency, color),
    }

    logger.debug(
        f"[DailyCtx] {color} | urgency={urgency} | "
        f"deadline={minutes}m | PnL={r_pnl:+.0f} IDR | mode={ctx['allowed_risk_mode']}"
    )
    return ctx
