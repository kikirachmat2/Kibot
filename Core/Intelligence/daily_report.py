"""Telegram midnight report builder for KiBot strategy vNext."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
STATE = ROOT / "state"
WIB = timezone(timedelta(hours=7))


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _rp(value: Any) -> str:
    try:
        return f"Rp {float(value):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _pct(value: Any) -> str:
    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return "+0.00%"


def _top(items: List[Any], n: int = 3) -> List[Any]:
    return list(items or [])[:n]


def build_daily_report(telemetry: Dict[str, Any] | None = None) -> str:
    telemetry = telemetry or _read_json(STATE / "telemetry_snapshot.json", {})
    portfolio = telemetry.get("portfolio", {}) if isinstance(telemetry, dict) else {}
    heatmap = _read_json(STATE / "market_heatmap.json", {})
    journal_summary = {}
    try:
        from Core.Intelligence.decision_journal import summarize_today
        journal_summary = summarize_today()
    except Exception:
        journal_summary = {}
    probability = _read_json(STATE / "green_probability.json", {})
    order_summary = {}
    try:
        from Core.Intelligence.order_tracker import get_tracker
        order_summary = get_tracker().get_today_summary()
    except Exception:
        order_summary = {}
    try:
        from Core.Intelligence.trade_history import summarize_today as summarize_trade_history
        trade_summary = summarize_trade_history()
    except Exception:
        trade_summary = {}

    daily_color = str(portfolio.get("daily_color") or (portfolio.get("daily_state") or {}).get("color") or "FLAT").upper()
    combined = portfolio.get("combined_equity_idr", portfolio.get("equity_idr", 0))
    realized = portfolio.get("realized_pnl_idr", portfolio.get("pnl_idr", 0))
    unrealized = portfolio.get("unrealized_pnl_idr", 0)
    daily_pnl = portfolio.get("daily_pnl_idr", 0)

    daily_pnl_pct = portfolio.get("daily_pnl_pct")
    if daily_pnl_pct is None:
        try:
            previous_equity = float(combined) - float(daily_pnl)
            if previous_equity > 0:
                daily_pnl_pct = (float(daily_pnl) / previous_equity) * 100.0
            else:
                daily_pnl_pct = 0.0
        except Exception:
            daily_pnl_pct = 0.0

    cash = portfolio.get("idr_cash", 0)
    holdings = portfolio.get("coin_holdings_idr", 0)
    poly = portfolio.get("polymarket", {}) if isinstance(portfolio.get("polymarket"), dict) else {}

    top_candidates = _top(journal_summary.get("top_candidates", []), 3)
    candidate_lines = []
    for cand in top_candidates:
        candidate_lines.append(
            f"- {cand.get('symbol','?')} {cand.get('lifecycle','?')} "
            f"{cand.get('trade_grade', cand.get('entry_quality','?'))} "
            f"score {float(cand.get('opportunity_score') or cand.get('confidence') or 0):.2f}"
        )
    if not candidate_lines:
        candidate_lines = ["- No strong candidates recorded"]

    top_movers = _top(heatmap.get("top_movers", []), 3)
    mover_lines = [
        f"- {m.get('pair','?')} +{float(m.get('change_from_low_pct') or 0):.1f}% vol {_rp(m.get('vol_idr', 0))}"
        for m in top_movers
    ] or ["- UNKNOWN"]

    prob_pct = probability.get("estimated_green_probability_pct", 0)
    prob_quality = probability.get("confidence_quality", "WEAK")
    positives = probability.get("positive_drivers", []) or []
    negatives = probability.get("negative_drivers", []) or []

    services = telemetry.get("services", {}) if isinstance(telemetry, dict) else {}
    system_stats = (telemetry.get("system_stats", {}) or {}).get("BATAM_MASTER", {}) if isinstance(telemetry, dict) else {}
    services_ok = all(str(services.get(s, "active")).lower() in {"active", "online"} for s in ("kibot-master", "kibot-scanner", "kibot-executor", "ollama", "redis-server"))
    health_text = "OK" if services_ok else "DEGRADED"

    return f"""KiBot Daily Report — {datetime.now(WIB).date().isoformat()} WIB

STATE
Daily Color: {daily_color}
Combined Equity: {_rp(combined)}
Daily PnL: {_rp(daily_pnl)} ({_pct(daily_pnl_pct)})
Daily Yield: {_pct(daily_pnl_pct)}
Realized: {_rp(realized)}
Unrealized: {_rp(unrealized)}
Green Probability: {prob_pct}% ({prob_quality})

CAPITAL
Cash IDR: {_rp(cash)}
Coin Holdings: {_rp(holdings)}
Polymarket: ${float(poly.get('usdc_balance') or 0):.2f} / {_rp(poly.get('equity_idr', 0))}

TRADING SUMMARY
Orders Today: {order_summary.get('total', 0)} total, {order_summary.get('reconciled', 0)} reconciled, {order_summary.get('stale', 0)} stale
Trade History: {trade_summary.get('buy_fills', 0)} buy fills, {trade_summary.get('sell_fills', 0)} sell fills, realized {_rp(trade_summary.get('realized_pnl_idr', 0))}
Council: {journal_summary.get('entries', 0)} enter, {journal_summary.get('waits', 0)} wait, {journal_summary.get('exits', 0)} exit
Open Positions: {len(portfolio.get('active_positions') or [])}

TOP CANDIDATES
{chr(10).join(candidate_lines)}

MARKET
Regime: {heatmap.get('market_breadth', 'UNKNOWN')}
{chr(10).join(mover_lines)}

PROBABILITY DRIVERS
Positive: {', '.join(_top(positives, 3)) or 'None'}
Negative: {', '.join(_top(negatives, 3)) or 'None'}

SYSTEM HEALTH
State: {health_text}
CPU/RAM/Disk: {system_stats.get('cpu', '?')}% / {system_stats.get('ram', '?')}% / {system_stats.get('disk', '?')}%

OPERATOR ACTION
None unless an emergency alert follows."""
