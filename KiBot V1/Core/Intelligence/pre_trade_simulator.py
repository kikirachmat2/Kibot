"""Pre-trade simulation gate for real-money Indodax entries."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, Iterable, List, Tuple


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_levels(rows: Iterable[Any]) -> List[Tuple[float, float]]:
    levels: List[Tuple[float, float]] = []
    for row in rows or []:
        try:
            price = _float(row[0])
            amount = _float(row[1])
            if price > 0 and amount > 0:
                levels.append((price, amount))
        except Exception:
            continue
    return levels


def _estimate_buy_fill(asks: List[Tuple[float, float]], budget_idr: float) -> Dict[str, float]:
    remaining = max(0.0, budget_idr)
    acquired = 0.0
    spent = 0.0
    for price, amount in sorted(asks, key=lambda x: x[0]):
        if remaining <= 0:
            break
        value = price * amount
        if value <= remaining:
            acquired += amount
            spent += value
            remaining -= value
        else:
            part = remaining / price
            acquired += part
            spent += remaining
            remaining = 0.0
            break
    avg_price = spent / acquired if acquired > 0 else 0.0
    return {
        "filled": acquired > 0 and remaining <= max(1.0, budget_idr * 0.02),
        "amount": acquired,
        "spent_idr": spent,
        "avg_price": avg_price,
        "unfilled_idr": remaining,
    }


def _estimate_sell_fill(bids: List[Tuple[float, float]], amount_coin: float) -> Dict[str, float]:
    remaining = max(0.0, amount_coin)
    sold = 0.0
    received = 0.0
    for price, amount in sorted(bids, key=lambda x: x[0], reverse=True):
        if remaining <= 0:
            break
        qty = min(remaining, amount)
        sold += qty
        received += qty * price
        remaining -= qty
    avg_price = received / sold if sold > 0 else 0.0
    return {
        "filled": sold > 0 and remaining <= max(1e-8, amount_coin * 0.02),
        "amount": sold,
        "received_idr": received,
        "avg_price": avg_price,
        "unsold_amount": remaining,
    }


from Core.Support.ki_config import KiConfig


async def simulate_pre_trade(
    gateway: Any,
    *,
    symbol: str,
    price: float,
    budget_idr: float,
    signal: Dict[str, Any] | None = None,
    fee_roundtrip_pct: float = KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT * 100.0,  # 0.61%
) -> Dict[str, Any]:
    """Return a PASS / REDUCE_SIZE / REJECT pre-trade simulation."""
    pair = str(symbol or "").lower().replace("/", "_")
    if "_" not in pair:
        pair = f"{pair}_idr"
    signal = signal or {}
    started = time.time()

    orderbook = await gateway.get_orderbook(pair)
    bids = _normalize_levels(orderbook.get("bids") or orderbook.get("buy") or [])
    asks = _normalize_levels(orderbook.get("asks") or orderbook.get("sell") or [])
    pair_info = await gateway.get_pair_info(pair)

    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    mid = ((best_bid + best_ask) / 2.0) if best_bid and best_ask else float(price or best_ask or best_bid or 0.0)
    spread_pct = ((best_ask - best_bid) / best_bid * 100.0) if best_bid and best_ask else 99.0

    min_base = _float(pair_info.get("trade_min_base_currency"), 10_000.0)
    min_coin = _float(pair_info.get("trade_min_traded_currency"), 0.0)
    buy_fill = _estimate_buy_fill(asks, budget_idr)
    amount = buy_fill["amount"]
    sell_fill = _estimate_sell_fill(bids, amount)

    entry_price_est = buy_fill["avg_price"] or best_ask or price
    exit_price_est = sell_fill["avg_price"] or best_bid or price
    slippage_entry_pct = ((entry_price_est - mid) / mid * 100.0) if mid else 99.0
    slippage_exit_pct = ((mid - exit_price_est) / mid * 100.0) if mid else 99.0
    one_tick_loss_pct = 0.0
    try:
        price_increment = _float(signal.get("price_increment"), 0.0)
        one_tick_loss_pct = (price_increment / max(entry_price_est, 1e-9)) * 100.0
    except Exception:
        one_tick_loss_pct = 0.0

    min_sellable_pass = (
        budget_idr >= min_base
        and amount > 0
        and (not min_coin or amount >= min_coin)
        and (amount * max(exit_price_est, 0.0)) >= min_base
    )
    partial_amount = amount * _float(signal.get("partial_take_profit_fraction"), 0.5)
    partial_tp_feasible = (
        partial_amount > 0
        and (not min_coin or partial_amount >= min_coin)
        and (partial_amount * max(exit_price_est, 0.0)) >= min_base
    )

    fee_cost_pct = fee_roundtrip_pct
    spread_cost_pct = max(0.0, spread_pct)
    slippage_pct = max(0.0, slippage_entry_pct) + max(0.0, slippage_exit_pct)
    breakeven_price = entry_price_est * (1 + (fee_cost_pct + max(0.0, slippage_pct)) / 100.0)

    reasons = []
    verdict = "PASS"
    if not bids or not asks:
        verdict = "REJECT"
        reasons.append("empty_orderbook")
    if not buy_fill["filled"]:
        verdict = "REJECT"
        reasons.append("entry_depth_insufficient")
    if not sell_fill["filled"]:
        verdict = "REJECT"
        reasons.append("exit_depth_insufficient")
    if spread_pct > _float(signal.get("max_spread_pct"), 1.2):
        verdict = "REJECT"
        reasons.append(f"spread_too_wide:{spread_pct:.2f}%")
    if not min_sellable_pass:
        verdict = "REJECT"
        reasons.append("minimum_sellable_failed")
    if slippage_pct > 2.0 and verdict != "REJECT":
        verdict = "REDUCE_SIZE"
        reasons.append(f"slippage_high:{slippage_pct:.2f}%")
    if one_tick_loss_pct > 3.0:
        verdict = "REJECT"
        reasons.append(f"one_tick_loss_too_high:{one_tick_loss_pct:.2f}%")

    return {
        "pair": pair,
        "symbol": symbol,
        "planned_value_idr": round(budget_idr, 2),
        "entry_price_est": round(entry_price_est, 8),
        "exit_price_est": round(exit_price_est, 8),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_cost_pct": round(spread_cost_pct, 4),
        "fee_cost_pct": round(fee_cost_pct, 4),
        "slippage_pct": round(slippage_pct, 4),
        "breakeven_price": round(breakeven_price, 8),
        "one_tick_loss_pct": round(one_tick_loss_pct, 4),
        "expected_amount": round(amount, 8),
        "min_base_idr": min_base,
        "min_coin": min_coin,
        "min_sellable_pass": bool(min_sellable_pass),
        "partial_tp_feasible": bool(partial_tp_feasible),
        "simulation_verdict": verdict,
        "reasons": reasons,
        "orderbook_age_s": round(time.time() - started, 3),
        "source": "INDODAX_ORDERBOOK_SIM",
    }


# Alias for backward compatibility
async def simulate_indodax_entry(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return await simulate_pre_trade(*args, **kwargs)
