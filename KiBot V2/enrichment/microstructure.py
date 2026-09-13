"""
Indodax Orderbook Microstructure & Real Market Impact Analyzer.
Ported and streamlined from KiBot V1 Core/Intelligence/indodax_microstructure.py.

Replaces static 0.1% slippage assumptions with realistic depth-weighted fill simulation (VWAP):
1. Calculates real-time bid-ask spread and spread percentage.
2. Simulates walk-the-book market impact across orderbook levels.
3. Solves partial depth failure (GAP-01 pre-trade check): rejects orders if available liquidity < target notional.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

from config import settings

logger = logging.getLogger("KiBotV2.Microstructure")


@dataclass
class MicrostructureAnalysis:
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread_idr: float = 0.0
    spread_pct: float = 0.0
    avg_fill_price: float = 0.0
    slippage_pct: float = 0.0
    total_depth_idr: float = 0.0
    is_depth_sufficient: bool = False
    depth_score: float = 0.0
    pass_liquidity: bool = False
    reason: str = ""


class IndodaxMicrostructureAnalyzer:
    """
    Simulates actual orderbook execution against real Indodax market depth.
    """
    def __init__(self, max_allowed_slippage_pct: float = 1.0, max_allowed_spread_pct: float = 1.5):
        self.max_allowed_slippage_pct = max_allowed_slippage_pct
        self.max_allowed_spread_pct = max_allowed_spread_pct

    def analyze_orderbook(
        self,
        orderbook: Dict[str, Any],
        target_notional_idr: float,
        side: str = "BUY",
    ) -> MicrostructureAnalysis:
        """
        Analyze orderbook depth to calculate spread, slippage, and VWAP execution price.
        
        Args:
            orderbook: dict containing "bids"/"buy" and "asks"/"sell" lists of [price, amount]
            target_notional_idr: order size in IDR
            side: 'BUY' (walks asks) or 'SELL' (walks bids)
        """
        res = MicrostructureAnalysis()
        
        if target_notional_idr <= 0:
            res.reason = "INVALID_ZERO_OR_NEGATIVE_NOTIONAL"
            res.is_depth_sufficient = False
            res.pass_liquidity = False
            return res

        if not orderbook or not isinstance(orderbook, dict):
            res.reason = "EMPTY_OR_MALFORMED_ORDERBOOK"
            return res

        bids = orderbook.get("bids", orderbook.get("buy", []))
        asks = orderbook.get("asks", orderbook.get("sell", []))

        if not bids or not asks:
            res.reason = "INSUFFICIENT_LEVELS_EMPTY_BIDS_OR_ASKS"
            return res

        try:
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
        except (IndexError, ValueError, TypeError) as exc:
            res.reason = f"CORRUPTED_BOOK_LEVELS: {exc}"
            return res

        if best_bid <= 0 or best_ask <= 0:
            res.reason = "INVALID_ZERO_PRICE_IN_BOOK"
            return res

        res.best_bid = best_bid
        res.best_ask = best_ask
        res.spread_idr = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2.0
        res.spread_pct = (res.spread_idr / mid_price) * 100.0

        # Calculate Depth Score (cumulative volume in top 10 price levels)
        top10_depth = 0.0
        for a in asks[:10]:
            try:
                top10_depth += float(a[0]) * float(a[1])
            except (IndexError, ValueError, TypeError):
                pass
        for b in bids[:10]:
            try:
                top10_depth += float(b[0]) * float(b[1])
            except (IndexError, ValueError, TypeError):
                pass
        res.depth_score = top10_depth

        # Walk the book according to order side
        book_levels = asks if side.upper() == "BUY" else bids
        base_ref_price = best_ask if side.upper() == "BUY" else best_bid

        total_idr_filled = 0.0
        total_coins_filled = 0.0
        cumulative_depth_idr = 0.0

        for level in book_levels:
            try:
                lvl_price = float(level[0])
                lvl_amount = float(level[1])
            except (IndexError, ValueError, TypeError):
                continue

            lvl_volume_idr = lvl_price * lvl_amount
            cumulative_depth_idr += lvl_volume_idr

            remaining_idr = target_notional_idr - total_idr_filled
            if remaining_idr > 0:
                fill_idr = min(remaining_idr, lvl_volume_idr)
                fill_coins = fill_idr / lvl_price
                total_idr_filled += fill_idr
                total_coins_filled += fill_coins

        res.total_depth_idr = cumulative_depth_idr

        # GAP-01 Pre-trade check: Does book have enough liquidity to fill the entire target notional?
        if total_idr_filled < (target_notional_idr - 1.0):  # allow 1 IDR rounding
            res.is_depth_sufficient = False
            res.reason = (
                f"INSUFFICIENT_DEPTH: Target Rp {target_notional_idr:,.0f} > Available Rp {cumulative_depth_idr:,.0f} "
                f"(Fillable: {(total_idr_filled/target_notional_idr)*100:.1f}%)"
            )
            return res

        res.is_depth_sufficient = True

        if total_coins_filled > 0:
            avg_fill_price = total_idr_filled / total_coins_filled
            res.avg_fill_price = avg_fill_price
            if side.upper() == "BUY":
                res.slippage_pct = max(0.0, ((avg_fill_price - base_ref_price) / base_ref_price) * 100.0)
            else:
                res.slippage_pct = max(0.0, ((base_ref_price - avg_fill_price) / base_ref_price) * 100.0)

        # Liquidity pass evaluation
        if res.spread_pct > self.max_allowed_spread_pct:
            res.pass_liquidity = False
            res.reason = f"SPREAD_TOO_WIDE: {res.spread_pct:.2f}% > Max {self.max_allowed_spread_pct:.2f}%"
            return res

        if res.slippage_pct > self.max_allowed_slippage_pct:
            res.pass_liquidity = False
            res.reason = f"SLIPPAGE_TOO_HIGH: {res.slippage_pct:.2f}% > Max {self.max_allowed_slippage_pct:.2f}%"
            return res

        res.pass_liquidity = True
        res.reason = "ORDERBOOK_LIQUIDITY_NOMINAL"
        return res


microstructure_analyzer = IndodaxMicrostructureAnalyzer()
