"""AI Performance Analyst — Out-of-band Mistral-powered performance insights.

Design principles:
- Purely advisory / out-of-band: Never blocks or influences trading logic/gates.
- Structured JSON output: Instructs Mistral to output strictly formatted JSON.
- Throttled & Fail-safe: Safe network calls within Mistral RPM limits; skips gracefully on error without crashing services.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from Core.Support.ki_config import KiConfig, STATE_DIR

logger = logging.getLogger("KiBot.AIPerformanceAnalyst")

AI_REPORT_FILE = STATE_DIR / "ai_performance_report.json"
WIB = timezone(timedelta(hours=int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))))

ANALYST_SYSTEM_PROMPT = (
    "You are an expert quantitative crypto analyst for KiBot, an automated trading system.\n"
    "Your job is to review performance metrics across paper trading variants and write a concise, structured report in Bahasa Indonesia.\n"
    "IMPORTANT DIRECTIVE: Your output is strictly OBSERVATIONAL and HYPOTHETICAL for human operators to review.\n"
    "You MUST NOT give direct operational instructions or assume your hypotheses will automatically alter bot code/thresholds.\n"
    "OUTPUT FORMAT: Return STRICT, COMPACT JSON ONLY with the following exact schema:\n"
    "{\n"
    '  "summary_text": "Bahasa Indonesia summary (200-400 words) analyzing trends, variant behavior, win rates, and PnL.",\n'
    '  "observations": ["bullet point 1", "bullet point 2", ...],\n'
    '  "hypotheses": ["hypothesis 1", "hypothesis 2", ...],\n'
    '  "suggested_investigation_areas": ["area 1", "area 2", ...]\n'
    "}"
)


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val in (None, "", "None", "nan"):
            return default
        return float(val)
    except Exception:
        return default


def collect_performance_metrics() -> Dict[str, Any]:
    """Collects multi-variant comparison summary, exit reasons, and top pair performance."""
    from Core.Intelligence.trade_history import HISTORY_DIR

    variants = ["CONSERVATIVE", "AGGRESSIVE", "DEFAULT", "AI_ASSISTED"]
    variant_stats: Dict[str, Dict[str, Any]] = {}

    for var in variants:
        eq_file = STATE_DIR / ("paper_equity.json" if var == "DEFAULT" else f"paper_equity_{var.lower()}.json")
        bankroll = 5000000.0
        equity = bankroll
        total_pnl = 0.0

        if eq_file.exists():
            try:
                eq = json.loads(eq_file.read_text(encoding="utf-8"))
                bankroll = _safe_float(eq.get("initial_bankroll_idr"), bankroll)
                equity = _safe_float(eq.get("current_equity_idr"), bankroll)
                total_pnl = _safe_float(eq.get("total_pnl_idr"), 0.0)
            except Exception:
                pass

        variant_stats[var] = {
            "variant_id": var,
            "bankroll_idr": bankroll,
            "equity_idr": equity,
            "total_pnl_idr": total_pnl,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "avg_pnl_idr": 0.0,
            "exit_reasons": {},
            "pair_wins": {},
            "pair_losses": {},
        }

    # Aggregate metrics from trade history jsonl files
    if HISTORY_DIR.exists():
        for f in HISTORY_DIR.glob("*.jsonl"):
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    status = str(row.get("status") or row.get("state") or "").upper()
                    if status not in ("CLOSED", "RECONCILED", "FILLED"):
                        continue

                    var_id = str(row.get("variant_id") or "DEFAULT").upper()
                    if var_id not in variant_stats:
                        var_id = "DEFAULT"

                    stats = variant_stats[var_id]
                    stats["total_trades"] += 1

                    pnl_pct = _safe_float(row.get("realized_pnl_pct"))
                    pnl_idr = _safe_float(row.get("realized_pnl_idr") or row.get("net_realized_pnl_idr"))
                    reason = str(row.get("exit_reason") or row.get("reason") or "UNKNOWN").upper()
                    pair = str(row.get("pair") or row.get("symbol") or "UNKNOWN").upper()

                    stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1

                    if pnl_pct > 0 or pnl_idr > 0:
                        stats["wins"] += 1
                        stats["pair_wins"][pair] = stats["pair_wins"].get(pair, 0) + 1
                    else:
                        stats["losses"] += 1
                        stats["pair_losses"][pair] = stats["pair_losses"].get(pair, 0) + 1
            except Exception as exc:
                logger.debug("Error reading trade history file %s: %s", f, exc)

    # Compute final derived stats
    for var, stats in variant_stats.items():
        tot = stats["total_trades"]
        if tot > 0:
            stats["win_rate_pct"] = round((stats["wins"] / tot) * 100.0, 1)
            stats["avg_pnl_idr"] = round(stats["total_pnl_idr"] / tot, 2)
        
        # Sort top pairs for prompt brevity
        stats["top_winning_pairs"] = sorted(stats["pair_wins"].items(), key=lambda x: x[1], reverse=True)[:5]
        stats["top_losing_pairs"] = sorted(stats["pair_losses"].items(), key=lambda x: x[1], reverse=True)[:5]
        stats.pop("pair_wins", None)
        stats.pop("pair_losses", None)

    return {
        "collected_at": datetime.now(WIB).isoformat(),
        "variant_stats": variant_stats,
    }


def _call_mistral_analyst(metrics: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Invokes Mistral via query_ai with rate-limit protection and fail-safe handling."""
    import asyncio
    from Core.Intelligence.kibot_ai_coordinator import query_ai

    compact_metrics = {}
    for var, stats in metrics.get("variant_stats", {}).items():
        compact_metrics[var] = {
            "trades": stats.get("total_trades", 0),
            "win_rate_pct": stats.get("win_rate_pct", 0.0),
            "total_pnl_idr": stats.get("total_pnl_idr", 0.0),
            "exit_reasons": stats.get("exit_reasons", {}),
            "top_wins": stats.get("top_winning_pairs", [])[:3],
            "top_losses": stats.get("top_losing_pairs", [])[:3],
        }

    context = {
        "metrics_json": json.dumps(compact_metrics, indent=2, ensure_ascii=False)
    }

    try:
        parsed = asyncio.run(query_ai("AI_PERFORMANCE_ANALYST", context, force_refresh=True))
        if not parsed or parsed.get("is_fallback"):
            logger.warning("[AI Analyst] query_ai call returned empty response or fallback.")
            return None

        if isinstance(parsed, dict) and ("summary_text" in parsed or "observations" in parsed):
            # Normalize dictionary outputs to lists if Mistral returns object instead of array
            for k in ("observations", "hypotheses", "suggested_investigation_areas"):
                val = parsed.get(k)
                if isinstance(val, dict):
                    parsed[k] = [f"{sub_k}: {json.dumps(sub_v, ensure_ascii=False)}" if isinstance(sub_v, (dict, list)) else f"{sub_k}: {sub_v}" for sub_k, sub_v in val.items()]
                elif isinstance(val, list):
                    parsed[k] = [json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item) for item in val]
            return parsed
        else:
            logger.warning("[AI Analyst] Mistral response JSON missing expected keys: %s", parsed)
            return None
    except Exception as exc:
        logger.warning("[AI Analyst] Failed to query Mistral: %s", exc)
        return None


def run_performance_analysis(send_telegram: bool = False) -> Dict[str, Any]:
    """Runs performance analysis, saves output to state/ai_performance_report.json, and optionally notifies Telegram."""
    metrics = collect_performance_metrics()
    report_data: Dict[str, Any] = {
        "timestamp_wib": datetime.now(WIB).isoformat(),
        "status": "FAILED",
        "metrics": metrics,
        "ai_report": None,
    }

    ai_analysis = _call_mistral_analyst(metrics)
    if ai_analysis:
        report_data["status"] = "SUCCESS"
        report_data["ai_report"] = ai_analysis
        logger.info("[AI Analyst] Performance report generated successfully.")
    else:
        report_data["status"] = "FALLBACK_EMPTY"
        report_data["ai_report"] = {
            "summary_text": "Laporan AI sementara tidak tersedia (Mistral unavailable / rate limit). Silakan coba lagi nanti via `bin/kibotctl ai-report`.",
            "observations": ["Panggilan Mistral gagal atau timeout."],
            "hypotheses": ["Kemungkinan rate limit / isu jaringan sementara."],
            "suggested_investigation_areas": ["Periksa log kibot_ai_coordinator."],
        }

    # Save report to disk atomically
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_file = AI_REPORT_FILE.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_file.replace(AI_REPORT_FILE)
    except Exception as exc:
        logger.error("[AI Analyst] Failed to save AI report to %s: %s", AI_REPORT_FILE, exc)

    # Send Telegram notification if requested
    if send_telegram and report_data.get("ai_report"):
        try:
            from Core.Support.telegram_helper import send_telegram_message

            summary_short = report_data["ai_report"].get("summary_text", "")[:350]
            msg = f"📊 *KiBot AI Performance Report*\n\n{summary_short}\n\n_Gunakan `./bin/kibotctl ai-report` untuk analisis lengkap._"
            send_telegram_message(msg)
        except Exception as exc:
            logger.debug("[AI Analyst] Telegram notification failed: %s", exc)

    return report_data


def get_latest_report() -> Dict[str, Any]:
    """Reads latest saved report from state/ai_performance_report.json."""
    if not AI_REPORT_FILE.exists():
        return {}
    try:
        return json.loads(AI_REPORT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
