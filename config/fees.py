"""KiBot V3 — Single Source of Truth for Indodax IDR Market (PRO) Trading Fees.

Imported directly from KiBot V2 (kikirachmat2/Kibot config/fees.py).
Source: Official Indodax app screenshot, IDR Market PRO, verified 2026-09-20.
Fee structure is ASYMMETRIC: Buy and Sell have different rates because
Indonesian crypto tax (PPh) applies only to SELL side (asset disposal).

Components per side:
  BUY  maker: Service 0.10% + Tax 0.00% + CFX 0.0111% = 0.1111%
  BUY  taker: Service 0.20% + Tax 0.00% + CFX 0.0111% = 0.2111%
  SELL maker: Service 0.10% + Tax 0.21% + CFX 0.0111% = 0.3211%
  SELL taker: Service 0.20% + Tax 0.21% + CFX 0.0111% = 0.4211%

Do NOT hardcode these numbers anywhere else. Always import from this module.
"""
from __future__ import annotations
from typing import NamedTuple


class FeeSchedule(NamedTuple):
    """Immutable fee schedule for one side of a trade (buy or sell)."""
    maker_pct: float   # % of notional deducted when using limit orders
    taker_pct: float   # % of notional deducted when using market orders


# ─── Official IDR Market PRO fee rates ───────────────────────────────────────

IDR_BUY_FEES = FeeSchedule(
    maker_pct=0.1111,   # Service 0.10% + CFX 0.0111% (no tax on buy)
    taker_pct=0.2111,   # Service 0.20% + CFX 0.0111%
)

IDR_SELL_FEES = FeeSchedule(
    maker_pct=0.3211,   # Service 0.10% + PPh 0.21% + CFX 0.0111%
    taker_pct=0.4211,   # Service 0.20% + PPh 0.21% + CFX 0.0111%
)

# ─── Roundtrip combinations (buy + sell) ─────────────────────────────────────

# Target: both sides as limit orders (best-case, normal market conditions)
ROUNDTRIP_MAKER_MAKER_PCT: float = IDR_BUY_FEES.maker_pct + IDR_SELL_FEES.maker_pct  # 0.4322%

# Worst-case: both sides as market orders (flash crash, urgent exit)
ROUNDTRIP_TAKER_TAKER_PCT: float = IDR_BUY_FEES.taker_pct + IDR_SELL_FEES.taker_pct  # 0.6322%

# Mixed: limit buy + market sell (urgent SL/forced exit, realistic for most events)
ROUNDTRIP_MAKER_TAKER_PCT: float = IDR_BUY_FEES.maker_pct + IDR_SELL_FEES.taker_pct  # 0.5322%

# ─── Exit type classification ─────────────────────────────────────────────────
URGENT_EXIT_REASONS: frozenset[str] = frozenset({
    "STOP_LOSS_BREACHED",
    "CHANDELIER_TRAILING_STOP_HIT",
    "BREAKEVEN_STOP_BREACHED",
    "MAX_HOLD_TIME_EXPIRED",
})

PATIENT_EXIT_REASONS: frozenset[str] = frozenset({
    "TAKE_PROFIT_TARGET_HIT",
    "SOFT_EXIT_3H_DRAWDOWN",
    "STAGNATION_DEAD_CAPITAL_EXIT",
    "MANUAL_EXIT",
})
