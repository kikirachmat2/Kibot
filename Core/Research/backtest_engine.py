"""Backtest Engine — fast vectorised single-pass historical simulation.

Given a list of OHLCV bars and a simple strategy configuration,
simulate trade entries and exits, returning a performance summary.

Design goals:
- Pure Python + stdlib only (no pandas required)
- DuckDB supported for large dataset queries (optional)
- Deterministic — same input always produces same output
- No external API calls
- Produces a BacktestResult with all key metrics
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Bar:
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Trade:
    entry_price: float
    exit_price: float
    entry_time: float
    exit_time: float
    side: str = "LONG"
    pnl_pct: float = 0.0
    pnl_abs: float = 0.0

    def __post_init__(self) -> None:
        if self.side == "LONG":
            self.pnl_pct = (self.exit_price - self.entry_price) / self.entry_price
        self.pnl_abs = self.pnl_pct  # fractional


@dataclass
class BacktestResult:
    strategy_id: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    expectancy_pct: float = 0.0     # EV per trade
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    elapsed_s: float = 0.0
    backtested_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 4),
            "avg_win_pct": round(self.avg_win_pct * 100, 3),
            "avg_loss_pct": round(self.avg_loss_pct * 100, 3),
            "expectancy_pct": round(self.expectancy_pct * 100, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 3),
            "total_return_pct": round(self.total_return_pct * 100, 3),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "profit_factor": round(self.profit_factor, 4),
            "elapsed_s": round(self.elapsed_s, 3),
            "backtested_at": self.backtested_at,
        }


def _compute_drawdown(equity_curve: List[float]) -> float:
    """Max drawdown from peak, as a positive fraction."""
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_sharpe(returns: List[float], periods_per_year: int = 252) -> float:
    """Annualised Sharpe ratio (risk-free = 0)."""
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def run_backtest(
    bars: List[Bar],
    *,
    strategy_id: str = "default",
    take_profit_pct: float = 0.015,    # 1.5%
    stop_loss_pct: float = 0.008,      # 0.8%
    fee_pct: float = 0.003,            # 0.3% per leg
    entry_signal_fn: Optional[Any] = None,  # callable(bar, history) -> bool
    lookback: int = 20,
) -> BacktestResult:
    """Single-pass backtest simulation.

    Args:
        bars: Chronologically sorted list of Bar objects.
        strategy_id: Identifier for this backtest run.
        take_profit_pct: Target profit fraction from entry.
        stop_loss_pct: Stop loss fraction from entry.
        fee_pct: One-way fee fraction (applied twice per trade).
        entry_signal_fn: Optional callable(bar, history_bars) -> bool.
            Defaults to a simple momentum signal (close > SMA20).
        lookback: Lookback window for default momentum signal.
    """
    t0 = time.time()
    result = BacktestResult(strategy_id=strategy_id)

    if len(bars) < lookback + 1:
        result.elapsed_s = time.time() - t0
        return result

    # Default entry: close crossed above SMA(lookback)
    def _default_signal(bar: Bar, hist: List[Bar]) -> bool:
        if len(hist) < lookback:
            return False
        sma = sum(b.close for b in hist[-lookback:]) / lookback
        prev_close = hist[-1].close if hist else bar.open
        return prev_close < sma <= bar.close

    signal_fn = entry_signal_fn or _default_signal

    in_trade = False
    entry_price = 0.0
    entry_time = 0.0
    equity_curve: List[float] = [1.0]
    returns: List[float] = []
    gross_wins = 0.0
    gross_losses = 0.0

    for i, bar in enumerate(bars):
        history = bars[max(0, i - lookback): i]

        if not in_trade:
            if signal_fn(bar, history):
                in_trade = True
                entry_price = bar.close * (1 + fee_pct)  # slippage + fee on entry
                entry_time = bar.timestamp
        else:
            # Check exit conditions
            tp_price = entry_price * (1 + take_profit_pct)
            sl_price = entry_price * (1 - stop_loss_pct)

            exit_price = None
            if bar.high >= tp_price:
                exit_price = tp_price
            elif bar.low <= sl_price:
                exit_price = sl_price

            if exit_price is not None:
                exit_net = exit_price * (1 - fee_pct)
                pnl = (exit_net - entry_price) / entry_price

                trade = Trade(
                    entry_price=entry_price,
                    exit_price=exit_net,
                    entry_time=entry_time,
                    exit_time=bar.timestamp,
                    pnl_pct=pnl,
                    pnl_abs=pnl,
                )
                result.trades.append(trade)

                if pnl >= 0:
                    result.winning_trades += 1
                    gross_wins += pnl
                else:
                    result.losing_trades += 1
                    gross_losses += abs(pnl)

                returns.append(pnl)
                equity_curve.append(equity_curve[-1] * (1 + pnl))
                in_trade = False

    # --- Aggregate ---
    result.total_trades = result.winning_trades + result.losing_trades
    if result.total_trades == 0:
        result.elapsed_s = time.time() - t0
        return result

    result.win_rate = result.winning_trades / result.total_trades
    wins = [t.pnl_pct for t in result.trades if t.pnl_pct >= 0]
    losses = [t.pnl_pct for t in result.trades if t.pnl_pct < 0]
    result.avg_win_pct = sum(wins) / len(wins) if wins else 0.0
    result.avg_loss_pct = abs(sum(losses) / len(losses)) if losses else 0.0
    result.expectancy_pct = (
        result.win_rate * result.avg_win_pct
        - (1 - result.win_rate) * result.avg_loss_pct
    )
    result.total_return_pct = equity_curve[-1] - 1.0
    result.max_drawdown_pct = _compute_drawdown(equity_curve)
    result.sharpe_ratio = _compute_sharpe(returns)
    result.profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf")
    result.elapsed_s = time.time() - t0
    return result


def bars_from_dicts(raw: List[Dict[str, Any]]) -> List[Bar]:
    """Convert list of OHLCV dicts to Bar objects."""
    return [
        Bar(
            timestamp=float(d.get("t") or d.get("timestamp") or 0),
            open=float(d.get("o") or d.get("open") or 0),
            high=float(d.get("h") or d.get("high") or 0),
            low=float(d.get("l") or d.get("low") or 0),
            close=float(d.get("c") or d.get("close") or 0),
            volume=float(d.get("v") or d.get("volume") or 0),
        )
        for d in raw
        if d
    ]
