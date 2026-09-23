import json
import random
import datetime
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

from config.fees import IDR_BUY_FEES, IDR_SELL_FEES

# Buy taker fee: 0.2111%, Sell taker fee: 0.4211%
BUY_FEE_RATE = IDR_BUY_FEES.taker_pct / 100.0
SELL_FEE_RATE = IDR_SELL_FEES.taker_pct / 100.0

def load_data(filepath: str) -> pd.DataFrame:
    with open(filepath, "r") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df.columns = [c.lower() for c in df.columns]
    if "time" in df.columns:
        df["date"] = pd.to_datetime(df["time"], unit="s")
    elif "timestamp" in df.columns:
        df["date"] = pd.to_datetime(df["timestamp"], unit="s")
    
    df["close"] = df["close"].astype(float)
    df = df.sort_values("date").reset_index(drop=True)
    return df

def generate_unscheduled_topups(start_date: pd.Timestamp, end_date: pd.Timestamp, seed: int = 42) -> Dict[str, float]:
    """
    Identical generator to run_trend_filter_backtest.py to ensure 100% apple-to-apple comparability.
    """
    random.seed(seed)
    current_date = start_date # Day 1 deposit
    topups = {}
    while current_date <= end_date:
        amt = random.randint(4, 20) * 50_000.0
        date_str = current_date.strftime("%Y-%m-%d")
        topups[date_str] = amt
        current_date += datetime.timedelta(days=random.randint(18, 42))
    return topups

@dataclass
class BacktestMetrics:
    scenario_name: str
    total_invested: float
    final_nav: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    max_capital_loss_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    sell_events_count: int
    buy_events_count: int
    total_fees_paid: float
    whipsaw_loss_count: int
    daily_nav: pd.Series
    drawdown_series: pd.Series
    trade_log: List[dict]

def run_simulation(
    df_btc: pd.DataFrame,
    df_eth: pd.DataFrame,
    topups: Dict[str, float],
    lookback_days: int = 30,           # e.g., 30 (1m), 90 (3m), 180 (6m), 365 (12m)
    check_frequency: str = "monthly",  # "monthly", "weekly", or "none" (baseline)
    asset_mode: str = "portfolio",     # "portfolio" (70/30), "btc" (100%), "eth" (100%)
    scenario_label: str = "",
    use_sma_rule: bool = False,        # If True, runs SMA200 daily for benchmark comparison
    sma_period: int = 200
) -> BacktestMetrics:
    # Merge BTC and ETH
    df = pd.merge(df_btc[["date", "close"]], df_eth[["date", "close"]], on="date", suffixes=("_btc", "_eth"))
    df = df.sort_values("date").reset_index(drop=True)
    
    # Precompute Indicators
    if use_sma_rule:
        df["sma_btc"] = df["close_btc"].rolling(window=sma_period).mean()
        df["sma_eth"] = df["close_eth"].rolling(window=sma_period).mean()
    else:
        # Time-Series Momentum: (Price(t) - Price(t - lookback)) / Price(t - lookback)
        df["mom_btc"] = df["close_btc"].pct_change(periods=lookback_days)
        df["mom_eth"] = df["close_eth"].pct_change(periods=lookback_days)
    
    # Mark check schedule
    df["is_month_end"] = False
    for i in range(len(df) - 1):
        if df.loc[i, "date"].month != df.loc[i+1, "date"].month:
            df.loc[i, "is_month_end"] = True
    df.loc[len(df)-1, "is_month_end"] = True

    # Mark weekly check (every Sunday, dayofweek == 6, or every 7 days)
    df["is_week_end"] = df["date"].dt.dayofweek == 6

    # State
    cash_btc_idr = 0.0
    cash_eth_idr = 0.0
    btc_qty = 0.0
    eth_qty = 0.0
    total_invested = 0.0
    
    regime_btc = "SAFE"
    regime_eth = "SAFE"
    
    # Target allocations
    if asset_mode == "portfolio":
        target_w_btc, target_w_eth = 0.70, 0.30
    elif asset_mode == "btc":
        target_w_btc, target_w_eth = 1.00, 0.00
    elif asset_mode == "eth":
        target_w_btc, target_w_eth = 0.00, 1.00
    else:
        raise ValueError("Invalid asset_mode")

    trade_log = []
    daily_nav_list = []
    daily_invested_list = []
    dates_list = []

    last_sell_btc = None
    last_sell_eth = None
    whipsaw_losses = 0

    for i, row in df.iterrows():
        dt_str = row["date"].strftime("%Y-%m-%d")
        p_btc = row["close_btc"]
        p_eth = row["close_eth"]
        is_month_end = row["is_month_end"]
        is_week_end = row["is_week_end"]
        
        # 1. Incoming Topup
        if dt_str in topups:
            topup_amt = topups[dt_str]
            total_invested += topup_amt
            
            topup_btc = topup_amt * target_w_btc
            topup_eth = topup_amt * target_w_eth
            
            # BTC Topup
            if check_frequency == "none" or regime_btc == "SAFE":
                if topup_btc > 0:
                    fee = topup_btc * BUY_FEE_RATE
                    net = topup_btc - fee
                    qty = net / p_btc
                    btc_qty += qty
                    trade_log.append({
                        "date": dt_str, "action": "BUY_TOPUP_BTC", "gross_idr": topup_btc,
                        "fee_idr": fee, "price": p_btc, "qty": qty
                    })
            else:
                cash_btc_idr += topup_btc
                trade_log.append({
                    "date": dt_str, "action": "CASH_TOPUP_BTC_DANGER", "gross_idr": topup_btc,
                    "fee_idr": 0.0, "price": p_btc, "qty": 0.0
                })
                
            # ETH Topup
            if check_frequency == "none" or regime_eth == "SAFE":
                if topup_eth > 0:
                    fee = topup_eth * BUY_FEE_RATE
                    net = topup_eth - fee
                    qty = net / p_eth
                    eth_qty += qty
                    trade_log.append({
                        "date": dt_str, "action": "BUY_TOPUP_ETH", "gross_idr": topup_eth,
                        "fee_idr": fee, "price": p_eth, "qty": qty
                    })
            else:
                cash_eth_idr += topup_eth
                trade_log.append({
                    "date": dt_str, "action": "CASH_TOPUP_ETH_DANGER", "gross_idr": topup_eth,
                    "fee_idr": 0.0, "price": p_eth, "qty": 0.0
                })

        # 2. Regime Evaluation
        if use_sma_rule:
            ready_btc = not pd.isna(row["sma_btc"])
            ready_eth = not pd.isna(row["sma_eth"])
            check_now = True # SMA daily
            is_safe_btc = (p_btc > row["sma_btc"]) if ready_btc else True
            is_safe_eth = (p_eth > row["sma_eth"]) if ready_eth else True
        else:
            ready_btc = not pd.isna(row["mom_btc"])
            ready_eth = not pd.isna(row["mom_eth"])
            
            check_now = False
            if check_frequency == "weekly" and is_week_end and ready_btc and ready_eth:
                check_now = True
            elif check_frequency == "monthly" and is_month_end and ready_btc and ready_eth:
                check_now = True
            elif check_frequency == "daily" and ready_btc and ready_eth:
                check_now = True
                
            # Momentum > 0 -> SAFE, Momentum <= 0 -> DANGER
            is_safe_btc = (row["mom_btc"] > 0.0) if ready_btc else True
            is_safe_eth = (row["mom_eth"] > 0.0) if ready_eth else True

        if check_now:
            # BTC Transition
            if target_w_btc > 0 and ready_btc:
                new_regime_btc = "SAFE" if is_safe_btc else "DANGER"
                if new_regime_btc != regime_btc:
                    if new_regime_btc == "DANGER":
                        if btc_qty > 0:
                            gross = btc_qty * p_btc
                            fee = gross * SELL_FEE_RATE
                            net = gross - fee
                            cash_btc_idr += net
                            trade_log.append({
                                "date": dt_str, "action": "SELL_ALL_BTC_DANGER", "gross_idr": gross,
                                "fee_idr": fee, "price": p_btc, "qty": btc_qty
                            })
                            last_sell_btc = {"price": p_btc, "date": dt_str, "qty": btc_qty}
                            btc_qty = 0.0
                    else: # Switched to SAFE -> Redeploy
                        if cash_btc_idr > 0:
                            fee = cash_btc_idr * BUY_FEE_RATE
                            net = cash_btc_idr - fee
                            qty = net / p_btc
                            btc_qty += qty
                            redeploy_entry = {
                                "date": dt_str, "action": "REDEPLOY_BTC_SAFE", "gross_idr": cash_btc_idr,
                                "fee_idr": fee, "price": p_btc, "qty": qty
                            }
                            if last_sell_btc is not None:
                                price_diff = (p_btc - last_sell_btc["price"]) / last_sell_btc["price"] * 100.0
                                redeploy_entry["price_diff_pct"] = price_diff
                                if p_btc > last_sell_btc["price"]:
                                    whipsaw_losses += 1
                                    redeploy_entry["whipsaw_penalty_pct"] = price_diff
                            trade_log.append(redeploy_entry)
                            cash_btc_idr = 0.0
                    regime_btc = new_regime_btc

            # ETH Transition
            if target_w_eth > 0 and ready_eth:
                new_regime_eth = "SAFE" if is_safe_eth else "DANGER"
                if new_regime_eth != regime_eth:
                    if new_regime_eth == "DANGER":
                        if eth_qty > 0:
                            gross = eth_qty * p_eth
                            fee = gross * SELL_FEE_RATE
                            net = gross - fee
                            cash_eth_idr += net
                            trade_log.append({
                                "date": dt_str, "action": "SELL_ALL_ETH_DANGER", "gross_idr": gross,
                                "fee_idr": fee, "price": p_eth, "qty": eth_qty
                            })
                            last_sell_eth = {"price": p_eth, "date": dt_str, "qty": eth_qty}
                            eth_qty = 0.0
                    else: # Switched to SAFE -> Redeploy
                        if cash_eth_idr > 0:
                            fee = cash_eth_idr * BUY_FEE_RATE
                            net = cash_eth_idr - fee
                            qty = net / p_eth
                            eth_qty += qty
                            redeploy_entry = {
                                "date": dt_str, "action": "REDEPLOY_ETH_SAFE", "gross_idr": cash_eth_idr,
                                "fee_idr": fee, "price": p_eth, "qty": qty
                            }
                            if last_sell_eth is not None:
                                price_diff = (p_eth - last_sell_eth["price"]) / last_sell_eth["price"] * 100.0
                                redeploy_entry["price_diff_pct"] = price_diff
                                if p_eth > last_sell_eth["price"]:
                                    whipsaw_losses += 1
                                    redeploy_entry["whipsaw_penalty_pct"] = price_diff
                            trade_log.append(redeploy_entry)
                            cash_eth_idr = 0.0
                    regime_eth = new_regime_eth

        # Daily NAV calculation
        daily_nav = (btc_qty * p_btc) + (eth_qty * p_eth) + cash_btc_idr + cash_eth_idr
        daily_nav_list.append(daily_nav)
        daily_invested_list.append(total_invested)
        dates_list.append(row["date"])

    # Build series
    nav_s = pd.Series(daily_nav_list, index=pd.to_datetime(dates_list))
    inv_s = pd.Series(daily_invested_list, index=pd.to_datetime(dates_list))

    # Unit price calculation
    unit_price = pd.Series(index=nav_s.index, dtype=float)
    n_days = len(nav_s)
    
    first_nav = nav_s.iloc[0]
    first_inv = inv_s.iloc[0]
    units = first_inv / 100.0
    unit_price.iloc[0] = first_nav / units

    for i in range(1, n_days):
        flow = inv_s.iloc[i] - inv_s.iloc[i-1]
        prior_unit_price = unit_price.iloc[i-1]
        
        if flow > 0:
            units += (flow / prior_unit_price)
            
        unit_price.iloc[i] = nav_s.iloc[i] / units

    running_max_unit = unit_price.cummax()
    unit_dd_series = (unit_price - running_max_unit) / running_max_unit * 100.0
    max_unit_dd = abs(unit_dd_series.min())

    unrealized_pnl_pct = (nav_s - inv_s) / inv_s * 100.0
    worst_capital_loss_pct = abs(min(0.0, unrealized_pnl_pct.min()))

    final_invested = inv_s.iloc[-1]
    final_nav = nav_s.iloc[-1]
    total_ret = ((final_nav - final_invested) / final_invested) * 100.0
    years = n_days / 365.25
    cagr = (((final_nav / final_invested) ** (1.0 / years)) - 1.0) * 100.0 if final_nav > 0 and final_invested > 0 else 0.0

    daily_rets = unit_price.pct_change().dropna()
    rf = 0.05
    ann_mean = daily_rets.mean() * 365.25
    ann_vol = daily_rets.std() * np.sqrt(365.25)
    sharpe = (ann_mean - rf) / ann_vol if ann_vol > 0 else 0.0
    
    downside_rets = daily_rets[daily_rets < 0]
    downside_vol = downside_rets.std() * np.sqrt(365.25) if len(downside_rets) > 0 else 0.0
    sortino = (ann_mean - rf) / downside_vol if downside_vol > 0 else 0.0

    sell_events = [t for t in trade_log if "SELL_ALL" in t["action"]]
    buy_events = [t for t in trade_log if "BUY" in t["action"] or "REDEPLOY" in t["action"]]
    total_fees = sum(t["fee_idr"] for t in trade_log)

    return BacktestMetrics(
        scenario_name=scenario_label,
        total_invested=final_invested,
        final_nav=final_nav,
        total_return_pct=total_ret,
        cagr_pct=cagr,
        max_drawdown_pct=max_unit_dd,
        max_capital_loss_pct=worst_capital_loss_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        sell_events_count=len(sell_events),
        buy_events_count=len(buy_events),
        total_fees_paid=total_fees,
        whipsaw_loss_count=whipsaw_losses,
        daily_nav=nav_s,
        drawdown_series=unit_dd_series,
        trade_log=trade_log
    )

def main():
    df_btc = load_data("data/historical/btcidr.json")
    df_eth = load_data("data/historical/ethidr.json")
    
    start_date = max(df_btc["date"].min(), df_eth["date"].min())
    end_date = min(df_btc["date"].max(), df_eth["date"].max())
    
    topups = generate_unscheduled_topups(start_date, end_date, seed=42)
    total_topup_idr = sum(topups.values())
    print(f"Loaded {len(df_btc)} bars ({start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')})")
    print(f"Irregular topups totaling Rp {total_topup_idr:,.0f}\n")

    # Lookback configurations:
    # 1 Month  ~ 30 days
    # 3 Months ~ 90 days
    # 6 Months ~ 180 days
    # 12 Months ~ 365 days
    lookbacks = [
        ("1M", 30),
        ("3M", 90),
        ("6M", 180),
        ("12M", 365)
    ]
    frequencies = ["monthly", "weekly"]

    results = []

    # 1. Benchmarks
    # Baseline DCA
    res_base = run_simulation(
        df_btc, df_eth, topups, lookback_days=30, check_frequency="none",
        asset_mode="portfolio", scenario_label="[BENCHMARK 1] Baseline DCA 70/30"
    )
    results.append(res_base)

    # Trend-Filter SMA-200 Daily (best from yesterday)
    res_sma_daily = run_simulation(
        df_btc, df_eth, topups, lookback_days=30, check_frequency="daily",
        asset_mode="portfolio", scenario_label="[BENCHMARK 2] Trend-Filter SMA-200 Daily",
        use_sma_rule=True, sma_period=200
    )
    results.append(res_sma_daily)

    # 2. Portfolio 70/30 Momentum Skenarios
    for lb_label, lb_days in lookbacks:
        for freq in frequencies:
            name = f"PORTFOLIO 70/30: Mom-{lb_label} ({freq.title()})"
            res = run_simulation(
                df_btc, df_eth, topups, lookback_days=lb_days, check_frequency=freq,
                asset_mode="portfolio", scenario_label=name
            )
            results.append(res)

    # 3. BTC 100% Momentum Skenarios
    # Add BTC baseline first
    res_btc_base = run_simulation(
        df_btc, df_eth, topups, lookback_days=30, check_frequency="none",
        asset_mode="btc", scenario_label="[BTC BENCHMARK] Baseline DCA 100% BTC"
    )
    results.append(res_btc_base)
    for lb_label, lb_days in lookbacks:
        for freq in frequencies:
            name = f"BTC 100%: Mom-{lb_label} ({freq.title()})"
            res = run_simulation(
                df_btc, df_eth, topups, lookback_days=lb_days, check_frequency=freq,
                asset_mode="btc", scenario_label=name
            )
            results.append(res)

    # 4. ETH 100% Momentum Skenarios
    # Add ETH baseline first
    res_eth_base = run_simulation(
        df_btc, df_eth, topups, lookback_days=30, check_frequency="none",
        asset_mode="eth", scenario_label="[ETH BENCHMARK] Baseline DCA 100% ETH"
    )
    results.append(res_eth_base)
    for lb_label, lb_days in lookbacks:
        for freq in frequencies:
            name = f"ETH 100%: Mom-{lb_label} ({freq.title()})"
            res = run_simulation(
                df_btc, df_eth, topups, lookback_days=lb_days, check_frequency=freq,
                asset_mode="eth", scenario_label=name
            )
            results.append(res)

    # Print Table
    print("=" * 145)
    print(f"{'SCENARIO':<46} | {'FINAL NAV (IDR)':<16} | {'RETURN%':<8} | {'CAGR%':<7} | {'MAX DD%':<8} | {'CAP LOSS%':<9} | {'SHARPE':<7} | {'SELLS':<5} | {'WHIPSAWS':<8} | {'FEES (IDR)':<12}")
    print("=" * 145)
    for r in results:
        print(f"{r.scenario_name:<46} | Rp {r.final_nav:>13,.0f} | {r.total_return_pct:>7.2f}% | {r.cagr_pct:>6.2f}% | {r.max_drawdown_pct:>7.2f}% | {r.max_capital_loss_pct:>8.2f}% | {r.sharpe_ratio:>7.2f} | {r.sell_events_count:>5} | {r.whipsaw_loss_count:>8} | Rp {r.total_fees_paid:>9,.0f}")
    print("=" * 145)

    # Save to JSON
    summary_data = []
    for r in results:
        summary_data.append({
            "scenario": r.scenario_name,
            "total_invested": r.total_invested,
            "final_nav": r.final_nav,
            "total_return_pct": r.total_return_pct,
            "cagr_pct": r.cagr_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "max_capital_loss_pct": r.max_capital_loss_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "sortino_ratio": r.sortino_ratio,
            "sell_events": r.sell_events_count,
            "whipsaw_losses": r.whipsaw_loss_count,
            "total_fees_paid": r.total_fees_paid,
            "trades": r.trade_log
        })
    with open("data/momentum_backtest_results.json", "w") as f:
        json.dump(summary_data, f, indent=2)

if __name__ == "__main__":
    main()
