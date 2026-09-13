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


def determine_security_status(
    governor_data: Dict[str, Any],
    services_ok: bool = True,
) -> Tuple[str, str, str]:
    """
    Returns (badge_emoji, status_tag, status_desc).
    Terhubung langsung ke overall_drawdown_pct dan circuit_breaker_tripped dari CapitalGovernor.
    """
    is_tripped = bool(governor_data.get("circuit_breaker_tripped", False))
    status = str(governor_data.get("status", "")).upper()
    dd_pct = float(governor_data.get("overall_drawdown_pct", 0.0) or 0.0)
    dd_threshold = float(governor_data.get("overall_drawdown_threshold_pct", 18.0) or 18.0)
    global_hard_stop = bool(governor_data.get("global_hard_stop", False))
    allow_orders = bool(governor_data.get("allow_new_orders", True))
    reset_pending = bool(governor_data.get("daily_reset_pending", False))

    if is_tripped or dd_pct >= dd_threshold or status == "OVERALL_DRAWDOWN_BREAKER_TRIPPED":
        return (
            "🔴",
            "TERKUNCI",
            f"Drawdown {dd_pct:.1f}% (≥{dd_threshold:.0f}% limit). Transaksi disetop demi lindungi modal.",
        )
    if global_hard_stop:
        return (
            "🔴",
            "TERKUNCI",
            "Sistem dikunci darurat (global hard stop aktif). Transaksi diblokir total.",
        )
    if not services_ok:
        return (
            "🔴",
            "KENDALA SISTEM",
            "Satu atau lebih service utama tidak aktif. Periksa sistem.",
        )
    if dd_pct >= 8.0:
        return (
            "🟠",
            "SIAGA",
            f"Drawdown {dd_pct:.1f}% mendekati batas risiko ({dd_threshold:.0f}%). Proteksi modal siaga.",
        )
    if dd_pct >= 4.0 or not allow_orders or reset_pending:
        reason = governor_data.get("allow_new_orders_reason") or "Proteksi modal aktif"
        return (
            "🟡",
            "WASPADA",
            f"Drawdown {dd_pct:.1f}%. {reason}.",
        )
    return (
        "🟢",
        "AMAN",
        f"Drawdown {dd_pct:.1f}% (<4.0%). Seluruh pengaman modal & sistem aktif normal.",
    )


def determine_operator_action(
    status_tag: str,
    governor_data: Dict[str, Any],
) -> str:
    if status_tag == "TERKUNCI":
        return "Jalankan 'bin/kibotctl drawdown-ack' setelah evaluasi risiko untuk membuka kunci proteksi."
    if status_tag == "KENDALA SISTEM":
        return "Jalankan 'bin/kibotctl doctor' untuk memeriksa service yang offline."
    if status_tag in {"SIAGA", "WASPADA"}:
        return "Pantau pergerakan pasar; pengaman modal siaga otomatis tanpa intervensi manual."
    return "Tidak ada tindakan yang diperlukan (Sistem berjalan normal)."


def determine_trading_reason(
    governor_data: Dict[str, Any],
    portfolio: Dict[str, Any],
    order_summary: Dict[str, Any],
    trade_summary: Dict[str, Any],
    probability: Dict[str, Any],
    journal_summary: Dict[str, Any],
    heatmap: Dict[str, Any],
    security_status_tag: str,
) -> str:
    """
    Memilih 1 kalimat paling relevan dari kondisi AKTUAL saat laporan dibuat:
    - Circuit breaker aktif / Terkunci
    - Saldo kas IDR tidak mencukupi
    - Pintu order diblokir governor
    - Posisi aktif sedang dipegang
    - Sudah ada eksekusi beli hari ini
    - Kondisi pasar risk-off / ekstrem
    - Belum ada kandidat grade A/B
    - Menunggu evaluasi council
    - Standby normal
    """
    # 1. Circuit breaker tripped
    if security_status_tag == "TERKUNCI" or governor_data.get("circuit_breaker_tripped"):
        return "Pintu transaksi dikunci total oleh Circuit Breaker (Drawdown ≥18%). Evaluasi risiko diperlukan sebelum transaksi dapat dilanjutkan."

    # 2. Allow new orders False dari Governor
    if not governor_data.get("allow_new_orders", True):
        reason = governor_data.get("allow_new_orders_reason") or "batas risiko tercapai"
        return f"Pintu transaksi dikunci oleh pengaman modal (Capital Governor): {reason}."

    # 3. Sudah ada transaksi beli hari ini
    buy_fills = int(trade_summary.get("buy_fills", 0) or 0)
    if buy_fills > 0:
        return f"Bot telah mengeksekusi {buy_fills} transaksi beli hari ini dan memantau perkembangan siklus pasar."

    # 4. Ada posisi aktif riil yang sedang dipegang
    active_positions = portfolio.get("active_positions", []) or []
    real_positions = [p for p in active_positions if float(p.get("value_idr", 0.0) or 0.0) >= 1000.0]
    if len(real_positions) > 0:
        symbols = ", ".join(p.get("coin", "").upper() for p in real_positions[:3])
        return f"Bot sedang mengawal {len(real_positions)} posisi aktif ({symbols}) dan fokus mengamankan target laba / stop-loss."

    # 5. Kas IDR tidak mencukupi (di bawah min order Indodax Rp 10.000)
    cash_idr = float(portfolio.get("cash_idr", portfolio.get("idr_cash", 0.0)) or 0.0)
    if cash_idr < 10000.0 and len(real_positions) == 0:
        return f"Saldo kas IDR ({_rp(cash_idr)}) belum mencukupi untuk membuka pesanan baru (minimal Rp 10.000)."

    # 6. Market regime defensif / risk-off
    breadth = str(heatmap.get("market_breadth", "")).upper()
    if breadth in {"RISK_OFF", "DEFENSIVE", "EXTREME_FEAR", "CRITICAL", "BEARISH"}:
        return "Kondisi pasar saat ini defensif/berisiko tinggi; bot menahan diri demi menghindari false breakout."

    # 7. Tidak ada kandidat Grade A/B atau probabilitas hijau lemah
    prob_pct = float(probability.get("estimated_green_probability_pct", 0.0) or 0.0)
    prob_quality = str(probability.get("confidence_quality", "")).upper()
    top_cands = journal_summary.get("top_candidates", []) or []
    has_high_grade = any(
        str(c.get("trade_grade") or c.get("entry_quality") or "").upper() in {"A", "A+", "B+"}
        or float(c.get("opportunity_score") or c.get("confidence") or 0.0) >= 0.85
        for c in top_cands
    )
    if not has_high_grade or prob_pct < 40.0 or prob_quality in {"WEAK", "POOR"}:
        return "Belum ada kandidat koin yang memenuhi standar profit probabilitas tinggi (Grade A/B); bot menunggu setup terbaik."

    # 8. Council sedang wait
    waits = int(journal_summary.get("waits", 0) or 0)
    entries = int(journal_summary.get("entries", 0) or 0)
    if waits > 0 and entries == 0:
        return "Kondisi pasar belum memenuhi konfirmasi sinyal beli; bot standby menunggu momentum terbaik."

    # 9. Default
    return "Bot aktif memantau pasar 24/7 dan hanya masuk saat sinyal profit aman terverifikasi."


def build_concise_daily_report(
    telemetry: Dict[str, Any] | None = None,
    governor_data: Dict[str, Any] | None = None,
) -> str:
    telemetry = telemetry or _read_json(STATE / "telemetry_snapshot.json", {})
    portfolio = telemetry.get("portfolio", {}) if isinstance(telemetry, dict) else {}
    governor_data = governor_data or _read_json(STATE / "capital_governor.json", {})
    heatmap = _read_json(STATE / "market_heatmap.json", {})
    probability = _read_json(STATE / "green_probability.json", {})

    journal_summary = {}
    try:
        from Core.Intelligence.decision_journal import summarize_today
        journal_summary = summarize_today()
    except Exception:
        journal_summary = {}

    order_summary = {}
    try:
        from Core.Intelligence.order_tracker import get_tracker
        order_summary = get_tracker().get_today_summary()
    except Exception:
        order_summary = {}

    trade_summary = {}
    try:
        from Core.Intelligence.trade_history import summarize_today as summarize_trade_history
        trade_summary = summarize_trade_history()
    except Exception:
        trade_summary = {}

    combined = portfolio.get(
        "total_balance_idr",
        portfolio.get("combined_equity_idr", portfolio.get("equity_idr", governor_data.get("current_total_equity_idr", governor_data.get("total_balance_idr", 0)))),
    )
    reset_balance = portfolio.get(
        "reset_total_balance_idr",
        portfolio.get("start_total_equity_idr", portfolio.get("starting_equity_today_idr", governor_data.get("start_total_equity_idr", 0))),
    )
    realized = portfolio.get("realized_pnl_idr", portfolio.get("pnl_idr", trade_summary.get("realized_pnl_idr", 0)))
    daily_return = portfolio.get("daily_return_idr", portfolio.get("daily_pnl_idr", governor_data.get("daily_return_idr", 0)))
    daily_return_pct = portfolio.get("daily_return_pct", portfolio.get("daily_pnl_pct", governor_data.get("daily_return_pct")))

    if daily_return_pct is None:
        try:
            previous_equity = float(reset_balance) if reset_balance else float(combined) - float(daily_return)
            if previous_equity > 0:
                daily_return_pct = (float(daily_return) / previous_equity) * 100.0
            else:
                daily_return_pct = 0.0
        except Exception:
            daily_return_pct = 0.0

    # Sanitize micro dust (< Rp 10.000 and return < Rp 500)
    if float(combined or 0) < 10000.0 and abs(float(daily_return or 0)) < 500.0:
        combined_display = "Rp 0"
        return_display = "Rp 0 (+0.00%)"
    else:
        combined_display = _rp(combined)
        return_display = f"{_rp(daily_return)} ({_pct(daily_return_pct)})"

    services = telemetry.get("services", {}) if isinstance(telemetry, dict) else {}
    services_ok = all(
        str(services.get(s, "active")).lower() in {"active", "online"}
        for s in ("kibot-master", "kibot-scanner", "kibot-executor", "ollama", "redis-server")
    )
    badge, status_tag, status_desc = determine_security_status(governor_data, services_ok=services_ok)
    operator_action = determine_operator_action(status_tag, governor_data)

    buy_fills = int(trade_summary.get("buy_fills", 0) or 0)
    sell_fills = int(trade_summary.get("sell_fills", 0) or 0)
    wl_ratio = portfolio.get("wl_ratio", "0W / 0L")

    active_pos = portfolio.get("active_positions", []) or []
    real_pos = [p for p in active_pos if float(p.get("value_idr", 0.0) or 0.0) >= 1000.0]
    dust_pos = [p for p in active_pos if float(p.get("value_idr", 0.0) or 0.0) < 1000.0]

    if dust_pos and not real_pos:
        dust_val = sum(float(p.get("value_idr", 0.0) or 0.0) for p in dust_pos)
        pos_str = f"0 aktif (+{len(dust_pos)} dust lama {_rp(dust_val)})"
    elif dust_pos:
        pos_str = f"{len(real_pos)} aktif (+{len(dust_pos)} dust lama)"
    else:
        pos_str = f"{len(real_pos)} aktif"

    trading_reason = determine_trading_reason(
        governor_data,
        portfolio,
        order_summary,
        trade_summary,
        probability,
        journal_summary,
        heatmap,
        status_tag,
    )
    reason_label = "Status Eksekusi" if buy_fills > 0 else "Alasan Belum Beli"

    today_str = datetime.now(WIB).date().isoformat()

    return f"""🤖 KiBot Daily Report — {today_str} WIB

💰 Saldo: {combined_display} | Hasil Hari Ini: {return_display}
🛡️ Status: {badge} {status_tag} — {status_desc}
📊 Trading Hari Ini: {buy_fills} beli, {sell_fills} jual | Hasil: {_rp(realized)} ({wl_ratio}) | Posisi: {pos_str}
❓ {reason_label}: {trading_reason}
🎯 Tindakan Operator: {operator_action}

ℹ️ Detail teknis: 'bin/kibotctl daily-report --full'"""


def build_detailed_daily_report(telemetry: Dict[str, Any] | None = None) -> str:
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
    combined = portfolio.get("total_balance_idr", portfolio.get("combined_equity_idr", portfolio.get("equity_idr", 0)))
    reset_balance = portfolio.get("reset_total_balance_idr", portfolio.get("start_total_equity_idr", portfolio.get("starting_equity_today_idr", 0)))
    realized = portfolio.get("realized_pnl_idr", portfolio.get("pnl_idr", 0))
    unrealized = portfolio.get("unrealized_pnl_idr", 0)
    daily_return = portfolio.get("daily_return_idr", portfolio.get("daily_pnl_idr", 0))

    daily_return_pct = portfolio.get("daily_return_pct", portfolio.get("daily_pnl_pct"))
    if daily_return_pct is None:
        try:
            previous_equity = float(reset_balance) if reset_balance else float(combined) - float(daily_return)
            if previous_equity > 0:
                daily_return_pct = (float(daily_return) / previous_equity) * 100.0
            else:
                daily_return_pct = 0.0
        except Exception:
            daily_return_pct = 0.0

    top_candidates = _top(journal_summary.get("top_candidates", []), 3)
    candidate_lines = []
    for cand in top_candidates:
        sym = cand.get("symbol") or cand.get("pair") or "?"
        stage = cand.get("lifecycle") or cand.get("pump_stage") or ""
        grade = cand.get("trade_grade") or cand.get("entry_quality")
        chg = cand.get("change_pct")
        score = float(cand.get("opportunity_score") or cand.get("confidence") or 0)

        parts = [f"- {sym}"]
        if stage and stage != "?":
            parts.append(str(stage))
        if grade and grade != "?":
            parts.append(f"grade {grade}")
        elif chg is not None:
            parts.append(f"+{float(chg):.1f}%")
        parts.append(f"score {score:.2f}")
        candidate_lines.append(" ".join(parts))
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
Total Saldo Gabungan: {_rp(combined)}
Saldo Setelah Reset: {_rp(reset_balance)}
Return Harian: {_rp(daily_return)}
PnL Harian %: {_pct(daily_return_pct)}
Realized: {_rp(realized)}
Unrealized: {_rp(unrealized)}
Green Probability: {prob_pct}% ({prob_quality})

CAPITAL
Indodax Cash: {_rp(portfolio.get('cash_idr', portfolio.get('idr_cash', 0)))}
Held Coin Value: {_rp(portfolio.get('held_coin_value_idr', portfolio.get('coin_holdings_idr', 0)))}

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


def build_daily_report(telemetry: Dict[str, Any] | None = None, full: bool = False) -> str:
    """Entrypoint for building KiBot daily strategy report."""
    if full:
        return build_detailed_daily_report(telemetry)
    return build_concise_daily_report(telemetry)


if __name__ == "__main__":
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(description="KiBot Daily Report Generator")
    parser.add_argument("--full", action="store_true", help="Generate full detailed report")
    parser.add_argument("--send", action="store_true", help="Send report to Telegram")
    args = parser.parse_args()

    report_text = build_daily_report(full=args.full)
    print(report_text)

    if args.send:
        from Core.Notifications.sovereign_notifier import SovereignNotifier
        notifier = SovereignNotifier()
        res = asyncio.run(notifier.send_daily_report(force=True, full=args.full))
        print(f"\n[Telegram Dispatch]: {'SUCCESS' if res else 'FAILED/THROTTLED'}")
