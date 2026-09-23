import pytest
from datetime import datetime, timezone, timedelta
from notifications.telegram_reporter import TelegramReporter

WIB = timezone(timedelta(hours=7))


def test_telegram_reporter_daily_format():
    reporter = TelegramReporter()
    holdings = {"BTC": 0.001, "ETH": 0.01}
    prices = {"BTC": 1_000_000_000.0, "ETH": 40_000_000.0}

    text = reporter.format_daily_report(
        nav_idr=1_400_000.0,
        cost_basis_idr=1_400_000.0,
        pnl_pct=0.0,
        holdings=holdings,
        prices=prices,
        cycle_phase="ACCUMULATE_70_30",
        system_health="HEALTHY",
        ts=datetime(2026, 9, 20, 8, 0, tzinfo=WIB),
    )

    assert "KIBOT V3 — LAPORAN HARIAN" in text
    assert "HEALTHY" in text
    assert "ACCUMULATE_70_30" in text
    assert "Rp 1,400,000" in text
    assert "BTC: Rp 1,000,000 (71.4%)" in text


def test_telegram_reporter_weekly_format():
    reporter = TelegramReporter()
    text = reporter.format_weekly_report(
        nav_idr=1_500_000.0,
        weekly_pnl_pct=3.2,
        btc_benchmark_pnl_pct=2.1,
        ts=datetime(2026, 9, 21, 0, 0, tzinfo=WIB),
    )

    assert "KIBOT V3 — LAPORAN MINGGUAN" in text
    assert "Portofolio Return: +3.20%" in text
    assert "Benchmark (BTC-Only Buy & Hold): +2.10%" in text
    assert "Alpha vs BTC Benchmark: +1.10%" in text
    assert "70% BTC / 30% ETH" in text


def test_telegram_reporter_monthly_format():
    reporter = TelegramReporter()
    text = reporter.format_monthly_report(
        total_topup_idr=1_500_000.0,
        nav_idr=1_620_000.0,
        total_invested_idr=1_400_000.0,
        all_time_pnl_pct=8.0,
        topup_count=3,
        manual_events=["Manual withdrawal detected on app"],
        ts=datetime(2026, 10, 1, 8, 0, tzinfo=WIB),
    )

    assert "KIBOT V3 — AUDIT BULANAN" in text
    assert "Rp 1,500,000" in text
    assert "Rp 1,620,000" in text
    assert "+8.00%" in text


def test_send_message_without_token():
    import asyncio
    reporter = TelegramReporter()
    res = asyncio.run(reporter.send_message("test"))
    assert res is False
