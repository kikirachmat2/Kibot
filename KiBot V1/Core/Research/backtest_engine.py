"""Backtest Engine — fast vectorised single-pass historical simulation.

Given a list of OHLCV bars and a strategy configuration, simulate trade entries
and exits, returning a performance summary.

Design goals:
- Pure Python + stdlib only (no pandas required)
- DuckDB supported for large dataset queries (optional)
- Deterministic — same input always produces same output
- No external API calls
- Produces a BacktestResult with all key metrics including exit_reasons breakdown
- Ground-truth signals supported via decision_journal / ground_truth_signals.json
- Line-by-line scanner replica (kibot_scanner_signal_fn) for parity with live engine
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("BacktestEngine")


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
    exit_reason: str = "TP"  # "TP", "SL", "TRAILING_STOP", "TIMEOUT"
    bars_held: int = 0

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
    exit_reasons: Dict[str, int] = field(default_factory=dict)
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
            "exit_reasons": dict(self.exit_reasons),
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
    fee_pct: float = 0.003,            # 0.3% per leg (0.6% roundtrip)
    max_hold_bars: Optional[int] = 8,  # Default 8 bars (2h on 15m candles); None = no timeout
    trailing_schedule: Optional[List[Tuple[float, float]]] = None,  # [(threshold_pct, buffer_pct)]
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
        max_hold_bars: Max bars to hold before exiting at market close (timeout).
            Default is 8 (corresponds to 2h timeout on 15m bars). Set None to disable.
        trailing_schedule: Optional list of (profit_pct, buffer_pct) pairs to ratchet stop loss.
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
    entry_bar_idx = 0
    current_stop = 0.0
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
                entry_bar_idx = i
                current_stop = entry_price * (1 - stop_loss_pct)
        else:
            bars_held = i - entry_bar_idx
            tp_price = entry_price * (1 + take_profit_pct)

            # Update trailing stop if schedule is provided
            if trailing_schedule and bar.high > entry_price:
                max_profit_pct = ((bar.high - entry_price) / entry_price) * 100.0
                best_stop = current_stop
                for threshold_pct, buffer_pct in trailing_schedule:
                    if max_profit_pct >= threshold_pct:
                        calc_stop = entry_price * (1.0 + ((threshold_pct - buffer_pct) / 100.0))
                        if calc_stop > best_stop:
                            best_stop = calc_stop
                if best_stop > current_stop:
                    current_stop = best_stop

            exit_price = None
            exit_reason = ""

            # Check exit conditions in order of price priority:
            # 1. Take profit target hit on bar high
            if bar.high >= tp_price:
                exit_price = tp_price
                exit_reason = "TP"
            # 2. Stop loss / trailing stop hit on bar low
            elif bar.low <= current_stop:
                exit_price = current_stop
                initial_stop = entry_price * (1 - stop_loss_pct)
                exit_reason = "TRAILING_STOP" if current_stop > initial_stop else "SL"
            # 3. Max hold time expired (timeout exit at close of bar)
            elif max_hold_bars is not None and bars_held >= max_hold_bars:
                exit_price = bar.close
                exit_reason = "TIMEOUT"

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
                    exit_reason=exit_reason,
                    bars_held=bars_held,
                )
                result.trades.append(trade)
                result.exit_reasons[exit_reason] = result.exit_reasons.get(exit_reason, 0) + 1

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


# ─────────────────────────────────────────────────────────────────────────────
# OPTION 3: Ground Truth Signal Integration (Primary Method)
# ─────────────────────────────────────────────────────────────────────────────

def load_ground_truth_signals(
    source_path: str = "state/ground_truth_signals.json",
    symbol_filter: Optional[str] = None,
    min_confidence: float = 0.0,
) -> Dict[str, List[Dict[str, Any]]]:
    """Load ground-truth BUY signals produced by KiBot Council from decision_journal.

    This represents the real historical decisions where the live KiBot system voted BUY.
    Using actual decisions avoids proxy/estimation bias.

    Args:
        source_path: Path to ground_truth_signals.json or a decision_journal directory.
        symbol_filter: Optional symbol to filter (e.g. "BTC/IDR").
        min_confidence: Minimum council confidence threshold.

    Returns:
        Dict mapping uppercase normalized pair symbol to list of signal dicts.
    """
    p = Path(source_path)
    if not p.is_absolute():
        root_dir = Path(__file__).resolve().parent.parent.parent
        p = root_dir / source_path

    signals_by_symbol: Dict[str, List[Dict[str, Any]]] = {}

    if p.is_file() and p.suffix == ".json":
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            for sig in data:
                sym = str(sig.get("symbol") or "").upper().strip()
                if not sym:
                    continue
                if symbol_filter and sym != symbol_filter.upper().strip():
                    continue
                conf = float(sig.get("confidence") or 0.0)
                if conf < min_confidence:
                    continue
                signals_by_symbol.setdefault(sym, []).append(sig)
    elif p.is_dir():
        for jsonl_file in sorted(p.glob("*.jsonl")):
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("event_type") == "COUNCIL_DECISION" and (
                            record.get("action") == "BUY" or record.get("decision_state") == "BUY"
                        ):
                            sig_data = record.get("source_signal") or {}
                            sym = str(sig_data.get("symbol") or record.get("ticker") or "").upper().strip()
                            if not sym:
                                continue
                            if symbol_filter and sym != symbol_filter.upper().strip():
                                continue
                            conf = float(record.get("confidence") or sig_data.get("confidence") or 0.0)
                            if conf < min_confidence:
                                continue
                            signals_by_symbol.setdefault(sym, []).append({
                                "ts": float(record.get("ts", 0)),
                                "symbol": sym,
                                "price": float(sig_data.get("price_idr") or sig_data.get("price") or 0),
                                "confidence": conf,
                                "score": float(record.get("decision_score", 0)),
                                "date_wib": record.get("date_wib"),
                            })
                    except Exception:
                        pass

    for sym in signals_by_symbol:
        signals_by_symbol[sym].sort(key=lambda s: s.get("ts", 0))

    return signals_by_symbol


def create_ground_truth_signal_fn(
    signals: List[Dict[str, Any]],
    tolerance_seconds: float = 900.0,
) -> Callable[[Bar, List[Bar]], bool]:
    """Create a signal function that fires when a ground truth signal timestamp falls within the bar.

    Args:
        signals: List of signal dicts for this specific pair.
        tolerance_seconds: Width of candle bar in seconds (e.g., 900s for 15m bars).
    """
    ts_list = sorted(float(s["ts"]) for s in signals if "ts" in s)

    def _signal(bar: Bar, hist: List[Bar]) -> bool:
        if not ts_list:
            return False
        # Bar spans [bar.timestamp, bar.timestamp + tolerance_seconds]
        idx = bisect.bisect_left(ts_list, bar.timestamp)
        if idx < len(ts_list) and ts_list[idx] <= bar.timestamp + tolerance_seconds:
            return True
        return False

    return _signal


# ─────────────────────────────────────────────────────────────────────────────
# OPTION 2: Line-by-Line KiBot Scanner Replica (Cross-Check Method)
# ─────────────────────────────────────────────────────────────────────────────
# Extracted directly from Core/Scanner/ki_indodax_smallcap_scanner.py.
#
# VALIDATION LINE-BY-LINE & PROXY DOCUMENTATION:
# - EXACT MATCHES:
#   * Thresholds imported directly from ki_indodax_smallcap_scanner:
#     VOLUME_SPIKE_MULTIPLIER (1.35), PRICE_CHANGE_MIN_PCT (0.35),
#     All 7 setup rules: CONTINUATION, MATURE, PULLBACK, LATE_RECLAIM,
#     RANGE_BREAK, SUPPORT_BOUNCE, PIVOT_RECLAIM.
#   * Scoring weights: momentum (0.28), volume (0.22), obi (0.16),
#     persistence (0.10), acceleration (0.04), plus bonuses.
#   * Official obi_proxy formula from scanner lines 416-427:
#     0.22 + 0.20*trend + 0.18*range + 0.16*persistence + 0.12*volume.
#
# - PROXIES / LIMITATIONS (Explicitly Documented):
#   1. Orderbook Depth: Historical OHLCV does not contain top-10 bid/ask queue.
#      The scanner's official fallback `obi_proxy` is used instead.
#   2. Persistence: Live scanner calculates 30-minute tick persistence; backtest
#      calculates green candle ratio over the preceding bars.
#   3. Day High/Low: Calculated over a rolling 96-bar window (24h on 15m candles)
#      instead of the Indodax 24h rolling clock ticker.
# ─────────────────────────────────────────────────────────────────────────────

try:
    from Core.Scanner.ki_indodax_smallcap_scanner import (
        VOLUME_SPIKE_MULTIPLIER,
        PRICE_CHANGE_MIN_PCT,
        OBI_MIN,
        CONTINUATION_MIN_RUNUP_PCT,
        CONTINUATION_MIN_RANGE_POSITION,
        CONTINUATION_MAX_DIST_TO_HIGH_PCT,
        CONTINUATION_MIN_VOLUME_RATIO,
        MATURE_MIN_RUNUP_PCT,
        MATURE_MIN_RANGE_POSITION,
        MATURE_MAX_DIST_TO_HIGH_PCT,
        MATURE_MIN_VOLUME_RATIO,
        PULLBACK_MIN_RUNUP_PCT,
        PULLBACK_MIN_RANGE_POSITION,
        PULLBACK_MAX_DIST_TO_HIGH_PCT,
        PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT,
        PULLBACK_MIN_VOLUME_RATIO,
        PULLBACK_MIN_RECLAIM_SCORE,
        LATE_RECLAIM_MIN_RUNUP_PCT,
        LATE_RECLAIM_MIN_RANGE_POSITION,
        LATE_RECLAIM_MAX_DIST_TO_HIGH_PCT,
        LATE_RECLAIM_MAX_DRAWDOWN_FROM_HIGH_PCT,
        LATE_RECLAIM_MIN_VOLUME_RATIO,
        LATE_RECLAIM_MIN_RECLAIM_SCORE,
        RANGE_BREAK_MIN_RUNUP_PCT,
        RANGE_BREAK_MIN_RANGE_POSITION,
        RANGE_BREAK_MIN_BREAKOUT_FROM_LOW_PCT,
        RANGE_BREAK_MAX_DIST_TO_HIGH_PCT,
        RANGE_BREAK_MIN_VOLUME_RATIO,
        RANGE_BREAK_MIN_RECLAIM_SCORE,
        SUPPORT_BOUNCE_MIN_RUNUP_PCT,
        SUPPORT_BOUNCE_MIN_RANGE_POSITION,
        SUPPORT_BOUNCE_MAX_DIST_TO_HIGH_PCT,
        SUPPORT_BOUNCE_MIN_BOUNCE_FROM_LOW_PCT,
        SUPPORT_BOUNCE_MIN_VOLUME_RATIO,
        SUPPORT_BOUNCE_MIN_RECLAIM_SCORE,
        PIVOT_RECLAIM_MIN_RUNUP_PCT,
        PIVOT_RECLAIM_MIN_RANGE_POSITION,
        PIVOT_RECLAIM_MAX_DIST_TO_HIGH_PCT,
        PIVOT_RECLAIM_MIN_BOUNCE_FROM_LOW_PCT,
        PIVOT_RECLAIM_MIN_VOLUME_RATIO,
        PIVOT_RECLAIM_MIN_RECLAIM_SCORE,
    )
except ImportError:
    # Standalone fallback if scanner module path is not in sys.path
    VOLUME_SPIKE_MULTIPLIER = 1.35
    PRICE_CHANGE_MIN_PCT = 0.35
    OBI_MIN = 0.1
    CONTINUATION_MIN_RUNUP_PCT = 10.0
    CONTINUATION_MIN_RANGE_POSITION = 0.65
    CONTINUATION_MAX_DIST_TO_HIGH_PCT = 12.5
    CONTINUATION_MIN_VOLUME_RATIO = 1.15
    MATURE_MIN_RUNUP_PCT = 22.0
    MATURE_MIN_RANGE_POSITION = 0.50
    MATURE_MAX_DIST_TO_HIGH_PCT = 20.0
    MATURE_MIN_VOLUME_RATIO = 1.05
    PULLBACK_MIN_RUNUP_PCT = 18.0
    PULLBACK_MIN_RANGE_POSITION = 0.38
    PULLBACK_MAX_DIST_TO_HIGH_PCT = 32.0
    PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT = 35.0
    PULLBACK_MIN_VOLUME_RATIO = 1.05
    PULLBACK_MIN_RECLAIM_SCORE = 0.55
    LATE_RECLAIM_MIN_RUNUP_PCT = 25.0
    LATE_RECLAIM_MIN_RANGE_POSITION = 0.28
    LATE_RECLAIM_MAX_DIST_TO_HIGH_PCT = 45.0
    LATE_RECLAIM_MAX_DRAWDOWN_FROM_HIGH_PCT = 45.0
    LATE_RECLAIM_MIN_VOLUME_RATIO = 1.08
    LATE_RECLAIM_MIN_RECLAIM_SCORE = 0.64
    RANGE_BREAK_MIN_RUNUP_PCT = 15.0
    RANGE_BREAK_MIN_RANGE_POSITION = 0.22
    RANGE_BREAK_MIN_BREAKOUT_FROM_LOW_PCT = 2.0
    RANGE_BREAK_MAX_DIST_TO_HIGH_PCT = 55.0
    RANGE_BREAK_MIN_VOLUME_RATIO = 1.10
    RANGE_BREAK_MIN_RECLAIM_SCORE = 0.70
    SUPPORT_BOUNCE_MIN_RUNUP_PCT = 6.0
    SUPPORT_BOUNCE_MIN_RANGE_POSITION = 0.08
    SUPPORT_BOUNCE_MAX_DIST_TO_HIGH_PCT = 72.0
    SUPPORT_BOUNCE_MIN_BOUNCE_FROM_LOW_PCT = 1.5
    SUPPORT_BOUNCE_MIN_VOLUME_RATIO = 1.08
    SUPPORT_BOUNCE_MIN_RECLAIM_SCORE = 0.66
    PIVOT_RECLAIM_MIN_RUNUP_PCT = 4.0
    PIVOT_RECLAIM_MIN_RANGE_POSITION = 0.05
    PIVOT_RECLAIM_MAX_DIST_TO_HIGH_PCT = 82.0
    PIVOT_RECLAIM_MIN_BOUNCE_FROM_LOW_PCT = 1.0
    PIVOT_RECLAIM_MIN_VOLUME_RATIO = 1.06
    PIVOT_RECLAIM_MIN_RECLAIM_SCORE = 0.60


def kibot_scanner_signal_fn(
    bar: Bar,
    hist: List[Bar],
    min_confidence: float = 0.70,
    lookback_24h: int = 96,  # 96 * 15m = 24 hours
) -> bool:
    """Official line-by-line replica of KiBot smallcap scanner entry logic.

    Evaluates whether the given bar qualifies for a pump signal based on the
    identical formulas in Core/Scanner/ki_indodax_smallcap_scanner.py.
    """
    if len(hist) < 4:
        return False

    price = bar.close
    if price <= 0:
        return False

    # 24-hour high/low proxy from rolling history (up to 96 bars on 15m timeframe)
    hist_24h = hist[-lookback_24h:]
    day_high = max(max(b.high for b in hist_24h), bar.high)
    day_low = min(min(b.low for b in hist_24h), bar.low)
    day_range = max(day_high - day_low, 0.0)

    # Persistence: ratio of non-falling bars in recent 4-bar window
    recent_bars = hist[-3:] + [bar]
    direction_hits = sum(1 for j in range(1, len(recent_bars)) if recent_bars[j].close >= recent_bars[j - 1].close)
    persistence = direction_hits / max(1, len(recent_bars) - 1)

    # Price change (momentum)
    price_change_pct = ((bar.close - bar.open) / bar.open * 100) if bar.open > 0 else 0.0

    # Volume spike vs 20-bar rolling average
    vol_window = [b.volume for b in hist[-20:]]
    avg_vol = sum(vol_window) / len(vol_window) if vol_window else 1.0
    vol_ratio = bar.volume / avg_vol if avg_vol > 0 else 1.0

    # Volume acceleration: compare current bar to 3 bars ago
    vol_acceleration = 0.0
    if len(vol_window) >= 4:
        vol_acceleration = (bar.volume - vol_window[-4]) / max(vol_window[-4], 1.0)

    # 24h metrics
    runup_from_low_pct = ((price - day_low) / day_low * 100) if day_low > 0 else 0.0
    distance_to_high_pct = ((day_high - price) / day_high * 100) if day_high > 0 else 100.0
    range_position = ((price - day_low) / day_range) if day_range > 0 else 0.0
    range_position = max(0.0, min(1.0, range_position))

    # Setup classifications (Identical lines 270-355 of scanner)
    trend_continuation = (
        runup_from_low_pct >= CONTINUATION_MIN_RUNUP_PCT
        and range_position >= CONTINUATION_MIN_RANGE_POSITION
        and distance_to_high_pct <= CONTINUATION_MAX_DIST_TO_HIGH_PCT
        and vol_ratio >= CONTINUATION_MIN_VOLUME_RATIO
        and persistence >= 0.55
    )

    pullback_reclaim = False
    late_reclaim = False
    range_break_reclaim = False
    support_bounce_reclaim = False
    pivot_reclaim = False

    if not trend_continuation:
        recent_low = min(b.low for b in recent_bars)
        reclaim_from_low_pct = ((price - recent_low) / recent_low * 100) if recent_low > 0 else 0.0
        drawdown_from_high_pct = ((day_high - price) / day_high * 100) if day_high > 0 else 100.0

        reclaim_score = 0.0
        reclaim_score += min(1.0, max(0.0, runup_from_low_pct / 45.0)) * 0.30
        reclaim_score += min(1.0, max(0.0, reclaim_from_low_pct / 6.0)) * 0.25
        reclaim_score += min(1.0, max(0.0, persistence)) * 0.20
        reclaim_score += min(1.0, max(0.0, vol_ratio - 1.0)) * 0.15
        reclaim_score += max(0.0, 1.0 - min(1.0, drawdown_from_high_pct / PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT)) * 0.10

        pullback_reclaim = (
            runup_from_low_pct >= PULLBACK_MIN_RUNUP_PCT
            and range_position >= PULLBACK_MIN_RANGE_POSITION
            and distance_to_high_pct <= PULLBACK_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= PULLBACK_MIN_VOLUME_RATIO
            and persistence >= 0.50
            and reclaim_from_low_pct >= 1.5
            and drawdown_from_high_pct <= PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT
            and reclaim_score >= PULLBACK_MIN_RECLAIM_SCORE
        )

        late_reclaim = (
            runup_from_low_pct >= LATE_RECLAIM_MIN_RUNUP_PCT
            and range_position >= LATE_RECLAIM_MIN_RANGE_POSITION
            and distance_to_high_pct <= LATE_RECLAIM_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= LATE_RECLAIM_MIN_VOLUME_RATIO
            and persistence >= 0.55
            and reclaim_from_low_pct >= 1.0
            and drawdown_from_high_pct <= LATE_RECLAIM_MAX_DRAWDOWN_FROM_HIGH_PCT
            and reclaim_score >= LATE_RECLAIM_MIN_RECLAIM_SCORE
        )

        breakout_from_low_pct = reclaim_from_low_pct
        range_break_reclaim = (
            runup_from_low_pct >= RANGE_BREAK_MIN_RUNUP_PCT
            and range_position >= RANGE_BREAK_MIN_RANGE_POSITION
            and distance_to_high_pct <= RANGE_BREAK_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= RANGE_BREAK_MIN_VOLUME_RATIO
            and persistence >= 0.58
            and breakout_from_low_pct >= RANGE_BREAK_MIN_BREAKOUT_FROM_LOW_PCT
            and reclaim_score >= RANGE_BREAK_MIN_RECLAIM_SCORE
        )

        support_bounce_reclaim = (
            runup_from_low_pct >= SUPPORT_BOUNCE_MIN_RUNUP_PCT
            and range_position >= SUPPORT_BOUNCE_MIN_RANGE_POSITION
            and distance_to_high_pct <= SUPPORT_BOUNCE_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= SUPPORT_BOUNCE_MIN_VOLUME_RATIO
            and persistence >= 0.52
            and reclaim_from_low_pct >= SUPPORT_BOUNCE_MIN_BOUNCE_FROM_LOW_PCT
            and reclaim_score >= SUPPORT_BOUNCE_MIN_RECLAIM_SCORE
        )

        pivot_reclaim = (
            runup_from_low_pct >= PIVOT_RECLAIM_MIN_RUNUP_PCT
            and range_position >= PIVOT_RECLAIM_MIN_RANGE_POSITION
            and distance_to_high_pct <= PIVOT_RECLAIM_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= PIVOT_RECLAIM_MIN_VOLUME_RATIO
            and persistence >= 0.48
            and reclaim_from_low_pct >= PIVOT_RECLAIM_MIN_BOUNCE_FROM_LOW_PCT
            and reclaim_score >= PIVOT_RECLAIM_MIN_RECLAIM_SCORE
        )

    mature_pump = (
        runup_from_low_pct >= MATURE_MIN_RUNUP_PCT
        and range_position >= MATURE_MIN_RANGE_POSITION
        and distance_to_high_pct <= MATURE_MAX_DIST_TO_HIGH_PCT
        and vol_ratio >= MATURE_MIN_VOLUME_RATIO
    )

    # Adaptive price and volume floor based on setup
    price_floor = PRICE_CHANGE_MIN_PCT
    volume_floor = VOLUME_SPIKE_MULTIPLIER
    if trend_continuation:
        price_floor = 0.25
        volume_floor = min(volume_floor, CONTINUATION_MIN_VOLUME_RATIO)
    if pullback_reclaim:
        price_floor = min(price_floor, 0.22)
        volume_floor = min(volume_floor, PULLBACK_MIN_VOLUME_RATIO)
    if late_reclaim:
        price_floor = min(price_floor, 0.18)
        volume_floor = min(volume_floor, LATE_RECLAIM_MIN_VOLUME_RATIO)
    if range_break_reclaim:
        price_floor = min(price_floor, 0.16)
        volume_floor = min(volume_floor, RANGE_BREAK_MIN_VOLUME_RATIO)
    if support_bounce_reclaim:
        price_floor = min(price_floor, 0.16)
        volume_floor = min(volume_floor, SUPPORT_BOUNCE_MIN_VOLUME_RATIO)
    if pivot_reclaim:
        price_floor = min(price_floor, 0.15)
        volume_floor = min(volume_floor, PIVOT_RECLAIM_MIN_VOLUME_RATIO)
    if mature_pump:
        price_floor = min(price_floor, 0.15)
        volume_floor = min(volume_floor, MATURE_MIN_VOLUME_RATIO)

    if price_change_pct < price_floor or vol_ratio < volume_floor:
        return False

    # Confidence score calculation (identical lines 385-451 of scanner)
    momentum_score = min(1.0, max(0.0, price_change_pct / 4.0))
    volume_score = min(1.0, max(0.0, (vol_ratio - 1.0) / 3.0))
    persistence_score = min(1.0, max(0.0, persistence))
    acceleration_score = min(1.0, max(0.0, vol_acceleration))
    trend_score = min(1.0, max(0.0, runup_from_low_pct / 35.0))
    range_score = min(1.0, max(0.0, range_position))
    near_high_score = max(0.0, min(1.0, 1.0 - (distance_to_high_pct / 12.0)))

    stage_bonus = 0.06 if trend_continuation else 0.03 if mature_pump else 0.0
    if pullback_reclaim:
        stage_bonus = max(stage_bonus, 0.04)
    if late_reclaim:
        stage_bonus = max(stage_bonus, 0.035)
    if range_break_reclaim:
        stage_bonus = max(stage_bonus, 0.045)
    if support_bounce_reclaim:
        stage_bonus = max(stage_bonus, 0.05)
    if pivot_reclaim:
        stage_bonus = max(stage_bonus, 0.055)

    # Official obi_proxy formula from scanner line 416
    obi_proxy = max(
        0.0,
        min(
            1.0,
            0.22
            + (trend_score * 0.20)
            + (range_score * 0.18)
            + (persistence_score * 0.16)
            + (volume_score * 0.12)
            + (0.06 if trend_continuation else 0.0)
        ),
    )
    obi_score = obi_proxy

    confidence = round(
        min(
            0.96,
            0.22
            + (momentum_score * 0.28)
            + (volume_score * 0.22)
            + (obi_score * 0.16)
            + (persistence_score * 0.10)
            + (acceleration_score * 0.04),
        ),
        4,
    )
    confidence = round(
        min(
            0.98,
            confidence
            + (trend_score * 0.06)
            + (range_score * 0.04)
            + (near_high_score * 0.05)
            + stage_bonus,
        ),
        4,
    )

    return confidence >= min_confidence
