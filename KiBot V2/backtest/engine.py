"""
KiBot V2 Backtest Engine.
Provides strict bar-by-bar historical replay with:
- Zero look-ahead bias (indicators computed strictly on closed bar[i])
- Next-bar open execution (bar[i+1].open)
- Realistic fill modeling via should_fill()
- Dual-slot position management (max 2 concurrent positions)
- Conservative intra-bar exit prioritization (SL prioritized over TP if both hit)
- Skipped bars for illiquid/flat data
- Full accounting of regulatory friction and Oxford adverse selection penalties
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd

from backtest.friction import (
    OrderType,
    StrategyType,
    should_fill,
    compute_pnl_after_costs,
)

logger = logging.getLogger("KiBotV2.Backtest.Engine")


def _is_bar_skipped(row: pd.Series, pair: str) -> bool:
    """
    Checks if bar is considered dummy/illiquid and should be skipped for indicators.
    - BTCIDR & ETHIDR: skip if volume == 0 or high == low
    - SOLIDR: skip if volume == 0 or high == low or range_pct < 0.05%
    """
    vol = float(row.get("indo_volume", 0.0))
    high = float(row.get("indo_high", 0.0))
    low = float(row.get("indo_low", 0.0))

    if vol <= 0.0 or high <= low or low <= 0.0:
        return True

    clean_pair = pair.upper().replace("/", "").strip()
    if clean_pair == "SOLIDR":
        range_pct = ((high - low) / low) * 100.0
        if range_pct < 0.05:
            return True

    return False


def _compute_indicators(df: pd.DataFrame, pair: str) -> pd.DataFrame:
    """
    Computes technical indicators across the dataset without look-ahead.
    Bars with zero volume or high == low are masked out from indicator input.
    """
    df_calc = df.copy()

    # Mask valid prices
    is_valid = ~df_calc.apply(lambda r: _is_bar_skipped(r, pair), axis=1)
    valid_close = df_calc["indo_close"].where(is_valid)

    # 1. Bollinger Bands (20, 2.0 std) on valid prices
    # We forward fill valid closes so invalid flat bars do not corrupt rolling windows
    filled_close = valid_close.ffill()

    sma20 = filled_close.rolling(window=20, min_periods=20).mean()
    std20 = filled_close.rolling(window=20, min_periods=20).std(ddof=0)

    df_calc["middle_bb"] = sma20
    df_calc["upper_bb"] = sma20 + (2.0 * std20)
    df_calc["lower_bb"] = sma20 - (2.0 * std20)
    df_calc["bb_bandwidth"] = (df_calc["upper_bb"] - df_calc["lower_bb"]) / df_calc["middle_bb"]

    # 2. BB Bandwidth 20th percentile (rolling 100 valid bars)
    df_calc["bb_squeeze_threshold"] = df_calc["bb_bandwidth"].rolling(window=100, min_periods=20).quantile(0.20)

    # 3. Rolling 24h Pearson Correlation between Indodax & Binance returns
    if "indo_return_1h" in df_calc.columns and "binance_return_1h" in df_calc.columns:
        df_calc["corr_24h"] = (
            df_calc["indo_return_1h"]
            .rolling(window=24, min_periods=12)
            .corr(df_calc["binance_return_1h"])
        )
    else:
        df_calc["corr_24h"] = 0.0

    df_calc["is_valid_bar"] = is_valid
    return df_calc


def run_backtest(
    aligned_df: pd.DataFrame,
    strategy_name: str,
    pair: str,
    initial_capital_idr: float = 10_000_000.0,
    position_size_idr: float = 5_000_000.0,
    order_type: OrderType = OrderType.MAKER,
    random_seed: int = 42,
    tp_pct: float = 0.015,
    sl_pct: float = 0.020,
    max_holding_bars: int = 24,
) -> Dict[str, Any]:
    """
    Bar-by-bar backtest replay with zero look-ahead bias.

    Aturan eksekusi:
    - Indikator dihitung dengan data sampai bar[i].close SAJA.
    - Entry signal muncul di bar[i].close.
    - Entry dieksekusi di bar[i+1].open (bukan close bar[i]).
    - Jika should_fill() return False, trade DIBATALKAN (tidak dicatat sebagai loss).
    - Exit TP/SL dicek pada bar[i+1].high & low. Jika high >= TP dan low <= SL
      dalam bar yang sama, asumsikan SL tersentuh lebih dulu (worst-case).
    - Skip bar dengan volume == 0 atau high == low untuk indikator.
    - Max concurrent positions = 2 (dual-slot).
    - Sisa cash tidak boleh negatif. Kalau tidak cukup untuk 1 posisi, skip.
    """
    if aligned_df.empty or len(aligned_df) < 2:
        raise ValueError("aligned_df must contain at least 2 rows for replay.")

    strat_clean = strategy_name.strip()
    if strat_clean in ("D1", "D2", "D3"):
        strategy_type = StrategyType.MEAN_REVERSION
    elif strat_clean in ("C_prime", "C'", "CPRIME"):
        strategy_type = StrategyType.LEAD_LAG
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}. Expected D1, D2, D3, or C_prime.")

    # Prepare DataFrame with indicators
    df = _compute_indicators(aligned_df, pair)

    cash_idr = float(initial_capital_idr)
    max_concurrent = 2
    open_positions: List[Dict[str, Any]] = []
    trades_log: List[Dict[str, Any]] = []
    equity_curve: List[float] = [cash_idr]

    n_unfilled = 0
    pending_entry: Optional[Dict[str, Any]] = None

    # Step through each bar sequentially (strictly historical)
    for i in range(len(df)):
        current_bar = df.iloc[i]
        curr_ts = int(current_bar["timestamp_utc"])
        curr_open = float(current_bar["indo_open"])
        curr_high = float(current_bar["indo_high"])
        curr_low = float(current_bar["indo_low"])
        curr_close = float(current_bar["indo_close"])
        curr_vol = float(current_bar.get("indo_volume", 0.0))

        # -------------------------------------------------------------
        # 1. PROCESS PENDING ENTRY FROM PREVIOUS BAR (at current_bar.open)
        # -------------------------------------------------------------
        if pending_entry is not None:
            bar_entry_info = {
                "open": curr_open,
                "high": curr_high,
                "low": curr_low,
                "close": curr_close,
                "volume": curr_vol,
            }
            # Probabilistic fill decision
            seed_for_bar = random_seed + i if random_seed is not None else None
            fill_ok = should_fill(order_type, bar_entry_info, random_seed=seed_for_bar)

            if fill_ok:
                entry_price = curr_open
                pos_tp = pending_entry.get("tp_price")
                pos_sl = pending_entry.get("sl_price")

                # If dynamic TP not set, calculate default TP/SL based on entry_price
                if pos_tp is None:
                    pos_tp = entry_price * (1.0 + tp_pct)
                if pos_sl is None:
                    pos_sl = entry_price * (1.0 - sl_pct)

                new_pos = {
                    "entry_ts": curr_ts,
                    "entry_price": entry_price,
                    "tp_price": pos_tp,
                    "sl_price": pos_sl,
                    "size_idr": position_size_idr,
                    "holding_bars": 0,
                    "max_holding_bars": pending_entry.get("max_bars", max_holding_bars),
                }
                open_positions.append(new_pos)
                cash_idr -= position_size_idr
            else:
                n_unfilled += 1

            pending_entry = None

        # -------------------------------------------------------------
        # 2. EVALUATE EXITS ON OPEN POSITIONS (current_bar intra-bar high/low)
        # -------------------------------------------------------------
        surviving_positions = []
        for pos in open_positions:
            pos["holding_bars"] += 1
            hit_tp = curr_high >= pos["tp_price"]
            hit_sl = curr_low <= pos["sl_price"]

            exit_price = None
            exit_reason = None

            # Worst-case prioritization: if both hit in the same bar, assume SL first
            if hit_tp and hit_sl:
                exit_price = pos["sl_price"]
                exit_reason = "SL"
            elif hit_sl:
                exit_price = pos["sl_price"]
                exit_reason = "SL"
            elif hit_tp:
                exit_price = pos["tp_price"]
                exit_reason = "TP"
            elif pos["holding_bars"] >= pos["max_holding_bars"]:
                exit_price = curr_close
                exit_reason = "TIMEOUT"

            if exit_price is not None:
                # Position closed
                pnl_res = compute_pnl_after_costs(
                    entry_price=pos["entry_price"],
                    exit_price=exit_price,
                    position_size_idr=pos["size_idr"],
                    pair=pair,
                    order_type=order_type,
                    strategy=strategy_type,
                )
                cash_idr += pos["size_idr"] + pnl_res["net_pnl_idr"]

                trades_log.append({
                    "entry_ts": pos["entry_ts"],
                    "entry_price": pos["entry_price"],
                    "exit_ts": curr_ts,
                    "exit_price": exit_price,
                    "side": "BUY",
                    "size_idr": pos["size_idr"],
                    "gross_pnl_idr": pnl_res["gross_pnl_idr"],
                    "friction_idr": pnl_res["friction_idr"],
                    "adverse_penalty_idr": pnl_res["adverse_penalty_idr"],
                    "net_pnl_idr": pnl_res["net_pnl_idr"],
                    "exit_reason": exit_reason,
                })
            else:
                surviving_positions.append(pos)

        open_positions = surviving_positions

        # -------------------------------------------------------------
        # 3. GENERATE ENTRY SIGNAL AT CLOSE OF bar[i]
        # -------------------------------------------------------------
        # Only evaluate if we have room in slots and sufficient cash
        can_open = (
            len(open_positions) < max_concurrent
            and cash_idr >= position_size_idr
            and pending_entry is None
            and bool(current_bar.get("is_valid_bar", False))
            and i < len(df) - 1  # Cannot enter if this is the absolute last bar
        )

        if can_open:
            signal = False
            target_tp = None
            target_sl = None
            max_bars = max_holding_bars

            # Strategy Option D1: Mean Reversion Lower BB touch murni
            if strat_clean == "D1":
                lower_bb = current_bar.get("lower_bb")
                middle_bb = current_bar.get("middle_bb")
                if pd.notna(lower_bb) and curr_low <= lower_bb:
                    signal = True
                    target_tp = middle_bb if pd.notna(middle_bb) else curr_close * (1.0 + tp_pct)
                    target_sl = curr_close * (1.0 - sl_pct)
                    max_bars = 24

            # Strategy Option D2: MR 1H Lower BB touch + BB Squeeze (< P20)
            elif strat_clean == "D2":
                lower_bb = current_bar.get("lower_bb")
                middle_bb = current_bar.get("middle_bb")
                bw = current_bar.get("bb_bandwidth")
                sqz_th = current_bar.get("bb_squeeze_threshold")
                if (
                    pd.notna(lower_bb)
                    and pd.notna(bw)
                    and pd.notna(sqz_th)
                    and curr_low <= lower_bb
                    and bw <= sqz_th
                ):
                    signal = True
                    target_tp = middle_bb if pd.notna(middle_bb) else curr_close * (1.0 + tp_pct)
                    target_sl = curr_close * (1.0 - sl_pct)
                    max_bars = 24

            # Strategy Option D3: MR 1H Lower BB touch + Squeeze + Binance Lead-Lag Filter
            elif strat_clean == "D3":
                lower_bb = current_bar.get("lower_bb")
                middle_bb = current_bar.get("middle_bb")
                bw = current_bar.get("bb_bandwidth")
                sqz_th = current_bar.get("bb_squeeze_threshold")
                binance_ret = current_bar.get("binance_return_1h", 0.0)
                corr = current_bar.get("corr_24h", 0.0)

                # Filter Lead-Lag: Binance momentum >= -0.50% & correlation >= 0.80
                lead_lag_ok = (binance_ret >= -0.005) and (corr >= 0.80)

                if (
                    pd.notna(lower_bb)
                    and pd.notna(bw)
                    and pd.notna(sqz_th)
                    and curr_low <= lower_bb
                    and bw <= sqz_th
                    and lead_lag_ok
                ):
                    signal = True
                    target_tp = middle_bb if pd.notna(middle_bb) else curr_close * (1.0 + tp_pct)
                    target_sl = curr_close * (1.0 - sl_pct)
                    max_bars = 24

            # Strategy Option C_prime: High-Conviction Lead-Lag Dislocation >= 2.0%
            elif strat_clean in ("C_prime", "C'", "CPRIME"):
                disloc = current_bar.get("dislocation_1h", 0.0)
                if pd.notna(disloc) and disloc >= 0.02:
                    signal = True
                    target_tp = curr_close * (1.0 + tp_pct)
                    target_sl = curr_close * (1.0 - sl_pct)
                    max_bars = 6

            if signal:
                pending_entry = {
                    "signal_ts": curr_ts,
                    "tp_price": target_tp,
                    "sl_price": target_sl,
                    "max_bars": max_bars,
                }

        # Track total equity at end of bar
        unrealized_pnl = 0.0
        for pos in open_positions:
            unrealized_pnl += pos["size_idr"] * ((curr_close - pos["entry_price"]) / pos["entry_price"])
        current_equity = cash_idr + (len(open_positions) * position_size_idr) + unrealized_pnl
        equity_curve.append(current_equity)

    # -------------------------------------------------------------
    # 4. CLOSE REMAINING OPEN POSITIONS AT END OF DATA
    # -------------------------------------------------------------
    last_bar = df.iloc[-1]
    last_close = float(last_bar["indo_close"])
    last_ts = int(last_bar["timestamp_utc"])

    for pos in open_positions:
        pnl_res = compute_pnl_after_costs(
            entry_price=pos["entry_price"],
            exit_price=last_close,
            position_size_idr=pos["size_idr"],
            pair=pair,
            order_type=order_type,
            strategy=strategy_type,
        )
        cash_idr += pos["size_idr"] + pnl_res["net_pnl_idr"]
        trades_log.append({
            "entry_ts": pos["entry_ts"],
            "entry_price": pos["entry_price"],
            "exit_ts": last_ts,
            "exit_price": last_close,
            "side": "BUY",
            "size_idr": pos["size_idr"],
            "gross_pnl_idr": pnl_res["gross_pnl_idr"],
            "friction_idr": pnl_res["friction_idr"],
            "adverse_penalty_idr": pnl_res["adverse_penalty_idr"],
            "net_pnl_idr": pnl_res["net_pnl_idr"],
            "exit_reason": "END_OF_DATA",
        })

    # -------------------------------------------------------------
    # 5. COMPILE AGGREGATE BACKTEST PERFORMANCE METRICS
    # -------------------------------------------------------------
    n_trades = len(trades_log)
    wins = [t for t in trades_log if t["net_pnl_idr"] > 0]
    losses = [t for t in trades_log if t["net_pnl_idr"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)

    win_rate = (n_wins / n_trades * 100.0) if n_trades > 0 else 0.0

    gross_pnl_idr = sum(t["gross_pnl_idr"] for t in trades_log)
    total_friction_idr = sum(t["friction_idr"] for t in trades_log)
    total_adverse_penalty_idr = sum(t["adverse_penalty_idr"] for t in trades_log)
    net_pnl_idr = sum(t["net_pnl_idr"] for t in trades_log)
    net_pnl_pct = (net_pnl_idr / initial_capital_idr) * 100.0

    avg_win_pct = (
        sum((w["net_pnl_idr"] / w["size_idr"]) * 100.0 for w in wins) / n_wins
        if n_wins > 0 else 0.0
    )
    avg_loss_pct = (
        sum((l["net_pnl_idr"] / l["size_idr"]) * 100.0 for l in losses) / n_losses
        if n_losses > 0 else 0.0
    )

    total_win_nominal = sum(w["net_pnl_idr"] for w in wins)
    total_loss_nominal = abs(sum(l["net_pnl_idr"] for l in losses))
    if total_loss_nominal == 0:
        profit_factor = 999.0 if total_win_nominal > 0 else 0.0
    else:
        profit_factor = total_win_nominal / total_loss_nominal

    expectancy_per_trade_pct = (net_pnl_pct / n_trades) if n_trades > 0 else 0.0

    total_costs = total_friction_idr + total_adverse_penalty_idr
    fee_to_gross_ratio = (total_costs / gross_pnl_idr) if gross_pnl_idr > 0 else 0.0

    # Max Peak-to-Trough Drawdown
    eq_arr = np.array(equity_curve)
    cummax = np.maximum.accumulate(eq_arr)
    drawdowns = (cummax - eq_arr) / cummax * 100.0
    max_drawdown_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    return {
        "strategy": strategy_name,
        "pair": pair,
        "n_trades": n_trades,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "n_unfilled": n_unfilled,
        "win_rate": round(win_rate, 2),
        "avg_win_pct": round(avg_win_pct, 4),
        "avg_loss_pct": round(avg_loss_pct, 4),
        "gross_pnl_idr": round(gross_pnl_idr, 2),
        "total_friction_idr": round(total_friction_idr, 2),
        "total_adverse_penalty_idr": round(total_adverse_penalty_idr, 2),
        "net_pnl_idr": round(net_pnl_idr, 2),
        "net_pnl_pct": round(net_pnl_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy_per_trade_pct": round(expectancy_per_trade_pct, 4),
        "fee_to_gross_ratio": round(fee_to_gross_ratio, 4),
        "trades_log": trades_log,
    }
