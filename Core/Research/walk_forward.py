"""Walk-Forward Engine — rolling out-of-sample validation to detect overfitting.

Splits historical bars into N folds. Each fold trains on in-sample (IS)
data and evaluates on out-of-sample (OOS) data. The OOS expectancy
across all folds is the "walk-forward expectancy" — a more honest
estimate of live performance than a single in-sample backtest.

Rule: A strategy is considered viable only if:
  - OOS win rate >= 45%
  - OOS expectancy >= 0%  (at minimum break-even after fees)
  - Efficiency ratio (OOS/IS expectancy) >= 0.50
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .backtest_engine import BacktestResult, Bar, run_backtest


# Viability thresholds
MIN_OOS_WIN_RATE = 0.45
MIN_OOS_EXPECTANCY = 0.0
MIN_EFFICIENCY_RATIO = 0.50


@dataclass
class WalkForwardFold:
    fold_index: int
    is_bars: int
    oos_bars: int
    is_result: BacktestResult
    oos_result: BacktestResult
    efficiency_ratio: float   # oos_expectancy / is_expectancy


@dataclass
class WalkForwardResult:
    strategy_id: str
    n_folds: int
    folds: List[WalkForwardFold] = field(default_factory=list)
    oos_win_rate: float = 0.0
    oos_expectancy_pct: float = 0.0
    oos_max_drawdown_pct: float = 0.0
    is_expectancy_pct: float = 0.0
    efficiency_ratio: float = 0.0
    viable: bool = False
    rejection_reasons: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "n_folds": self.n_folds,
            "oos_win_rate": round(self.oos_win_rate, 4),
            "oos_expectancy_pct": round(self.oos_expectancy_pct * 100, 4),
            "oos_max_drawdown_pct": round(self.oos_max_drawdown_pct * 100, 3),
            "is_expectancy_pct": round(self.is_expectancy_pct * 100, 4),
            "efficiency_ratio": round(self.efficiency_ratio, 4),
            "viable": self.viable,
            "rejection_reasons": self.rejection_reasons,
            "elapsed_s": round(self.elapsed_s, 3),
            "evaluated_at": self.evaluated_at,
            "fold_summary": [
                {
                    "fold": f.fold_index,
                    "is_trades": f.is_result.total_trades,
                    "oos_trades": f.oos_result.total_trades,
                    "is_exp_pct": round(f.is_result.expectancy_pct * 100, 3),
                    "oos_exp_pct": round(f.oos_result.expectancy_pct * 100, 3),
                    "efficiency": round(f.efficiency_ratio, 3),
                }
                for f in self.folds
            ],
        }


def run_walk_forward(
    bars: List[Bar],
    *,
    strategy_id: str = "default",
    n_folds: int = 5,
    is_fraction: float = 0.70,       # 70% IS, 30% OOS per fold
    take_profit_pct: float = 0.015,
    stop_loss_pct: float = 0.008,
    fee_pct: float = 0.003,
    entry_signal_fn: Optional[Callable] = None,
    lookback: int = 20,
) -> WalkForwardResult:
    """Run walk-forward validation.

    Splits bars into n_folds anchored windows. Each window grows by
    (total_bars / n_folds) on each fold — anchored IS expands, OOS fixed.
    """
    t0 = time.time()
    result = WalkForwardResult(strategy_id=strategy_id, n_folds=n_folds)

    n = len(bars)
    min_bars_needed = lookback * 3
    if n < min_bars_needed:
        result.rejection_reasons.append(
            f"Insufficient bars: {n} < minimum {min_bars_needed}"
        )
        result.elapsed_s = time.time() - t0
        return result

    fold_size = n // n_folds
    oos_size = max(1, int(fold_size * (1 - is_fraction)))

    oos_win_totals: List[float] = []
    oos_exp_totals: List[float] = []
    is_exp_totals: List[float] = []
    oos_dd_totals: List[float] = []

    for fold_i in range(n_folds):
        # Anchored window: IS starts at 0, OOS = next slice
        is_end = fold_size * (fold_i + 1)
        oos_start = is_end
        oos_end = min(n, oos_start + oos_size)

        if oos_start >= n:
            break

        is_bars_slice = bars[: is_end]
        oos_bars_slice = bars[oos_start: oos_end]

        if len(is_bars_slice) < lookback + 1 or len(oos_bars_slice) < 2:
            continue

        kwargs = dict(
            strategy_id=f"{strategy_id}_fold{fold_i}",
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            fee_pct=fee_pct,
            entry_signal_fn=entry_signal_fn,
            lookback=lookback,
        )

        is_res = run_backtest(is_bars_slice, **kwargs)
        oos_res = run_backtest(oos_bars_slice, **kwargs)

        if is_res.expectancy_pct != 0:
            eff = oos_res.expectancy_pct / is_res.expectancy_pct
        else:
            eff = 0.0

        fold = WalkForwardFold(
            fold_index=fold_i,
            is_bars=len(is_bars_slice),
            oos_bars=len(oos_bars_slice),
            is_result=is_res,
            oos_result=oos_res,
            efficiency_ratio=eff,
        )
        result.folds.append(fold)

        if oos_res.total_trades > 0:
            oos_win_totals.append(oos_res.win_rate)
            oos_exp_totals.append(oos_res.expectancy_pct)
            is_exp_totals.append(is_res.expectancy_pct)
            oos_dd_totals.append(oos_res.max_drawdown_pct)

    if not oos_exp_totals:
        result.rejection_reasons.append("No OOS trades generated across any fold")
        result.elapsed_s = time.time() - t0
        return result

    result.oos_win_rate = sum(oos_win_totals) / len(oos_win_totals)
    result.oos_expectancy_pct = sum(oos_exp_totals) / len(oos_exp_totals)
    result.is_expectancy_pct = sum(is_exp_totals) / len(is_exp_totals)
    result.oos_max_drawdown_pct = max(oos_dd_totals) if oos_dd_totals else 0.0
    if result.is_expectancy_pct != 0:
        result.efficiency_ratio = result.oos_expectancy_pct / result.is_expectancy_pct
    else:
        result.efficiency_ratio = 0.0

    # Viability check
    viable = True
    if result.oos_win_rate < MIN_OOS_WIN_RATE:
        viable = False
        result.rejection_reasons.append(
            f"OOS win rate {result.oos_win_rate:.1%} < {MIN_OOS_WIN_RATE:.0%}"
        )
    if result.oos_expectancy_pct < MIN_OOS_EXPECTANCY:
        viable = False
        result.rejection_reasons.append(
            f"OOS expectancy {result.oos_expectancy_pct*100:.3f}% < {MIN_OOS_EXPECTANCY*100:.2f}%"
        )
    if result.efficiency_ratio < MIN_EFFICIENCY_RATIO:
        viable = False
        result.rejection_reasons.append(
            f"Efficiency ratio {result.efficiency_ratio:.2f} < {MIN_EFFICIENCY_RATIO}"
        )

    result.viable = viable
    result.n_folds = len(result.folds)
    result.elapsed_s = time.time() - t0
    return result
