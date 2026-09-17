"""
KiBot V2 Backtest Friction & Execution Model.
Implements official regulatory costs, realistic maker/taker models,
probabilistic fill rate, and adverse selection penalties.
"""
from __future__ import annotations

from enum import Enum
import random
from typing import Dict, Any, Optional


class OrderType(Enum):
    MAKER = "maker"
    TAKER = "taker"


class StrategyType(Enum):
    MEAN_REVERSION = "mean_reversion"
    LEAD_LAG = "lead_lag"
    TREND_FOLLOWING = "trend_following"


# Friksi dasar per pair (dari dokumentasi baseline STRATEGY_EVALUATION_REVISED.md)
# Format: (maker_pct, taker_pct, spread_pct)
PAIR_FRICTION: Dict[str, tuple[float, float, float]] = {
    # pair: (maker_pct, taker_pct, spread_pct)
    "BTCIDR": (0.56, 0.78, 0.10),
    "ETHIDR": (0.56, 0.78, 0.10),
    "SOLIDR": (0.70, 0.95, 0.35),
    "AVAXIDR": (0.70, 0.95, 0.35),
}

# Fallback default untuk seluruh altcoin Indodax lainnya
DEFAULT_ALTCOIN_FRICTION: tuple[float, float, float] = (0.70, 0.95, 0.35)


def _normalize_pair(pair: str) -> str:
    """Normalizes symbol string to uppercase without separators."""
    return pair.upper().replace("/", "").replace("_", "").strip()


def get_roundtrip_friction(pair: str, order_type: OrderType) -> float:
    """
    Return friction % roundtrip.
    Maker = base maker friction (exchange fee + PPh + CFX + passive spread/slippage).
    Taker = base taker friction (higher exchange fee + PPh + CFX + spread crossing + market slippage).
    Falls back to DEFAULT_ALTCOIN_FRICTION for any unlisted altcoins.
    """
    clean_pair = _normalize_pair(pair)
    if clean_pair in PAIR_FRICTION:
        maker_pct, taker_pct, _ = PAIR_FRICTION[clean_pair]
    else:
        maker_pct, taker_pct, _ = DEFAULT_ALTCOIN_FRICTION

    if order_type == OrderType.MAKER:
        return maker_pct
    elif order_type == OrderType.TAKER:
        return taker_pct
    else:
        raise ValueError(f"Unknown OrderType: {order_type}")


def get_adverse_penalty(strategy: StrategyType) -> float:
    """
    Adverse selection penalty rate based on quantitative research:
    - Mean Reversion: 0.30 (30% discount on gross edge due to asymmetric limit order fill / falling knives)
    - Lead-Lag: 0.40 (40% discount on gross edge due to latency crowdedness / winner slip)
    - Trend Following: 0.20 (20% discount on gross edge due to trailing slippage)
    """
    if strategy == StrategyType.MEAN_REVERSION:
        return 0.30
    elif strategy == StrategyType.LEAD_LAG:
        return 0.40
    elif strategy == StrategyType.TREND_FOLLOWING:
        return 0.20
    else:
        raise ValueError(f"Unknown StrategyType: {strategy}")



def should_fill(
    order_type: OrderType,
    bar_at_entry: Dict[str, Any],
    random_seed: Optional[int] = None,
) -> bool:
    """
    Probabilistik fill decision.
    Maker: fill_rate = 0.85 (default). Taker: fill_rate = 1.0.
    Bar_at_entry = {open, high, low, close, volume}.
    Untuk realism tambahan: kalau bar_at_entry high-low range < 0.1%, make
    fill_rate lebih rendah (0.70) — karena pasar terlalu sunyi, limit order
    pasif jarang tersentuh.
    """
    if order_type == OrderType.TAKER:
        return True

    if order_type == OrderType.MAKER:
        fill_rate = 0.85

        # Check high-low volatility range
        try:
            high = float(bar_at_entry.get("high", 0.0))
            low = float(bar_at_entry.get("low", 0.0))
            ref_price = low if low > 0 else float(bar_at_entry.get("open", 0.0))

            if ref_price > 0:
                range_pct = ((high - low) / ref_price) * 100.0
                if range_pct < 0.1:  # Range < 0.1%
                    fill_rate = 0.70
        except (ValueError, TypeError):
            fill_rate = 0.85

        if random_seed is not None:
            rng = random.Random(random_seed)
            return rng.random() < fill_rate
        return random.random() < fill_rate

    raise ValueError(f"Unsupported OrderType: {order_type}")


def compute_pnl_after_costs(
    entry_price: float,
    exit_price: float,
    position_size_idr: float,
    pair: str,
    order_type: OrderType,
    strategy: StrategyType,
) -> Dict[str, float]:
    """
    Calculates detailed PnL after all regulatory friction, execution costs,
    and strategy-specific adverse selection penalties.

    Return dict:
    {
      "gross_pnl_idr": ...,
      "friction_idr": ...,
      "adverse_penalty_idr": ...,
      "net_pnl_idr": ...,
      "net_pnl_pct": ...,
    }
    """
    if entry_price <= 0:
        raise ValueError(f"entry_price must be > 0, got {entry_price}")
    if position_size_idr <= 0:
        raise ValueError(f"position_size_idr must be > 0, got {position_size_idr}")

    # Gross PnL
    price_return = (exit_price - entry_price) / entry_price
    gross_pnl_idr = position_size_idr * price_return

    # Friction cost
    friction_pct = get_roundtrip_friction(pair, order_type)
    friction_idr = position_size_idr * (friction_pct / 100.0)

    # Adverse selection penalty (haircut on gross positive edge)
    penalty_rate = get_adverse_penalty(strategy)
    if gross_pnl_idr > 0.0:
        adverse_penalty_idr = gross_pnl_idr * penalty_rate
    else:
        adverse_penalty_idr = 0.0

    # Net PnL
    net_pnl_idr = gross_pnl_idr - friction_idr - adverse_penalty_idr
    net_pnl_pct = (net_pnl_idr / position_size_idr) * 100.0

    return {
        "gross_pnl_idr": round(gross_pnl_idr, 4),
        "friction_idr": round(friction_idr, 4),
        "adverse_penalty_idr": round(adverse_penalty_idr, 4),
        "net_pnl_idr": round(net_pnl_idr, 4),
        "net_pnl_pct": round(net_pnl_pct, 6),
    }
