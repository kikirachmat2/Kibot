"""
KiBot V2 — Cross-Asset Dual Momentum Engine.
Ported and adapted from suenot/029-cross-asset-momentum.
Combines:
1. Time-Series Momentum (TSM): Absolute trend filter (asset return > hurdle/benchmark).
2. Cross-Sectional Momentum (CSM): Relative ranking across the Indodax crypto universe.
3. Drawdown Protection: Rejects assets with excessive peak-to-trough drawdowns or extreme volatility.
"""
from __future__ import annotations

from typing import Dict, List, Tuple, Any, Optional
import numpy as np


class DualMomentumEngine:
    def __init__(
        self,
        hurdle_rate_pct: float = 0.0,
        max_drawdown_limit_pct: float = 12.0,
        top_csm_quantile: float = 0.30,
    ):
        self.hurdle_rate_pct = hurdle_rate_pct
        self.max_drawdown_limit_pct = max_drawdown_limit_pct
        self.top_csm_quantile = top_csm_quantile

    def calc_tsm(self, price_series: List[float]) -> float:
        """Calculates Time-Series Momentum (% return over lookback)."""
        if not price_series or len(price_series) < 2:
            return 0.0
        start = float(price_series[0])
        end = float(price_series[-1])
        if start <= 0:
            return 0.0
        return (end - start) / start * 100.0

    def calc_max_drawdown(self, price_series: List[float]) -> float:
        """Calculates peak-to-trough drawdown % across series."""
        if not price_series or len(price_series) < 2:
            return 0.0
        prices = np.array(price_series, dtype=float)
        running_max = np.maximum.accumulate(prices)
        drawdowns = (running_max - prices) / (running_max + 1e-12) * 100.0
        return float(np.max(drawdowns))

    def evaluate_universe(
        self,
        universe_prices: Dict[str, List[float]],
        benchmark_prices: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates full universe with Dual Momentum:
        - Filters out assets failing TSM (negative return or < hurdle / benchmark).
        - Computes peak drawdown protection.
        - Ranks surviving assets via Cross-Sectional Momentum.
        """
        benchmark_return = self.calc_tsm(benchmark_prices) if benchmark_prices else 0.0
        effective_hurdle = max(self.hurdle_rate_pct, benchmark_return)

        tsm_scores: Dict[str, float] = {}
        drawdowns: Dict[str, float] = {}
        passed_tsm: Dict[str, float] = {}

        for sym, prices in universe_prices.items():
            ret = self.calc_tsm(prices)
            dd = self.calc_max_drawdown(prices)
            tsm_scores[sym] = ret
            drawdowns[sym] = dd

            # TSM Filter: Must exceed hurdle and stay within drawdown limit
            if ret > effective_hurdle and dd <= self.max_drawdown_limit_pct:
                passed_tsm[sym] = ret

        # Rank by Cross-Sectional Momentum (CSM)
        ranked_csm = sorted(passed_tsm.items(), key=lambda x: x[1], reverse=True)
        num_allowed = max(1, int(np.ceil(len(universe_prices) * self.top_csm_quantile)))
        top_selected = ranked_csm[:num_allowed]
        selected_symbols = [s[0] for s in top_selected]

        return {
            "effective_hurdle_pct": round(effective_hurdle, 2),
            "benchmark_return_pct": round(benchmark_return, 2),
            "all_tsm_scores": tsm_scores,
            "all_drawdowns": drawdowns,
            "passed_tsm_count": len(passed_tsm),
            "ranked_csm": ranked_csm,
            "selected_symbols": selected_symbols,
        }
