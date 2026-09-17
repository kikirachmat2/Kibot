"""
KiBot V2 Backtest Report Generator.
Generates comprehensive Markdown reports evaluating scenarios against official Decision Gates:
- Expectancy weekly > +0.30%
- Profit Factor > 1.20
- Max Rolling Drawdown < 4.0%
- N trades >= 100 total
- Frequency >= 5 trades/week
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List
import pandas as pd


def generate_markdown_report(results: Dict[str, Any], output_path: Path) -> str:
    """
    Generates a structured Markdown report from backtest scenario results.
    Writes output to output_path and returns the markdown string.
    """
    lines: List[str] = [
        "# LAPORAN HASIL BACKTEST KUANTITATIF KIBOT V2",
        "",
        "> **Klasifikasi**: *Official Strategy Evaluation & Decision Gates Verification*  ",
        f"> **Tanggal Evaluasi**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        "> **Universe Pair**: BTCIDR, ETHIDR, SOLIDR (AVAXIDR Resmi Di-Exclude)  ",
        "> **Model Eksekusi**: Maker Limit Order (0.56% BTC/ETH, 0.70% SOL) + Oxford Adverse Selection Penalty (30% MR, 40% LL)",
        "",
        "---",
        "",
    ]

    # Approximate duration in weeks per scenario
    scenario_weeks = {
        "S1_2023_full": 52.14,
        "S2_Q3_2024": 13.14,
        "S3_2025_to_now": 89.0,
    }
    total_weeks = sum(scenario_weeks.values())

    strategy_stats: Dict[str, Dict[str, Any]] = {}

    # 1. Detail per Skenario
    for sc_name, sc_data in results.items():
        weeks = scenario_weeks.get(sc_name, 52.0)
        lines.append(f"## Skenario: `{sc_name}` (Durasi: ~{weeks:.1f} Minggu)")
        lines.append("")
        lines.append(
            "| Strategy | Pair | N Trades | WR (%) | Avg Win (%) | Avg Loss (%) | Gross PnL (IDR) | Friction (IDR) | Adverse (IDR) | Net PnL (IDR) | Net (%) | Max DD (%) | PF | Fee/Gross | Verdict |"
        )
        lines.append(
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
        )

        for pair, strat_dict in sc_data.items():
            for strat, res in strat_dict.items():
                n_trades = res.get("n_trades", 0)
                wr = res.get("win_rate", 0.0)
                avg_w = res.get("avg_win_pct", 0.0)
                avg_l = res.get("avg_loss_pct", 0.0)
                gross = res.get("gross_pnl_idr", 0.0)
                fric = res.get("total_friction_idr", 0.0)
                adv = res.get("total_adverse_penalty_idr", 0.0)
                net = res.get("net_pnl_idr", 0.0)
                net_pct = res.get("net_pnl_pct", 0.0)
                mdd = res.get("max_drawdown_pct", 0.0)
                pf = res.get("profit_factor", 0.0)
                fee_ratio = res.get("fee_to_gross_ratio", 0.0)

                # Pass criteria for individual row
                weekly_exp = net_pct / weeks if weeks > 0 else 0.0
                freq = n_trades / weeks if weeks > 0 else 0.0
                is_pass = (net > 0) and (pf > 1.20) and (mdd < 4.0)
                verdict = "✅ PASS" if is_pass else "❌ FAIL"

                lines.append(
                    f"| **{strat}** | {pair} | {n_trades} | {wr:.1f}% | +{avg_w:.2f}% | {avg_l:.2f}% | "
                    f"{gross:,.0f} | {fric:,.0f} | {adv:,.0f} | **{net:,.0f}** | **{net_pct:+.2f}%** | "
                    f"{mdd:.2f}% | {pf:.2f} | {fee_ratio:.2f} | {verdict} |"
                )

                # Accumulate for Aggregate
                if strat not in strategy_stats:
                    strategy_stats[strat] = {
                        "trades": 0,
                        "wins": 0,
                        "gross": 0.0,
                        "friction": 0.0,
                        "adverse": 0.0,
                        "net": 0.0,
                        "max_dd": 0.0,
                        "total_win_nom": 0.0,
                        "total_loss_nom": 0.0,
                    }
                s_stat = strategy_stats[strat]
                s_stat["trades"] += n_trades
                s_stat["wins"] += res.get("n_wins", 0)
                s_stat["gross"] += gross
                s_stat["friction"] += fric
                s_stat["adverse"] += adv
                s_stat["net"] += net
                s_stat["max_dd"] = max(s_stat["max_dd"], mdd)

                # Win/loss nominals for aggregate PF
                if gross > 0:
                    s_stat["total_win_nom"] += max(0.0, net)
                if net < 0:
                    s_stat["total_loss_nom"] += abs(net)

        lines.append("")
        lines.append("---")
        lines.append("")

    # 2. Section Aggregate Lintas Skenario & Pair
    lines.append("## AGGREGATE PERFORMANCE (Lintas 3 Skenario & 3 Pair)")
    lines.append("")
    lines.append(
        "| Strategy | Total Trades | Freq (tr/wk) | WR (%) | Total Gross (IDR) | Total Friction | Total Adverse | Total Net (IDR) | Weekly Exp (%) | Max DD (%) | PF | Overall Status |"
    )
    lines.append(
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    )

    decision_summary: Dict[str, Dict[str, Any]] = {}

    for strat, stat in strategy_stats.items():
        tot_trades = stat["trades"]
        tot_wins = stat["wins"]
        wr = (tot_wins / tot_trades * 100.0) if tot_trades > 0 else 0.0
        freq = tot_trades / total_weeks if total_weeks > 0 else 0.0
        tot_net = stat["net"]
        # Approximate initial base 10M
        net_pct = (tot_net / 10_000_000.0) * 100.0
        weekly_exp = net_pct / total_weeks if total_weeks > 0 else 0.0
        pf = (stat["total_win_nom"] / stat["total_loss_nom"]) if stat["total_loss_nom"] > 0 else (999.0 if stat["total_win_nom"] > 0 else 0.0)
        mdd = stat["max_dd"]

        # Decision Gate Verification
        pass_exp = weekly_exp > 0.30
        pass_pf = pf > 1.20
        pass_mdd = mdd < 4.0
        pass_n = tot_trades >= 100
        pass_freq = freq >= 5.0

        all_pass = pass_exp and pass_pf and pass_mdd and pass_n and pass_freq
        status = "🟢 QUALIFIED" if all_pass else "🔴 REJECTED"

        decision_summary[strat] = {
            "all_pass": all_pass,
            "weekly_exp": weekly_exp,
            "pf": pf,
            "mdd": mdd,
            "tot_trades": tot_trades,
            "freq": freq,
            "pass_exp": pass_exp,
            "pass_pf": pass_pf,
            "pass_mdd": pass_mdd,
            "pass_n": pass_n,
            "pass_freq": pass_freq,
        }

        lines.append(
            f"| **{strat}** | {tot_trades} | {freq:.1f} | {wr:.1f}% | {stat['gross']:,.0f} | "
            f"{stat['friction']:,.0f} | {stat['adverse']:,.0f} | **{tot_net:,.0f}** | "
            f"**{weekly_exp:+.3f}%** | {mdd:.2f}% | {pf:.2f} | **{status}** |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")

    # 3. Section Decision
    lines.append("## DECISION & EVALUATION GATES (Ambang Batas Mutlak)")
    lines.append("")
    lines.append("| Strategy | Expectancy Wk > +0.30% | PF > 1.20 | Max DD < 4.0% | N >= 100 | Freq >= 5/wk | FINAL VERDICT |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")

    for strat, d in decision_summary.items():
        c_exp = f"✅ ({d['weekly_exp']:+.3f}%)" if d["pass_exp"] else f"❌ ({d['weekly_exp']:+.3f}%)"
        c_pf = f"✅ ({d['pf']:.2f})" if d["pass_pf"] else f"❌ ({d['pf']:.2f})"
        c_mdd = f"✅ ({d['mdd']:.2f}%)" if d["pass_mdd"] else f"❌ ({d['mdd']:.2f}%)"
        c_n = f"✅ ({d['tot_trades']})" if d["pass_n"] else f"❌ ({d['tot_trades']})"
        c_freq = f"✅ ({d['freq']:.1f}/wk)" if d["pass_freq"] else f"❌ ({d['freq']:.1f}/wk)"
        verdict = "**LULUS (APPROVED)**" if d["all_pass"] else "**TIDAK LULUS (REJECTED)**"

        lines.append(f"| **{strat}** | {c_exp} | {c_pf} | {c_mdd} | {c_n} | {c_freq} | {verdict} |")

    lines.append("")
    report_text = "\n".join(lines)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    return report_text
