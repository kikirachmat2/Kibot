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

    # 4. Multi-Timeframe: 4H Resampling for MR_4H (Zero look-ahead shift)
    df_calc["bucket_4h"] = df_calc["timestamp_utc"] // 14400
    df_4h = df_calc.groupby("bucket_4h").agg({
        "indo_open": "first",
        "indo_high": "max",
        "indo_low": "min",
        "indo_close": "last",
        "indo_volume": "sum"
    }).reset_index()

    c_4h = df_4h["indo_close"]
    delta_4h = c_4h.diff()
    gain_4h = delta_4h.where(delta_4h > 0, 0.0).rolling(14, min_periods=2).mean()
    loss_4h = (-delta_4h.where(delta_4h < 0, 0.0)).rolling(14, min_periods=2).mean()
    rs_4h = gain_4h / loss_4h.replace(0, np.nan)
    df_4h["rsi_4h"] = (100.0 - (100.0 / (1.0 + rs_4h))).fillna(50.0)

    sma20_4h = c_4h.rolling(20, min_periods=5).mean()
    std20_4h = c_4h.rolling(20, min_periods=5).std(ddof=0).fillna(0.0)
    df_4h["middle_bb_4h"] = sma20_4h
    df_4h["lower_bb_4h"] = sma20_4h - 2.0 * std20_4h
    df_4h["upper_bb_4h"] = sma20_4h + 2.0 * std20_4h

    for col in ["rsi_4h", "middle_bb_4h", "lower_bb_4h", "upper_bb_4h"]:
        df_4h[col] = df_4h[col].shift(1)

    df_calc = pd.merge(
        df_calc,
        df_4h[["bucket_4h", "rsi_4h", "middle_bb_4h", "lower_bb_4h", "upper_bb_4h"]],
        on="bucket_4h",
        how="left"
    )

    # 5. Multi-Timeframe: 1D Resampling for TREND_1D & MR_1D (Zero look-ahead shift)
    df_calc["bucket_1d"] = df_calc["timestamp_utc"] // 86400
    df_1d = df_calc.groupby("bucket_1d").agg({
        "indo_open": "first",
        "indo_high": "max",
        "indo_low": "min",
        "indo_close": "last",
        "indo_volume": "sum"
    }).reset_index()

    c_1d = df_1d["indo_close"]
    h_1d = df_1d["indo_high"]
    l_1d = df_1d["indo_low"]

    df_1d["sma50_1d"] = c_1d.rolling(50, min_periods=5).mean()
    df_1d["sma200_1d"] = c_1d.rolling(200, min_periods=10).mean()

    tr1 = h_1d - l_1d
    tr2 = (h_1d - c_1d.shift(1)).abs()
    tr3 = (l_1d - c_1d.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df_1d["atr14_1d"] = tr.rolling(14, min_periods=2).mean()

    sma20_1d = c_1d.rolling(20, min_periods=5).mean()
    std20_1d = c_1d.rolling(20, min_periods=5).std(ddof=0).replace(0, np.nan)
    df_1d["sma20_1d"] = sma20_1d
    df_1d["z_score_1d"] = ((c_1d - sma20_1d) / std20_1d).fillna(0.0)

    for col in ["sma50_1d", "sma200_1d", "atr14_1d", "sma20_1d", "z_score_1d"]:
        df_1d[col] = df_1d[col].shift(1)

    df_calc = pd.merge(
        df_calc,
        df_1d[["bucket_1d", "sma50_1d", "sma200_1d", "atr14_1d", "sma20_1d", "z_score_1d"]],
        on="bucket_1d",
        how="left"
    )

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
    if strat_clean in ("D1", "D2", "D3", "MR_4H", "MR_1D"):
        strategy_type = StrategyType.MEAN_REVERSION
    elif strat_clean in ("C_prime", "C'", "CPRIME"):
        strategy_type = StrategyType.LEAD_LAG
    elif strat_clean in ("TREND_1D", "TREND"):
        strategy_type = StrategyType.TREND_FOLLOWING
    else:
        raise ValueError(f"Unknown strategy: {strategy_name}.")

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
                use_fixed_tp = pending_entry.get("use_fixed_tp", True)

                # If dynamic TP not set and fixed TP enabled, calculate default TP/SL based on entry_price
                if pos_tp is None and use_fixed_tp:
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
                    "highest_high": entry_price,
                    "atr_val": pending_entry.get("atr_val"),
                    "trail_mult": pending_entry.get("trail_mult"),
                    "strategy_name": strat_clean,
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
            pos["highest_high"] = max(pos.get("highest_high", pos["entry_price"]), curr_high)

            # Update trailing stop for ATR trailing strategy
            if pos.get("trail_mult") is not None and pos.get("atr_val") is not None:
                trail_sl = pos["highest_high"] - (pos["trail_mult"] * pos["atr_val"])
                pos["sl_price"] = max(pos["sl_price"], trail_sl)

            hit_tp = (pos["tp_price"] is not None) and (curr_high >= pos["tp_price"])
            hit_sl = curr_low <= pos["sl_price"]

            exit_price = None
            exit_reason = None

            # Strategy-specific conditional exits:
            # MR_4H: Exit when RSI_4H > 50
            if pos.get("strategy_name") == "MR_4H":
                rsi_val = current_bar.get("rsi_4h")
                if pd.notna(rsi_val) and rsi_val > 50.0:
                    exit_price = curr_close
                    exit_reason = "EXIT_RSI50"
            # MR_1D: Exit when Z-score_1D > 0
            elif pos.get("strategy_name") == "MR_1D":
                z_val = current_bar.get("z_score_1d")
                if pd.notna(z_val) and z_val > 0.0:
                    exit_price = curr_close
                    exit_reason = "EXIT_ZSCORE"

            # Worst-case prioritization: if both hit in the same bar, assume SL first
            if exit_price is None:
                if hit_tp and hit_sl:
                    exit_price = pos["sl_price"]
                    exit_reason = "SL"
                elif hit_sl:
                    exit_price = pos["sl_price"]
                    exit_reason = "TRAILING_ATR" if pos.get("trail_mult") is not None else "SL"
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
            extra_params = {}

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

            # Strategy Option TREND_1D: Trend following daily (close > SMA200 & SMA50 > SMA200)
            elif strat_clean in ("TREND_1D", "TREND"):
                sma200_1d = current_bar.get("sma200_1d")
                sma50_1d = current_bar.get("sma50_1d")
                atr_d = current_bar.get("atr14_1d")

                if (
                    pd.notna(sma200_1d)
                    and pd.notna(sma50_1d)
                    and curr_close > sma200_1d
                    and sma50_1d > sma200_1d
                    and len(open_positions) == 0  # 1 position at a time riding trend
                ):
                    signal = True
                    atr_effective = atr_d if (pd.notna(atr_d) and atr_d > 0) else curr_close * 0.03
                    target_tp = None
                    target_sl = curr_close - (2.5 * atr_effective)
                    max_bars = 720  # 30 days
                    extra_params = {
                        "use_fixed_tp": False,
                        "atr_val": atr_effective,
                        "trail_mult": 2.5,
                    }

            # Strategy Option MR_4H: Mean reversion 4H (RSI < 30 & price < lower BB(20,2))
            elif strat_clean == "MR_4H":
                rsi_4h = current_bar.get("rsi_4h")
                lower_bb_4h = current_bar.get("lower_bb_4h")
                middle_bb_4h = current_bar.get("middle_bb_4h")

                if (
                    pd.notna(rsi_4h)
                    and pd.notna(lower_bb_4h)
                    and rsi_4h < 30.0
                    and (curr_close < lower_bb_4h or curr_low <= lower_bb_4h)
                ):
                    signal = True
                    target_tp = middle_bb_4h if pd.notna(middle_bb_4h) else curr_close * 1.03
                    target_sl = curr_close * 0.95  # 5% SL
                    max_bars = 96  # 4 days
                    extra_params = {"use_fixed_tp": True}

            # Strategy Option MR_1D: Mean reversion 1D (Z-score < -2.0 & price > SMA200)
            elif strat_clean == "MR_1D":
                z_1d = current_bar.get("z_score_1d")
                sma200_1d = current_bar.get("sma200_1d")
                sma20_1d = current_bar.get("sma20_1d")

                if (
                    pd.notna(z_1d)
                    and pd.notna(sma200_1d)
                    and z_1d < -2.0
                    and curr_close > sma200_1d
                ):
                    signal = True
                    target_tp = sma20_1d if pd.notna(sma20_1d) else curr_close * 1.05
                    target_sl = curr_close * 0.94  # 6% SL
                    max_bars = 240  # 10 days
                    extra_params = {"use_fixed_tp": True}

            if signal:
                pending_entry = {
                    "signal_ts": curr_ts,
                    "tp_price": target_tp,
                    "sl_price": target_sl,
                    "max_bars": max_bars,
                    **extra_params,
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
