"""
Exit Plan Engine
=================
Generates a complete, per-trade exit plan at the moment of buy mandate.
Contract: PUMP_LIFECYCLE_STRATEGY.md §5, §6, §15.4

Every entry must have an exit plan. No executor may receive a buy mandate
without a concrete exit-aware scenario.

Exit plan is stored at: state/exit_plans/{order_id}.json
"""

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("ExitPlan")

STATE_DIR  = Path(__file__).resolve().parent.parent.parent / "state"
PLANS_DIR  = STATE_DIR / "exit_plans"

# ─────────────────────────────────────────────
# Default parameters (§5, §6)
# ─────────────────────────────────────────────
FEE_ROUNDTRIP_PCT     = 0.0102     # 1.02% default Indodax maker+taker roundtrip
HARD_STOP_DEFAULT_PCT = 2.5        # §5: hard stop below entry
BREAKEVEN_BUFFER_PCT  = 0.3        # move stop to breakeven after this profit above fees
PARTIAL_TP_DEFAULT    = 0.8        # take 50% off at 0.8% profit
PARTIAL_TP_FRACTION   = 0.50       # sell 50% of position for partial TP
MAX_HOLD_DEFAULT_MIN  = 120        # 2 hours max hold

# §6: Trailing profit schedule (threshold_pct → trail_pct)
DEFAULT_TRAILING_SCHEDULE = [
    (1.2, 0.6),    # above +1.2%  → trail with 0.6% buffer
    (2.0, 0.8),    # above +2.0%  → trail with 0.8% buffer
    (4.0, 1.5),    # above +4.0%  → trail with 1.5% buffer
    (8.0, 2.5),    # above +8.0%  → trail aggressively with 2.5% buffer
]


def _lifecycle_to_exit_params(lifecycle: str, daily_color: str, urgency: str) -> dict:
    """
    §5: Exit parameters depend on lifecycle stage + daily context.
    IGNITION/CONFIRMATION  → normal params
    RIDE / LOCAL           → tighter params (faster breakeven, earlier partial TP)
    DISTRIBUTION           → immediate exit triggers
    """
    params = {
        "hard_stop_pct":            HARD_STOP_DEFAULT_PCT,
        "breakeven_after_pct":      FEE_ROUNDTRIP_PCT * 100 + BREAKEVEN_BUFFER_PCT,
        "partial_take_profit_pct":  PARTIAL_TP_DEFAULT,
        "partial_take_profit_fraction": PARTIAL_TP_FRACTION,
        "trailing_schedule":        DEFAULT_TRAILING_SCHEDULE,
        "max_hold_minutes":         MAX_HOLD_DEFAULT_MIN,
    }

    # RIDE / LOCAL pumps: tighter everything (§12.2.3)
    if lifecycle in ("RIDE", "LOCAL_IGNITION", "LOCAL_CONFIRMATION", "LOCAL_BLOWOFF"):
        params["hard_stop_pct"]           = 1.5
        params["breakeven_after_pct"]     = FEE_ROUNDTRIP_PCT * 100 + 0.15
        params["partial_take_profit_pct"] = 0.5
        params["partial_take_profit_fraction"] = 0.60
        params["max_hold_minutes"]        = 45
        params["trailing_schedule"] = [
            (0.8, 0.4),
            (1.5, 0.6),
            (3.0, 1.0),
        ]

    # DISTRIBUTION: very aggressive exit
    elif lifecycle in ("DISTRIBUTION", "LOCAL_TRAP", "TRAP"):
        params["hard_stop_pct"]           = 1.0
        params["breakeven_after_pct"]     = FEE_ROUNDTRIP_PCT * 100 + 0.05
        params["partial_take_profit_pct"] = 0.3
        params["partial_take_profit_fraction"] = 0.75
        params["max_hold_minutes"]        = 20

    # GREEN + deadline: tighten everything (§9, §10)
    if daily_color == "GREEN" and urgency in ("HIGH", "CRITICAL"):
        params["hard_stop_pct"]           = min(params["hard_stop_pct"], 1.2)
        params["partial_take_profit_pct"] = min(params["partial_take_profit_pct"], 0.4)
        params["partial_take_profit_fraction"] = max(params["partial_take_profit_fraction"], 0.65)
        params["max_hold_minutes"]        = min(params["max_hold_minutes"], 30)

    return params


def _distribution_exit_rules(lifecycle: str, spread_pct: Optional[float]) -> dict:
    """
    §5: distribution_exit_rules — when to bail regardless of TP schedule.
    """
    return {
        "exit_if_obi_below":       -0.10,   # negative OBI = sellers dominating
        "exit_if_spread_above_pct": max(spread_pct * 3 if spread_pct else 2.0, 2.0),
        "exit_if_vol_collapse":    True,     # volume drops >70% vs entry
        "exit_on_lifecycle_change": ["DISTRIBUTION", "TRAP", "LOCAL_BLOWOFF", "LOCAL_TRAP"],
    }


def build_exit_plan(
    signal: Dict,
    daily_context: Dict,
    capital_state: str,
    pair_memory: Optional[Dict] = None,
    order_id: Optional[str] = None,
) -> Dict:
    """
    Build a complete exit plan for a given signal.

    Args:
        signal:        Scanner signal dict (must have lifecycle, price, spread_pct)
        daily_context: From daily_context.get_daily_context()
        capital_state: From risk_gate.get_capital_state()["capital_state"]
        pair_memory:   From learning_engine.get_pair_stats() (optional)
        order_id:      If provided, plan is saved to state/exit_plans/{order_id}.json

    Returns:
        Exit plan dict per §5 spec.
    """
    lifecycle   = signal.get("lifecycle", signal.get("pump_stage", "IGNITION"))
    entry_price = float(signal.get("price_idr", signal.get("price", 0)))
    spread_pct  = float(signal.get("spread_pct") or 0.0)
    confidence  = float(signal.get("confidence", 0.65))

    daily_color = daily_context.get("daily_color", "FLAT")
    urgency     = daily_context.get("urgency_level", "LOW")
    deadline_mode = daily_context.get("deadline_mode", "PATIENT")
    minutes_left = daily_context.get("minutes_to_midnight", 480)

    params = _lifecycle_to_exit_params(lifecycle, daily_color, urgency)

    # §10: Cap max_hold to available time before midnight
    params["max_hold_minutes"] = min(params["max_hold_minutes"], max(15, minutes_left - 10))

    # Pair memory adjustments (§12)
    if pair_memory:
        verdict = pair_memory.get("historian_verdict", "UNKNOWN")
        if verdict == "TRAP_PRONE":
            params["hard_stop_pct"] = min(params["hard_stop_pct"], 1.5)
            params["partial_take_profit_fraction"] = max(params["partial_take_profit_fraction"], 0.65)
        elif verdict == "GOOD":
            # trusted pair → allow slightly wider trail
            params["hard_stop_pct"] = min(params["hard_stop_pct"] * 1.1, 3.0)

    plan = {
        "order_id":                     order_id or f"plan_{int(time.time()*1000)}",
        "pair":                         signal.get("symbol", "UNKNOWN"),
        "entry_price":                  entry_price,
        "lifecycle":                    lifecycle,
        "hard_stop_pct":                round(params["hard_stop_pct"], 3),
        "hard_stop_price":              round(entry_price * (1 - params["hard_stop_pct"] / 100), 8) if entry_price > 0 else 0,
        "breakeven_after_pct":          round(params["breakeven_after_pct"], 3),
        "partial_take_profit_pct":      round(params["partial_take_profit_pct"], 3),
        "partial_take_profit_fraction": round(params["partial_take_profit_fraction"], 3),
        "trailing_profit_schedule":     params["trailing_schedule"],
        "max_hold_minutes":             params["max_hold_minutes"],
        "distribution_exit_rules":      _distribution_exit_rules(lifecycle, spread_pct),
        "deadline_mode":                deadline_mode,
        "daily_color":                  daily_color,
        "urgency_level":                urgency,
        "capital_state":                capital_state,
        "created_at":                   int(time.time()),
        "plan_version":                 "2.0",
    }

    # Persist to disk
    if order_id:
        _save_plan(plan)

    logger.info(
        f"[ExitPlan] {plan['pair']} | lifecycle={lifecycle} | "
        f"stop={plan['hard_stop_pct']}% | TP={plan['partial_take_profit_pct']}% | "
        f"maxhold={plan['max_hold_minutes']}m | deadline={deadline_mode}"
    )
    return plan


def _save_plan(plan: Dict) -> None:
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    path = PLANS_DIR / f"{plan['order_id']}.json"
    tmp  = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(plan, indent=2))
    tmp.replace(path)


def load_plan(order_id: str) -> Optional[Dict]:
    """Load an exit plan by order_id."""
    path = PLANS_DIR / f"{order_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        logger.error(f"[ExitPlan] Failed to load plan {order_id}: {e}")
        return None


def check_trailing_stop(
    plan: Dict,
    current_price: float,
    peak_price: float,
) -> Dict:
    """
    Check if trailing stop should trigger based on current price vs peak.

    Returns:
      {"should_exit": bool, "reason": str, "trail_stop_price": float}
    """
    entry = float(plan.get("entry_price", 0))
    if entry <= 0 or current_price <= 0:
        return {"should_exit": False, "reason": "invalid_price", "trail_stop_price": 0}

    unrealized_pct = (current_price - entry) / entry * 100
    peak_pct       = (peak_price - entry) / entry * 100

    # Hard stop
    hard_stop_pct = float(plan.get("hard_stop_pct", 2.5))
    if unrealized_pct < -hard_stop_pct:
        return {
            "should_exit":     True,
            "reason":          f"HARD_STOP ({unrealized_pct:.2f}% < -{hard_stop_pct}%)",
            "trail_stop_price": entry * (1 - hard_stop_pct / 100),
        }

    # Trailing schedule
    schedule = plan.get("trailing_profit_schedule", DEFAULT_TRAILING_SCHEDULE)
    active_trail_pct = None
    for threshold, trail_buffer in sorted(schedule, key=lambda x: x[0], reverse=True):
        if peak_pct >= threshold:
            active_trail_pct = trail_buffer
            break

    if active_trail_pct is not None:
        trail_stop = peak_price * (1 - active_trail_pct / 100)
        if current_price <= trail_stop:
            return {
                "should_exit":      True,
                "reason":           f"TRAILING_STOP (peak={peak_pct:.2f}%, trail={active_trail_pct}%)",
                "trail_stop_price": round(trail_stop, 8),
            }
        return {
            "should_exit":      False,
            "reason":           "trailing_active",
            "trail_stop_price": round(trail_stop, 8),
        }

    return {"should_exit": False, "reason": "below_trailing_threshold", "trail_stop_price": 0}


def check_partial_tp(plan: Dict, current_price: float, already_partial: bool = False) -> Dict:
    """
    Check if partial take-profit should trigger.

    Returns:
      {"should_partial": bool, "fraction": float, "reason": str}
    """
    if already_partial:
        return {"should_partial": False, "fraction": 0, "reason": "already_partial"}

    entry   = float(plan.get("entry_price", 0))
    tp_pct  = float(plan.get("partial_take_profit_pct", 0.8))
    fraction = float(plan.get("partial_take_profit_fraction", 0.5))

    if entry <= 0:
        return {"should_partial": False, "fraction": 0, "reason": "invalid_entry"}

    unrealized_pct = (current_price - entry) / entry * 100
    if unrealized_pct >= tp_pct:
        return {
            "should_partial": True,
            "fraction":       fraction,
            "reason":         f"PARTIAL_TP ({unrealized_pct:.2f}% >= {tp_pct}%)",
        }
    return {"should_partial": False, "fraction": 0, "reason": f"below_partial_tp ({unrealized_pct:.2f}%)"}
