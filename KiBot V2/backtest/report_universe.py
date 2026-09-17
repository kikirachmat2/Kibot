"""
KiBot V2 Universe Backtest Report Generator.
Generates comprehensive analysis reports for broad universe backtests:
- Per-pair aggregation (Trades, WR, Net PnL, Max DD, PF, Best Strategy)
- Per-strategy aggregation (Trades, WR, Net PnL, PF, Frequency)
- Top 10 Pairs by Net Profit
- Top 5 Strategies by Net Profit
- Strict Shadow Ledger Qualification Recommendations:
  * Net PnL > 0 in >= 2 of 3 scenarios
  * PF > 1.10
  * Max DD < 8.0%
  * N trades >= 30
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd

logger = logging.getLogger("KiBotV2.Backtest.UniverseReport")


def generate_universe_report(results: Dict[str, Any], output_path: Path) -> str:
    """
    Generates Markdown report and saves it to output_path.
    Returns the markdown string.
    """
    scenarios = results.get("scenarios", [])
    raw_matrix = results.get("results", {})  # scenario -> pair -> strategy -> metrics

    # 1. Flatten all data points into a DataFrame for robust analysis
    records = []
    for sc, pairs in raw_matrix.items():
        for pair, strats in pairs.items():
            for strat, m in strats.items():
                records.append({
                    "scenario": sc,
                    "pair": pair,
                    "strategy": strat,
                    "n_trades": m.get("n_trades", 0),
                    "n_wins": m.get("n_wins", 0),
                    "n_losses": m.get("n_losses", 0),
                    "gross_pnl_idr": m.get("gross_pnl_idr", 0.0),
                    "friction_idr": m.get("total_friction_idr", 0.0),
                    "net_pnl_idr": m.get("net_pnl_idr", 0.0),
                    "net_pnl_pct": m.get("net_pnl_pct", 0.0),
                    "max_drawdown_pct": m.get("max_drawdown_pct", 0.0),
                    "profit_factor": m.get("profit_factor", 0.0),
                })

    df = pd.DataFrame(records)
    lines: List[str] = []

    lines.append("# REPORT EVALUASI BROAD UNIVERSE — KIBOT V2")
    lines.append("")
    lines.append(f"- **Total Skenario Diuji**: {len(scenarios)} ({', '.join(scenarios)})")
    lines.append(f"- **Total Pair Diuji**: {df['pair'].nunique() if not df.empty else 0}")
    lines.append(f"- **Total Strategi Diuji**: {df['strategy'].nunique() if not df.empty else 0}")
    lines.append(f"- **Total Evaluasi Matrix**: {len(df)}")
    lines.append("")

    if df.empty:
        lines.append("> [!WARNING]\n> Data backtest kosong.")
        content = "\n".join(lines)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        return content

    # -------------------------------------------------------------
    # 1. TABEL PER PAIR
    # -------------------------------------------------------------
    lines.append("## 1. Agregasi Kinerja Per Pair")
    lines.append("")
    lines.append("| Pair | Total Trades | Win Rate (%) | Net PnL (IDR) | Max DD (%) | Avg PF | Strategi Terbaik |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :--- |")

    pair_groups = df.groupby("pair")
    pair_summary = []

    for pair, p_df in pair_groups:
        tot_trades = int(p_df["n_trades"].sum())
        tot_wins = int(p_df["n_wins"].sum())
        wr = (tot_wins / tot_trades * 100.0) if tot_trades > 0 else 0.0
        tot_net_pnl = p_df["net_pnl_idr"].sum()
        max_dd = p_df["max_drawdown_pct"].max()
        # Filter valid PF
        valid_pf = p_df[p_df["profit_factor"] > 0]["profit_factor"]
        avg_pf = valid_pf.mean() if not valid_pf.empty else 0.0

        # Best strategy for this pair based on net pnl
        strat_pnl = p_df.groupby("strategy")["net_pnl_idr"].sum()
        best_strat = strat_pnl.idxmax() if not strat_pnl.empty else "-"
        best_pnl = strat_pnl.max() if not strat_pnl.empty else 0.0

        pair_summary.append({
            "pair": pair,
            "trades": tot_trades,
            "wr": wr,
            "net_pnl": tot_net_pnl,
            "max_dd": max_dd,
            "avg_pf": avg_pf,
            "best_strat": f"{best_strat} (Rp {best_pnl:+,.0f})",
        })

    # Sort descending by Net PnL
    pair_summary.sort(key=lambda x: x["net_pnl"], reverse=True)

    for p in pair_summary:
        lines.append(
            f"| `{p['pair']}` | {p['trades']} | {p['wr']:.1f}% | Rp {p['net_pnl']:+,.0f} | {p['max_dd']:.2f}% | {p['avg_pf']:.2f} | {p['best_strat']} |"
        )
    lines.append("")

    # -------------------------------------------------------------
    # 2. TABEL PER STRATEGY
    # -------------------------------------------------------------
    lines.append("## 2. Agregasi Kinerja Per Strategi")
    lines.append("")
    lines.append("| Strategi | Total Trades | Win Rate (%) | Net PnL (IDR) | Avg PF | Frekuensi (Trades/Pair/Scenario) |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")

    strat_groups = df.groupby("strategy")
    strat_summary = []

    for strat, s_df in strat_groups:
        tot_trades = int(s_df["n_trades"].sum())
        tot_wins = int(s_df["n_wins"].sum())
        wr = (tot_wins / tot_trades * 100.0) if tot_trades > 0 else 0.0
        tot_net_pnl = s_df["net_pnl_idr"].sum()
        valid_pf = s_df[s_df["profit_factor"] > 0]["profit_factor"]
        avg_pf = valid_pf.mean() if not valid_pf.empty else 0.0
        n_pairs = s_df["pair"].nunique() * s_df["scenario"].nunique()
        freq = (tot_trades / n_pairs) if n_pairs > 0 else 0.0

        strat_summary.append({
            "strategy": strat,
            "trades": tot_trades,
            "wr": wr,
            "net_pnl": tot_net_pnl,
            "avg_pf": avg_pf,
            "freq": freq,
        })

    strat_summary.sort(key=lambda x: x["net_pnl"], reverse=True)

    for s in strat_summary:
        lines.append(
            f"| **{s['strategy']}** | {s['trades']} | {s['wr']:.1f}% | Rp {s['net_pnl']:+,.0f} | {s['avg_pf']:.2f} | {s['freq']:.1f} |"
        )
    lines.append("")

    # -------------------------------------------------------------
    # 3. TOP 10 PAIRS BY NET PROFIT
    # -------------------------------------------------------------
    lines.append("## 3. Top 10 Pairs by Net Profit")
    lines.append("")
    lines.append("| Rank | Pair | Net PnL (IDR) | Total Trades | Win Rate (%) | Max DD (%) | Strategi Dominan |")
    lines.append("| :---: | :--- | :---: | :---: | :---: | :---: | :--- |")

    for idx, p in enumerate(pair_summary[:10], start=1):
        lines.append(
            f"| #{idx} | `{p['pair']}` | **Rp {p['net_pnl']:+,.0f}** | {p['trades']} | {p['wr']:.1f}% | {p['max_dd']:.2f}% | {p['best_strat']} |"
        )
    lines.append("")

    # -------------------------------------------------------------
    # 4. TOP 5 STRATEGIES BY NET PROFIT
    # -------------------------------------------------------------
    lines.append("## 4. Top 5 Strategies by Net Profit")
    lines.append("")
    lines.append("| Rank | Strategi | Net PnL (IDR) | Win Rate (%) | Total Trades | Avg PF |")
    lines.append("| :---: | :--- | :---: | :---: | :---: | :---: |")

    for idx, s in enumerate(strat_summary[:5], start=1):
        lines.append(
            f"| #{idx} | **{s['strategy']}** | **Rp {s['net_pnl']:+,.0f}** | {s['wr']:.1f}% | {s['trades']} | {s['avg_pf']:.2f} |"
        )
    lines.append("")

    # -------------------------------------------------------------
    # 5. REKOMENDASI SHADOW LEDGER (STRICT GATES)
    # -------------------------------------------------------------
    lines.append("## 5. Rekomendasi Shadow Ledger (Decision Gate Evaluation)")
    lines.append("")
    lines.append("Kriteria kelayakan:")
    lines.append("1. **Net PnL > 0** di minimal 2 dari 3 skenario.")
    lines.append("2. **Profit Factor > 1.10**.")
    lines.append("3. **Max Drawdown < 8.0%**.")
    lines.append("4. **Total Trades >= 30**.")
    lines.append("")

    qualified_combos = []

    # Evaluate each (pair, strategy) combination across scenarios
    pair_strat_groups = df.groupby(["pair", "strategy"])

    for (pair, strat), ps_df in pair_strat_groups:
        n_positive_scenarios = (ps_df["net_pnl_idr"] > 0).sum()
        total_pnl = ps_df["net_pnl_idr"].sum()
        total_trades = int(ps_df["n_trades"].sum())
        total_wins = int(ps_df["n_wins"].sum())
        wr = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0
        max_dd = ps_df["max_drawdown_pct"].max()

        valid_pf = ps_df[ps_df["profit_factor"] > 0]["profit_factor"]
        avg_pf = valid_pf.mean() if not valid_pf.empty else 0.0

        is_qualified = (
            n_positive_scenarios >= 2
            and avg_pf > 1.10
            and max_dd < 8.0
            and total_trades >= 30
        )

        if is_qualified:
            qualified_combos.append({
                "pair": pair,
                "strategy": strat,
                "pos_scenarios": f"{n_positive_scenarios}/{len(ps_df)}",
                "net_pnl": total_pnl,
                "trades": total_trades,
                "wr": wr,
                "pf": avg_pf,
                "max_dd": max_dd,
            })

    if qualified_combos:
        lines.append("### ✅ PASSED: Kombinasi yang LULUS Masuk Shadow Ledger")
        lines.append("")
        lines.append("| Pair | Strategi | Positif di Skenario | Total Trades | Win Rate (%) | Net PnL (IDR) | Avg PF | Max DD (%) |")
        lines.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        qualified_combos.sort(key=lambda x: x["net_pnl"], reverse=True)
        for q in qualified_combos:
            lines.append(
                f"| `{q['pair']}` | **{q['strategy']}** | {q['pos_scenarios']} | {q['trades']} | {q['wr']:.1f}% | **Rp {q['net_pnl']:+,.0f}** | {q['pf']:.2f} | {q['max_dd']:.2f}% |"
            )
    else:
        lines.append("### ❌ NONE PASSED: Tidak Ada Kombinasi yang Memenuhi Seluruh 4 Kriteria Kelayakan")
        lines.append("")
        lines.append("> [!NOTE]")
        lines.append("> Tidak ada kombinasi pair & strategi yang secara simultan memenuhi:")
        lines.append("> Net PnL > 0 di >= 2 skenario, PF > 1.10, Max DD < 8.0%, dan N >= 30 trades.")
        lines.append("> Tinjau tabel per pair dan per strategi untuk analisis kelemahan masing-masing.")

    lines.append("")

    report_content = "\n".join(lines)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    logger.info(f"[UniverseReport] Successfully wrote report to {output_path}")
    return report_content
