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
    Generates irregular topups: random amount (200k - 1M IDR) spaced 18-42 days apart.
    First deposit happens on start_date so portfolio starts funded.
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
    max_capital_dd_pct: float
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
    sma_period: int = 200,
    check_frequency: str = "monthly", # "monthly", "daily", or "none" (baseline)
    asset_mode: str = "portfolio",   # "portfolio" (70/30), "btc" (100%), "eth" (100%)
    scenario_label: str = ""
) -> BacktestMetrics:
    # Merge BTC and ETH
    df = pd.merge(df_btc[["date", "close"]], df_eth[["date", "close"]], on="date", suffixes=("_btc", "_eth"))
    df = df.sort_values("date").reset_index(drop=True)
    
    # Calculate SMAs
    df["sma_btc"] = df["close_btc"].rolling(window=sma_period).mean()
    df["sma_eth"] = df["close_eth"].rolling(window=sma_period).mean()
    
    # Month ends
    df["is_month_end"] = False
    for i in range(len(df) - 1):
        if df.loc[i, "date"].month != df.loc[i+1, "date"].month:
            df.loc[i, "is_month_end"] = True
    df.loc[len(df)-1, "is_month_end"] = True

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
        sma_btc = row["sma_btc"]
        sma_eth = row["sma_eth"]
        is_month_end = row["is_month_end"]
        
        # 1. Incoming Topup
        if dt_str in topups:
            topup_amt = topups[dt_str]
            total_invested += topup_amt
            
            topup_btc = topup_amt * target_w_btc
            topup_eth = topup_amt * target_w_eth
            
            # For BTC slice:
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
                
            # For ETH slice:
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

        # 2. Check Regime Update
        sma_ready_btc = not pd.isna(sma_btc)
        sma_ready_eth = not pd.isna(sma_eth)
        
        check_now = False
        if check_frequency == "daily":
            check_now = True
        elif check_frequency == "monthly" and is_month_end:
            check_now = True
            
        if check_now:
            # Evaluate BTC
            if target_w_btc > 0 and sma_ready_btc:
                new_regime_btc = "SAFE" if p_btc > sma_btc else "DANGER"
                if new_regime_btc != regime_btc:
                    if new_regime_btc == "DANGER":
                        # Liquidate BTC
                        if btc_qty > 0:
                            gross = btc_qty * p_btc
                            fee = gross * SELL_FEE_RATE
                            net = gross - fee
                            cash_btc_idr += net
                            trade_log.append({
                                "date": dt_str, "action": "SELL_ALL_BTC_DANGER", "gross_idr": gross,
                                "fee_idr": fee, "price": p_btc, "qty": btc_qty, "sma": sma_btc
                            })
                            last_sell_btc = {"price": p_btc, "date": dt_str, "qty": btc_qty}
                            btc_qty = 0.0
                    else: # Switched back to SAFE
                        # Redeploy idle BTC cash
                        if cash_btc_idr > 0:
                            fee = cash_btc_idr * BUY_FEE_RATE
                            net = cash_btc_idr - fee
                            qty = net / p_btc
                            btc_qty += qty
                            redeploy_entry = {
                                "date": dt_str, "action": "REDEPLOY_BTC_SAFE", "gross_idr": cash_btc_idr,
                                "fee_idr": fee, "price": p_btc, "qty": qty, "sma": sma_btc
                            }
                            if last_sell_btc is not None:
                                price_diff_pct = (p_btc - last_sell_btc["price"]) / last_sell_btc["price"] * 100.0
                                redeploy_entry["sold_at_price"] = last_sell_btc["price"]
                                redeploy_entry["sold_at_date"] = last_sell_btc["date"]
                                redeploy_entry["price_diff_pct"] = price_diff_pct
                                if p_btc > last_sell_btc["price"]:
                                    whipsaw_losses += 1
                                    redeploy_entry["whipsaw_penalty_pct"] = price_diff_pct
                            trade_log.append(redeploy_entry)
                            cash_btc_idr = 0.0
                    regime_btc = new_regime_btc

            # Evaluate ETH
            if target_w_eth > 0 and sma_ready_eth:
                new_regime_eth = "SAFE" if p_eth > sma_eth else "DANGER"
                if new_regime_eth != regime_eth:
                    if new_regime_eth == "DANGER":
                        # Liquidate ETH
                        if eth_qty > 0:
                            gross = eth_qty * p_eth
                            fee = gross * SELL_FEE_RATE
                            net = gross - fee
                            cash_eth_idr += net
                            trade_log.append({
                                "date": dt_str, "action": "SELL_ALL_ETH_DANGER", "gross_idr": gross,
                                "fee_idr": fee, "price": p_eth, "qty": eth_qty, "sma": sma_eth
                            })
                            last_sell_eth = {"price": p_eth, "date": dt_str, "qty": eth_qty}
                            eth_qty = 0.0
                    else: # Switched back to SAFE
                        # Redeploy idle ETH cash
                        if cash_eth_idr > 0:
                            fee = cash_eth_idr * BUY_FEE_RATE
                            net = cash_eth_idr - fee
                            qty = net / p_eth
                            eth_qty += qty
                            redeploy_entry = {
                                "date": dt_str, "action": "REDEPLOY_ETH_SAFE", "gross_idr": cash_eth_idr,
                                "fee_idr": fee, "price": p_eth, "qty": qty, "sma": sma_eth
                            }
                            if last_sell_eth is not None:
                                price_diff_pct = (p_eth - last_sell_eth["price"]) / last_sell_eth["price"] * 100.0
                                redeploy_entry["sold_at_price"] = last_sell_eth["price"]
                                redeploy_entry["sold_at_date"] = last_sell_eth["date"]
                                redeploy_entry["price_diff_pct"] = price_diff_pct
                                if p_eth > last_sell_eth["price"]:
                                    whipsaw_losses += 1
                                    redeploy_entry["whipsaw_penalty_pct"] = price_diff_pct
                            trade_log.append(redeploy_entry)
                            cash_eth_idr = 0.0
                    regime_eth = new_regime_eth

        # End of day NAV
        daily_nav = (btc_qty * p_btc) + (eth_qty * p_eth) + cash_btc_idr + cash_eth_idr
        daily_nav_list.append(daily_nav)
        daily_invested_list.append(total_invested)
        dates_list.append(row["date"])

    # Build series
    nav_s = pd.Series(daily_nav_list, index=pd.to_datetime(dates_list))
    inv_s = pd.Series(daily_invested_list, index=pd.to_datetime(dates_list))

    # Unit price calculation (Time-Weighted NAV per unit, standard mutual fund accounting)
    unit_price = pd.Series(index=nav_s.index, dtype=float)
    n_days = len(nav_s)
    
    # Day 0 initialization: first deposit
    first_nav = nav_s.iloc[0]
    first_inv = inv_s.iloc[0]
    # Initial unit price set to 100.0
    units = first_inv / 100.0
    unit_price.iloc[0] = first_nav / units

    for i in range(1, n_days):
        flow = inv_s.iloc[i] - inv_s.iloc[i-1]
        prior_unit_price = unit_price.iloc[i-1]
        
        # Inflow creates new units at prior close unit price
        if flow > 0:
            units += (flow / prior_unit_price)
            
        unit_price.iloc[i] = nav_s.iloc[i] / units

    # Maximum Drawdown on Unit Price (True Time-Weighted Investment Performance Drawdown)
    running_max_unit = unit_price.cummax()
    unit_dd_series = (unit_price - running_max_unit) / running_max_unit * 100.0
    max_unit_dd = abs(unit_dd_series.min())

    # Capital Drawdown on Actual Portfolio Value (NAV vs Cumulative Invested Capital)
    # i.e., Worst unrealized loss percentage relative to invested capital: (NAV - Invested) / Invested
    unrealized_pnl_pct = (nav_s - inv_s) / inv_s * 100.0
    worst_capital_loss_pct = abs(min(0.0, unrealized_pnl_pct.min()))

    final_invested = inv_s.iloc[-1]
    final_nav = nav_s.iloc[-1]
    total_ret = ((final_nav - final_invested) / final_invested) * 100.0
    years = n_days / 365.25
    cagr = (((final_nav / final_invested) ** (1.0 / years)) - 1.0) * 100.0 if final_nav > 0 and final_invested > 0 else 0.0

    daily_rets = unit_price.pct_change().dropna()
    rf = 0.05 # 5% risk free rate
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
        max_capital_dd_pct=worst_capital_loss_pct,
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
    print(f"Generated {len(topups)} irregular topups totaling Rp {total_topup_idr:,.0f}\n")

    scenarios = [
        # Combined Portfolio 70/30
        ("PORTFOLIO 70/30: Baseline DCA (No Filter)", 200, "none", "portfolio"),
        ("PORTFOLIO 70/30: Faber Monthly SMA-200", 200, "monthly", "portfolio"),
        ("PORTFOLIO 70/30: Faber Daily SMA-200", 200, "daily", "portfolio"),
        ("PORTFOLIO 70/30: Faber Monthly SMA-150", 150, "monthly", "portfolio"),
        ("PORTFOLIO 70/30: Faber Daily SMA-150", 150, "daily", "portfolio"),
        ("PORTFOLIO 70/30: Faber Monthly SMA-250", 250, "monthly", "portfolio"),
        ("PORTFOLIO 70/30: Faber Daily SMA-250", 250, "daily", "portfolio"),

        # BTC Only
        ("BTC 100%: Baseline DCA (No Filter)", 200, "none", "btc"),
        ("BTC 100%: Faber Monthly SMA-200", 200, "monthly", "btc"),
        ("BTC 100%: Faber Daily SMA-200", 200, "daily", "btc"),
        ("BTC 100%: Faber Monthly SMA-150", 150, "monthly", "btc"),
        ("BTC 100%: Faber Daily SMA-150", 150, "daily", "btc"),
        ("BTC 100%: Faber Monthly SMA-250", 250, "monthly", "btc"),
        ("BTC 100%: Faber Daily SMA-250", 250, "daily", "btc"),

        # ETH Only
        ("ETH 100%: Baseline DCA (No Filter)", 200, "none", "eth"),
        ("ETH 100%: Faber Monthly SMA-200", 200, "monthly", "eth"),
        ("ETH 100%: Faber Daily SMA-200", 200, "daily", "eth"),
        ("ETH 100%: Faber Monthly SMA-150", 150, "monthly", "eth"),
        ("ETH 100%: Faber Daily SMA-150", 150, "daily", "eth"),
        ("ETH 100%: Faber Monthly SMA-250", 250, "monthly", "eth"),
        ("ETH 100%: Faber Daily SMA-250", 250, "daily", "eth"),
    ]

    results = []
    trade_logs_dict = {}

    for name, sma_p, freq, asset_m in scenarios:
        res = run_simulation(
            df_btc, df_eth, topups, sma_period=sma_p, check_frequency=freq,
            asset_mode=asset_m, scenario_label=name
        )
        results.append(res)
        trade_logs_dict[name] = res

    # Format Results Table
    print("=" * 140)
    print(f"{'SCENARIO':<42} | {'FINAL NAV (IDR)':<16} | {'RETURN%':<8} | {'CAGR%':<7} | {'MAX DD%':<8} | {'CAP LOSS%':<9} | {'SHARPE':<7} | {'SELLS':<5} | {'WHIPSAWS':<8} | {'FEES (IDR)':<12}")
    print("=" * 140)
    for r in results:
        print(f"{r.scenario_name:<42} | Rp {r.final_nav:>13,.0f} | {r.total_return_pct:>7.2f}% | {r.cagr_pct:>6.2f}% | {r.max_drawdown_pct:>7.2f}% | {r.max_capital_dd_pct:>8.2f}% | {r.sharpe_ratio:>7.2f} | {r.sell_events_count:>5} | {r.whipsaw_loss_count:>8} | Rp {r.total_fees_paid:>9,.0f}")
    print("=" * 140)

    # Save detailed JSON summary for report analysis
    summary_data = []
    for r in results:
        summary_data.append({
            "scenario": r.scenario_name,
            "total_invested": r.total_invested,
            "final_nav": r.final_nav,
            "total_return_pct": r.total_return_pct,
            "cagr_pct": r.cagr_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "max_capital_dd_pct": r.max_capital_dd_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "sortino_ratio": r.sortino_ratio,
            "sell_events": r.sell_events_count,
            "whipsaw_losses": r.whipsaw_loss_count,
            "total_fees_paid": r.total_fees_paid,
            "trades": r.trade_log
        })
    with open("data/trend_filter_backtest_results.json", "w") as f:
        json.dump(summary_data, f, indent=2)

if __name__ == "__main__":
    main()
