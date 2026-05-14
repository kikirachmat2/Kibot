#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR

app = FastAPI(title="KiBot Sovereign Dashboard", version="2.0")

ROOT = Path(PROJECT_ROOT)
STATE = Path(STATE_DIR)
LOGS = ROOT / "Logs"
ASSETS = Path(__file__).resolve().parent / "dashboard_assets"
WIB = ZoneInfo("Asia/Jakarta")
POLYMARKET_STATE_URL = os.getenv("KIBOT_POLYMARKET_STATE_URL", "http://127.0.0.1:11600/api/state").strip()
USD_IDR_RATE = float(os.getenv("USD_IDR_RATE", "16000"))

SERVICE_NAMES = [
    "kibot-master",
    "kibot-scanner",
    "kibot-executor",
    "kibot-executor-polymarket",
    "kibot-ai-scout",
    "kibot-janitor",
    "kibot-dashboard",
    "ollama",
    "redis-server",
]

SERVICE_CACHE: Dict[str, Any] = {"ts": 0.0, "data": {}}
SERVICE_CACHE_TTL_SEC = 5.0

LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} [0-9:.,]+) \[(?P<level>[A-Z]+)\] (?P<actor>[^:]+): (?P<message>.*)$"
)
STARTUP_LINE_RE = re.compile(r"^\[(?P<channel>[A-Z0-9_]+)\]\[(?P<level>[A-Z]+)\] (?P<message>.*)$")

if ASSETS.is_dir():
    app.mount("/static", StaticFiles(directory=str(ASSETS)), name="static")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "None", "nan"):
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "None", "nan"):
            return default
        return int(float(value))
    except Exception:
        return default


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _load_lines(path: Path, limit: int = 50) -> List[str]:
    try:
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-limit:]
    except Exception:
        return []


def _latest_mtime(paths: Iterable[Path]) -> Optional[str]:
    mtimes: List[float] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            mtimes.append(path.stat().st_mtime)
        except Exception:
            continue
    if not mtimes:
        return None
    return datetime.fromtimestamp(max(mtimes), tz=WIB).isoformat()


def _format_idr(value: Any) -> str:
    amount = _safe_float(value, 0.0)
    return f"Rp {amount:,.0f}".replace(",", ".")


def _format_usdc(value: Any) -> str:
    amount = _safe_float(value, 0.0)
    return f"{amount:,.4f} USDC"


def _format_pct(value: Any, digits: int = 2) -> str:
    amount = _safe_float(value, 0.0)
    return f"{amount:+.{digits}f}%"


def _minutes_to_midnight_wib() -> int:
    now = datetime.now(WIB)
    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(0, int((next_midnight - now).total_seconds() // 60))


def _deadline_pressure(minutes: int) -> str:
    if minutes <= 45:
        return "IMMINENT"
    if minutes <= 180:
        return "HIGH"
    if minutes <= 360:
        return "MEDIUM"
    return "LOW"


def _status_tone(status: str) -> str:
    status = str(status or "").lower()
    if status in {"active", "running", "live", "ok", "online", "healthy"}:
        return "success"
    if status in {"thinking", "deliberating", "evaluating", "dealing"}:
        return "thinking"
    if status in {"warning", "warn", "degraded"}:
        return "warn"
    if status in {"error", "failed", "inactive", "stopped", "crashed"}:
        return "error"
    if status in {"paused", "idle", "standby"}:
        return "idle"
    return "idle"


def _service_statuses() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    cached = SERVICE_CACHE.get("data") or {}
    if now - float(SERVICE_CACHE.get("ts", 0.0) or 0.0) < SERVICE_CACHE_TTL_SEC and cached:
        return cached

    statuses: Dict[str, Dict[str, Any]] = {}
    for name in SERVICE_NAMES:
        status = "unknown"
        detail = ""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True,
                text=True,
                timeout=1.2,
                check=False,
            )
            status = (result.stdout or result.stderr or "unknown").strip() or "unknown"
        except FileNotFoundError:
            status = "unknown"
            detail = "systemctl_missing"
        except Exception as exc:
            status = "unknown"
            detail = f"error:{exc.__class__.__name__}"

        statuses[name] = {
            "name": name,
            "status": status,
            "tone": _status_tone(status),
            "detail": detail,
            "checked_at": datetime.now(WIB).isoformat(),
        }

    SERVICE_CACHE["ts"] = now
    SERVICE_CACHE["data"] = statuses
    return statuses


def _normalize_positions(raw: Any, limit: int = 6) -> List[Dict[str, Any]]:
    if isinstance(raw, dict):
        items = []
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("symbol", key)
                items.append(item)
            else:
                items.append({"symbol": key, "amount": value})
    elif isinstance(raw, list):
        items = [item for item in raw if isinstance(item, dict)]
    else:
        items = []

    normalized: List[Dict[str, Any]] = []
    for item in items[:limit]:
        symbol = str(item.get("symbol") or item.get("coin") or item.get("pair") or item.get("market_id") or "unknown")
        amount = item.get("amount")
        if amount is None:
            amount = item.get("size") or item.get("size_usdc") or item.get("balance")
        normalized.append({
            "symbol": symbol,
            "amount": amount,
            "entry": item.get("entry_price") or item.get("price") or item.get("entry"),
            "pnl_pct": item.get("pnl_pct") or item.get("return_pct") or item.get("profit_pct"),
            "status": item.get("status") or item.get("side") or "",
            "raw": item,
        })
    return normalized


def _normalize_council(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, list) and raw:
        raw = raw[-1] if isinstance(raw[-1], dict) else {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _extract_trade_count(raw_trades: Any) -> int:
    if isinstance(raw_trades, dict):
        return len(raw_trades)
    if isinstance(raw_trades, list):
        return len(raw_trades)
    return 0


def _load_polymarket_state_sync() -> Dict[str, Any]:
    try:
        import urllib.request

        with urllib.request.urlopen(POLYMARKET_STATE_URL, timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


async def _load_polymarket_state() -> Dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(POLYMARKET_STATE_URL)
            if response.status_code == 200:
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
    except Exception:
        pass
    return _load_polymarket_state_sync()


def _build_daily_state(portfolio: Dict[str, Any], strategy: Dict[str, Any]) -> Dict[str, Any]:
    candidate = {}
    for item in (portfolio.get("daily_state"), strategy.get("daily_state")):
        if isinstance(item, dict) and item:
            candidate = item
            break

    daily_pnl_idr = _safe_float(portfolio.get("daily_pnl_idr") or portfolio.get("pnl_idr") or 0.0)
    color = str(candidate.get("color") or "").upper()
    if color not in {"GREEN", "RECOVERY", "FLAT"}:
        if daily_pnl_idr > 0:
            color = "GREEN"
        elif daily_pnl_idr < 0:
            color = "RECOVERY"
        else:
            color = "FLAT"

    hold_winners = bool(candidate.get("hold_winners", color == "GREEN"))
    take_profit_multiplier = _safe_float(candidate.get("take_profit_multiplier"), 1.0 if color != "GREEN" else 1.75)
    reason = str(candidate.get("reason") or ("green_state" if color == "GREEN" else "recovery_state" if color == "RECOVERY" else "flat_state"))
    minutes = _minutes_to_midnight_wib()
    pressure = _deadline_pressure(minutes)
    return {
        "color": color,
        "hold_winners": hold_winners,
        "take_profit_multiplier": take_profit_multiplier,
        "reason": reason,
        "minutes_to_midnight": minutes,
        "deadline_pressure": pressure,
        "midnight_label": f"{minutes // 60:02d}h {minutes % 60:02d}m",
    }


def _build_portfolio_snapshot(telemetry: Dict[str, Any], strategy: Dict[str, Any], polymarket_live: Dict[str, Any]) -> Dict[str, Any]:
    tele_portfolio = telemetry.get("portfolio") if isinstance(telemetry, dict) else {}
    tele_portfolio = tele_portfolio if isinstance(tele_portfolio, dict) else {}

    indodax_equity_idr = _safe_float(tele_portfolio.get("equity_idr") or tele_portfolio.get("balance_idr") or 0.0)
    indodax_positions = _normalize_positions(tele_portfolio.get("active_positions") or tele_portfolio.get("positions") or [])
    telemetry_combined = _safe_float(tele_portfolio.get("combined_equity_idr") or 0.0)
    daily_pnl_idr = _safe_float(tele_portfolio.get("daily_pnl_idr") or tele_portfolio.get("pnl_idr") or 0.0)
    daily_pnl_pct = _safe_float(tele_portfolio.get("daily_pnl_pct") or tele_portfolio.get("return_pct") or 0.0)

    poly_state = polymarket_live if isinstance(polymarket_live, dict) else {}
    if not poly_state:
        poly_state = tele_portfolio.get("polymarket") if isinstance(tele_portfolio.get("polymarket"), dict) else {}

    usdc_balance = _safe_float(poly_state.get("usdc_balance") or 0.0)
    poly_equity_idr = _safe_float(poly_state.get("equity_idr") or (usdc_balance * USD_IDR_RATE))
    poly_daily_pnl_usd = _safe_float(poly_state.get("daily_pnl_usd") or 0.0)
    poly_daily_pnl_idr = _safe_float(poly_state.get("daily_pnl_idr") or (poly_daily_pnl_usd * USD_IDR_RATE))
    active_bets = _normalize_positions(poly_state.get("active_bets") or poly_state.get("active_positions") or poly_state.get("top_opportunities") or [])

    combined_equity_idr = telemetry_combined if telemetry_combined > 0 else (indodax_equity_idr + poly_equity_idr)
    if combined_equity_idr <= 0:
        combined_equity_idr = indodax_equity_idr + poly_equity_idr

    portfolio = {
        "indodax": {
            "cash_idr": indodax_equity_idr,
            "equity_idr": indodax_equity_idr,
            "pnl_idr": daily_pnl_idr,
            "pnl_pct": daily_pnl_pct,
            "active_positions": indodax_positions,
            "active_positions_count": len(indodax_positions),
        },
        "polymarket": {
            "wallet_ready": bool(poly_state.get("wallet_ready", False)),
            "wallet_address": poly_state.get("wallet_address"),
            "usdc_balance": usdc_balance,
            "equity_idr": poly_equity_idr,
            "pnl_idr": poly_daily_pnl_idr,
            "daily_pnl_usd": poly_daily_pnl_usd,
            "active_bets": active_bets,
            "active_bets_count": len(active_bets),
        },
        "combined_equity_idr": combined_equity_idr,
        "daily_pnl_idr": daily_pnl_idr,
        "daily_pnl_pct": daily_pnl_pct,
        "daily_state": _build_daily_state({"daily_state": tele_portfolio.get("daily_state"), "daily_pnl_idr": daily_pnl_idr, "pnl_idr": daily_pnl_idr}, strategy),
    }
    return portfolio


def _build_council_snapshot(
    council_raw: Dict[str, Any],
    brain_raw: Dict[str, Any],
    whatif_raw: Dict[str, Any],
    portfolio: Dict[str, Any],
) -> Dict[str, Any]:
    ai_critic = brain_raw.get("ai_critic") if isinstance(brain_raw, dict) else {}
    if not isinstance(ai_critic, dict):
        ai_critic = {}

    decision_state = str(
        council_raw.get("decision_state")
        or council_raw.get("decision")
        or council_raw.get("state")
        or ai_critic.get("verdict")
        or "WAIT"
    ).upper()
    confidence = max(
        _safe_float(council_raw.get("confidence"), 0.0),
        _safe_float(council_raw.get("decision_score"), 0.0),
        _safe_float(ai_critic.get("confidence"), 0.0),
    )
    enter_score = _safe_float(council_raw.get("enter_score"), 0.0)
    wait_score = _safe_float(council_raw.get("wait_score"), 0.0)
    exit_score = _safe_float(council_raw.get("exit_score"), 0.0)

    daily_state = portfolio.get("daily_state") if isinstance(portfolio.get("daily_state"), dict) else {}
    recovery_mode = bool(council_raw.get("recovery_mode", daily_state.get("color") == "RECOVERY"))
    green_hold_mode = bool(council_raw.get("green_hold_mode", daily_state.get("color") == "GREEN"))
    deadline_pressure = str(council_raw.get("deadline_pressure") or daily_state.get("deadline_pressure") or "LOW").upper()
    whatif_state = str(whatif_raw.get("state") or whatif_raw.get("verdict") or whatif_raw.get("result") or ai_critic.get("verdict") or "UNKNOWN").upper()
    whatif_confidence = _safe_float(whatif_raw.get("confidence"), 0.0)

    mandate = (
        council_raw.get("last_mandate")
        or council_raw.get("mandate")
        or council_raw.get("current_mandate")
        or ai_critic.get("logic")
        or ""
    )
    if not mandate:
        mandate = str(ai_critic.get("reason") or "Council in observation mode.")

    return {
        "decision_state": decision_state,
        "decision_score": round(max(confidence, enter_score, wait_score, exit_score), 4),
        "enter_score": round(enter_score, 4),
        "wait_score": round(wait_score, 4),
        "exit_score": round(exit_score, 4),
        "confidence": round(confidence, 4),
        "recovery_mode": recovery_mode,
        "green_hold_mode": green_hold_mode,
        "deadline_pressure": deadline_pressure,
        "whatif_state": whatif_state,
        "whatif_confidence": round(whatif_confidence, 4),
        "mandate": str(mandate),
        "reason": str(council_raw.get("reason") or ai_critic.get("reason") or ""),
        "antagonist": council_raw.get("antagonist") or {},
        "possibility_focus": council_raw.get("possibility_focus") or [],
    }


def _build_brain_snapshot(brain_raw: Dict[str, Any], world_model_raw: Dict[str, Any], ai_search_raw: Dict[str, Any]) -> Dict[str, Any]:
    market_pulse = brain_raw.get("market_pulse") if isinstance(brain_raw, dict) else {}
    if not isinstance(market_pulse, dict):
        market_pulse = {}
    intelligence = world_model_raw.get("intelligence") if isinstance(world_model_raw, dict) else {}
    if not isinstance(intelligence, dict):
        intelligence = {}

    headlines = list(market_pulse.get("top_headlines") or [])
    if not headlines and isinstance(ai_search_raw, dict):
        finnhub = ai_search_raw.get("finnhub:crypto") or {}
        data = finnhub.get("data") if isinstance(finnhub, dict) else []
        if isinstance(data, list):
            headlines = [str(item.get("headline") or item.get("summary") or "") for item in data[:5] if isinstance(item, dict)]

    return {
        "risk_bias": str(market_pulse.get("risk_bias") or "UNKNOWN"),
        "sentiment": str(intelligence.get("market_sentiment") or brain_raw.get("market_sentiment") or market_pulse.get("risk_bias") or "UNKNOWN"),
        "risk_level": str(intelligence.get("risk_level") or "UNKNOWN"),
        "suggested_posture": str(intelligence.get("suggested_posture") or "UNKNOWN"),
        "top_catalysts": list(intelligence.get("top_catalysts") or [])[:3],
        "headlines": headlines[:5],
        "ai_critic": brain_raw.get("ai_critic") if isinstance(brain_raw, dict) else {},
        "last_updated": brain_raw.get("updated_at") if isinstance(brain_raw, dict) else None,
    }


def _build_provider_health(provider_state: Dict[str, Any]) -> Dict[str, Any]:
    providers = provider_state.get("providers") if isinstance(provider_state, dict) else {}
    if not isinstance(providers, dict):
        providers = {}
    now = time.time()
    active = 0
    cooling = 0
    auth_failures = 0
    failing = 0
    details: List[Dict[str, Any]] = []

    for name, data in sorted(providers.items()):
        if not isinstance(data, dict):
            continue
        cooldown_until = _safe_float(data.get("cooldown_until"), 0.0)
        reason = str(data.get("last_failure_reason") or "")
        is_active = cooldown_until <= now
        if is_active:
            active += 1
        else:
            cooling += 1
        if "401" in reason or "auth" in reason.lower():
            auth_failures += 1
        if reason and reason not in {"ok", "success"}:
            failing += 1
        details.append(
            {
                "name": name,
                "status": "active" if is_active else "cooldown",
                "tone": "success" if is_active else "warn",
                "cooldown_until": cooldown_until,
                "reason": reason,
                "last_success_at": data.get("last_success_at"),
                "last_failure_at": data.get("last_failure_at"),
            }
        )

    return {
        "active": active,
        "cooling": cooling,
        "auth_failures": auth_failures,
        "failing": failing,
        "details": details,
        "total": len(details),
    }


def _parse_log_event(line: str, source: str, index: int = 0) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None

    timestamp = datetime.now(WIB) - timedelta(seconds=index * 7)
    level = "INFO"
    actor = source
    message = line

    match = LOG_LINE_RE.match(line)
    if match:
        try:
            timestamp = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=WIB)
        except Exception:
            timestamp = datetime.now(WIB) - timedelta(seconds=index * 7)
        level = match.group("level")
        actor = match.group("actor")
        message = match.group("message")
    else:
        match = STARTUP_LINE_RE.match(line)
        if match:
            level = match.group("level")
            actor = match.group("channel")
            message = match.group("message")

    upper_message = message.upper()
    tone = "info"
    icon = "•"
    if level in {"ERROR", "CRITICAL"} or "FAILED" in upper_message or "OFFLINE" in upper_message:
        tone = "danger"
        icon = "⛔"
    elif level == "WARNING" or "WARN" in upper_message:
        tone = "warn"
        icon = "⚠️"
    elif "ACTIVE" in upper_message or "READY" in upper_message or "UPDATED" in upper_message or "SUCCESS" in upper_message:
        tone = "success"
        icon = "⚡"
    elif "LEARNING" in upper_message or "SCOUT" in upper_message or "WHAT-IF" in upper_message:
        tone = "info"
        icon = "🧠"
    elif "DELIBERAT" in upper_message or "COUNCIL" in upper_message:
        tone = "thinking"
        icon = "🏛️"
    elif "EXECUT" in upper_message or "ORDER" in upper_message or "BUY" in upper_message or "SELL" in upper_message:
        tone = "success"
        icon = "⚡"

    short_actor = str(actor).split(":")[0].strip()
    return {
        "timestamp": timestamp.isoformat(),
        "tone": tone,
        "icon": icon,
        "title": short_actor,
        "detail": message[:220],
        "source": source,
        "level": level,
    }


def _build_event_trail(snapshot: Dict[str, Any], limit: int = 24) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    now = datetime.now(WIB)
    portfolio = snapshot.get("portfolio", {})
    daily_state = portfolio.get("daily_state", {}) if isinstance(portfolio, dict) else {}
    services = snapshot.get("services", {}) if isinstance(snapshot.get("services"), dict) else {}
    council = snapshot.get("council", {}) if isinstance(snapshot.get("council"), dict) else {}
    brain = snapshot.get("brain", {}) if isinstance(snapshot.get("brain"), dict) else {}
    telemetry = snapshot.get("telemetry", {}) if isinstance(snapshot.get("telemetry"), dict) else {}
    system_stats = telemetry.get("system_stats", {}) if isinstance(telemetry.get("system_stats"), dict) else {}
    batam_stats = system_stats.get("BATAM_MASTER", {}) if isinstance(system_stats.get("BATAM_MASTER"), dict) else {}
    stats = telemetry.get("stats", {}) if isinstance(telemetry.get("stats"), dict) else {}

    events.extend(
        [
            {
                "timestamp": (now - timedelta(seconds=2)).isoformat(),
                "tone": "success" if daily_state.get("color") == "GREEN" else "warn" if daily_state.get("color") == "RECOVERY" else "info",
                "icon": "💼",
                "title": "Portfolio",
                "detail": f"Combined equity {_format_idr(portfolio.get('combined_equity_idr'))} | Daily PnL {_format_idr(portfolio.get('daily_pnl_idr'))} | State {daily_state.get('color', 'FLAT')}",
                "source": "summary",
                "level": "INFO",
            },
            {
                "timestamp": (now - timedelta(seconds=6)).isoformat(),
                "tone": "thinking" if council.get("decision_state") not in {"WAIT", "UNKNOWN", "NONE"} else "info",
                "icon": "🏛️",
                "title": "Council",
                "detail": f"Decision {council.get('decision_state', 'WAIT')} | conf {_safe_float(council.get('confidence'), 0.0):.2f} | deadline {council.get('deadline_pressure', 'LOW')}",
                "source": "summary",
                "level": "INFO",
            },
            {
                "timestamp": (now - timedelta(seconds=10)).isoformat(),
                "tone": "info",
                "icon": "🧠",
                "title": "Brain",
                "detail": f"Sentiment {brain.get('sentiment', 'UNKNOWN')} | risk {brain.get('risk_level', 'UNKNOWN')} | posture {brain.get('suggested_posture', 'UNKNOWN')}",
                "source": "summary",
                "level": "INFO",
            },
            {
                "timestamp": (now - timedelta(seconds=14)).isoformat(),
                "tone": "warn" if _safe_float(batam_stats.get("disk"), 0.0) >= 90 else "info",
                "icon": "🧹",
                "title": "Janitor",
                "detail": f"CPU {_safe_float(batam_stats.get('cpu'), 0.0):.1f}% | RAM {_safe_float(batam_stats.get('ram'), 0.0):.1f}% | Disk {_safe_float(batam_stats.get('disk'), 0.0):.1f}%",
                "source": "summary",
                "level": "INFO",
            },
            {
                "timestamp": (now - timedelta(seconds=18)).isoformat(),
                "tone": "success",
                "icon": "📈",
                "title": "Scanner",
                "detail": f"Signals {stats.get('total', 0)} | approved {stats.get('approved', 0)} | vetoed {stats.get('vetoed', 0)}",
                "source": "summary",
                "level": "INFO",
            },
        ]
    )

    if services:
        service_bits = []
        for name in ("kibot-master", "kibot-scanner", "kibot-executor", "kibot-executor-polymarket", "kibot-ai-scout", "kibot-janitor", "ollama", "redis-server"):
            info = services.get(name, {})
            if isinstance(info, dict):
                service_bits.append(f"{name}:{info.get('status', 'unknown')}")
        events.append(
            {
                "timestamp": (now - timedelta(seconds=22)).isoformat(),
                "tone": "success",
                "icon": "🛰️",
                "title": "Services",
                "detail": " | ".join(service_bits),
                "source": "summary",
                "level": "INFO",
            }
        )

    log_sources = [
        ("kibot_sovereign", LOGS / "kibot_sovereign.log", 20),
        ("startup", LOGS / "startup.log", 12),
    ]
    for source, path, limit in log_sources:
        lines = _load_lines(path, limit)
        for index, line in enumerate(reversed(lines)):
            event = _parse_log_event(line, source, index=index)
            if event:
                events.append(event)

    events.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    return events[:limit]


def _build_canvas(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    portfolio = snapshot.get("portfolio", {})
    telemetry = snapshot.get("telemetry", {})
    services = snapshot.get("services", {})
    council = snapshot.get("council", {})
    brain = snapshot.get("brain", {})
    provider_health = snapshot.get("provider_health", {})
    active_trades = snapshot.get("active_trades", [])
    world_model = snapshot.get("world_model", {})

    stats = telemetry.get("stats", {}) if isinstance(telemetry.get("stats"), dict) else {}
    system_stats = telemetry.get("system_stats", {}) if isinstance(telemetry.get("system_stats"), dict) else {}
    batam_stats = system_stats.get("BATAM_MASTER", {}) if isinstance(system_stats.get("BATAM_MASTER"), dict) else {}
    polarity = str(portfolio.get("daily_state", {}).get("color") or "FLAT").upper()
    daily_state = portfolio.get("daily_state", {})
    active_positions = portfolio.get("indodax", {}).get("active_positions", [])
    active_bets = portfolio.get("polymarket", {}).get("active_bets", [])
    council_decision = str(council.get("decision_state") or council.get("decision") or "WAIT").upper()
    confidence = _safe_float(council.get("confidence"), 0.0)

    def node_status(service_name: str, fallback: str = "idle") -> str:
        service = services.get(service_name, {})
        if isinstance(service, dict):
            raw = str(service.get("status") or fallback).lower()
        else:
            raw = fallback
        return raw

    nodes = [
        {
            "id": "scanner",
            "label": "SCANNER",
            "icon": "🌐",
            "status": node_status("kibot-scanner", "active"),
            "accent": "cyan",
            "x": 52,
            "y": 56,
            "w": 260,
            "h": 142,
            "badge": "DISCOVERY",
            "headline": f"{stats.get('total', 0)} signals",
            "metrics": [
                {"label": "Approved", "value": stats.get("approved", 0)},
                {"label": "Vetoed", "value": stats.get("vetoed", 0)},
                {"label": "Math skip", "value": stats.get("math_skipped", 0)},
            ],
            "note": "Indodax + Polymarket discovery, continuation, reclaim, pivot.",
        },
        {
            "id": "council",
            "label": "COUNCIL",
            "icon": "🏛️",
            "status": "thinking" if council_decision not in {"WAIT", "IDLE", "UNKNOWN"} else "active",
            "accent": "blue",
            "x": 352,
            "y": 94,
            "w": 282,
            "h": 178,
            "badge": council_decision,
            "headline": f"conf {confidence:.2f}",
            "metrics": [
                {"label": "Enter", "value": _safe_float(council.get("enter_score"), 0.0)},
                {"label": "Wait", "value": _safe_float(council.get("wait_score"), 0.0)},
                {"label": "Exit", "value": _safe_float(council.get("exit_score"), 0.0)},
            ],
            "note": f"{council.get('mandate') or council.get('reason') or 'Deliberating with what-if + antagonist + deadline.'}",
        },
        {
            "id": "indodax",
            "label": "INDODAX EXECUTOR",
            "icon": "⚡",
            "status": node_status("kibot-executor", "active"),
            "accent": "orange",
            "x": 684,
            "y": 44,
            "w": 250,
            "h": 148,
            "badge": "LIVE",
            "headline": _format_idr(portfolio.get("indodax", {}).get("cash_idr")),
            "metrics": [
                {"label": "Positions", "value": len(active_positions)},
                {"label": "Slots", "value": f"{len(active_positions)}/{_safe_int((snapshot.get('strategy', {}) or {}).get('indodax', {}).get('max_slots', 0), 0) or '∞'}"},
                {"label": "Daily", "value": _format_pct(portfolio.get("indodax", {}).get("pnl_pct"), 2)},
            ],
            "note": f"Cash-aware, fee-aware, spread-aware. Active {len(active_positions)} positions.",
        },
        {
            "id": "polymarket",
            "label": "POLYMARKET EXECUTOR",
            "icon": "🔮",
            "status": node_status("kibot-executor-polymarket", "active"),
            "accent": "purple",
            "x": 684,
            "y": 230,
            "w": 250,
            "h": 148,
            "badge": "LIVE",
            "headline": _format_usdc(portfolio.get("polymarket", {}).get("usdc_balance")),
            "metrics": [
                {"label": "IDR eq", "value": _format_idr(portfolio.get("polymarket", {}).get("equity_idr"))},
                {"label": "Bets", "value": len(active_bets)},
                {"label": "Daily", "value": _format_pct(portfolio.get("polymarket", {}).get("pnl_idr") / USD_IDR_RATE if USD_IDR_RATE else 0.0, 2)},
            ],
            "note": f"Phantom wallet / Polygon CLOB. Active bets {len(active_bets)}.",
        },
        {
            "id": "verifier",
            "label": "VERIFIER",
            "icon": "✅",
            "status": "active",
            "accent": "green",
            "x": 978,
            "y": 102,
            "w": 244,
            "h": 176,
            "badge": "VERIFY",
            "headline": _format_idr(portfolio.get("daily_pnl_idr")),
            "metrics": [
                {"label": "Return", "value": _format_pct(portfolio.get("daily_pnl_pct"), 2)},
                {"label": "Trades", "value": _extract_trade_count(active_trades)},
                {"label": "State", "value": polarity},
            ],
            "note": "Tracks fills, recovery, daily PnL, and midnight report readiness.",
        },
        {
            "id": "janitor",
            "label": "JANITOR",
            "icon": "🧹",
            "status": node_status("kibot-janitor", "active"),
            "accent": "amber",
            "x": 978,
            "y": 320,
            "w": 244,
            "h": 168,
            "badge": "MAINTAIN",
            "headline": f"Disk {_safe_float(batam_stats.get('disk'), 0.0):.1f}%",
            "metrics": [
                {"label": "CPU", "value": f"{_safe_float(batam_stats.get('cpu'), 0.0):.1f}%"},
                {"label": "RAM", "value": f"{_safe_float(batam_stats.get('ram'), 0.0):.1f}%"},
                {"label": "Ollama", "value": node_status("ollama", "active")},
            ],
            "note": f"Self-healing maintenance loop. Redis {node_status('redis-server', 'unknown')}.",
        },
        {
            "id": "brain",
            "label": "OLLAMA BRAIN",
            "icon": "🧠",
            "status": node_status("ollama", "active"),
            "accent": "cyan",
            "x": 352,
            "y": 332,
            "w": 282,
            "h": 160,
            "badge": "SCOUT",
            "headline": str(brain.get("sentiment") or brain.get("risk_bias") or "UNKNOWN"),
            "metrics": [
                {"label": "Risk", "value": str(brain.get("risk_level") or "UNKNOWN")},
                {"label": "Posture", "value": str(brain.get("suggested_posture") or "UNKNOWN")},
                {"label": "Catalyst", "value": str((brain.get("top_catalysts") or ["—"])[0])[:34]},
            ],
            "note": "World model, headlines, and catalyst memory feed the council.",
        },
    ]

    positions = {node["id"]: node for node in nodes}

    def edge_path(source: str, target: str) -> str:
        src = positions[source]
        dst = positions[target]
        x1 = src["x"] + src["w"]
        y1 = src["y"] + src["h"] / 2.0
        x2 = dst["x"]
        y2 = dst["y"] + dst["h"] / 2.0
        horizontal = max(120.0, abs(x2 - x1) * 0.48)
        if x2 < x1:
            x1 = src["x"]
            x2 = dst["x"] + dst["w"]
            horizontal = max(120.0, abs(x2 - x1) * 0.48)
            return f"M {x1:.1f} {y1:.1f} C {x1 - horizontal:.1f} {y1:.1f}, {x2 + horizontal:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"
        return f"M {x1:.1f} {y1:.1f} C {x1 + horizontal:.1f} {y1:.1f}, {x2 - horizontal:.1f} {y2:.1f}, {x2:.1f} {y2:.1f}"

    edges = [
        {
            "id": "scanner-council",
            "from": "scanner",
            "to": "council",
            "label": f"{stats.get('total', 0)} signals",
            "tone": "active" if stats.get("total", 0) else "idle",
            "path": edge_path("scanner", "council"),
        },
        {
            "id": "brain-council",
            "from": "brain",
            "to": "council",
            "label": str(brain.get("suggested_posture") or "POSTURE"),
            "tone": "thinking",
            "path": edge_path("brain", "council"),
        },
        {
            "id": "council-indo",
            "from": "council",
            "to": "indodax",
            "label": str(council.get("decision_state") or "WAIT"),
            "tone": "active" if council_decision in {"ENTER", "BUY", "APPROVE", "EXECUTING"} else "idle",
            "path": edge_path("council", "indodax"),
        },
        {
            "id": "council-poly",
            "from": "council",
            "to": "polymarket",
            "label": str(council.get("decision_state") or "WAIT"),
            "tone": "active" if council_decision in {"ENTER", "BUY", "APPROVE", "EXECUTING"} else "idle",
            "path": edge_path("council", "polymarket"),
        },
        {
            "id": "indo-verifier",
            "from": "indodax",
            "to": "verifier",
            "label": f"{len(active_positions)} live",
            "tone": "success" if active_positions else "idle",
            "path": edge_path("indodax", "verifier"),
        },
        {
            "id": "poly-verifier",
            "from": "polymarket",
            "to": "verifier",
            "label": f"{len(active_bets)} bets",
            "tone": "success" if active_bets else "idle",
            "path": edge_path("polymarket", "verifier"),
        },
        {
            "id": "verifier-council",
            "from": "verifier",
            "to": "council",
            "label": "learning loop",
            "tone": "thinking",
            "path": edge_path("verifier", "council"),
        },
        {
            "id": "janitor-scanner",
            "from": "janitor",
            "to": "scanner",
            "label": "health",
            "tone": "active",
            "path": edge_path("janitor", "scanner"),
        },
        {
            "id": "janitor-brain",
            "from": "janitor",
            "to": "brain",
            "label": "cleanup",
            "tone": "active",
            "path": edge_path("janitor", "brain"),
        },
    ]

    return {
        "layout": {"width": 1280, "height": 560},
        "nodes": nodes,
        "edges": edges,
        "status": {
            "daily_state": daily_state,
            "decision_state": council_decision,
            "confidence": confidence,
        },
    }


def _build_system_snapshot() -> Dict[str, Any]:
    telemetry = _read_json(STATE / "telemetry_snapshot.json", {})
    runtime = _read_json(STATE / "runtime_note.json", {})
    strategy = _read_json(STATE / "active_strategy.json", {})
    whatif = _read_json(STATE / "whatif_results.json", {})
    council = _read_json(STATE / "council_directives.json", {})
    active_trades_raw = _read_json(STATE / "active_trades.json", {})
    provider_state = _read_json(STATE / "ai_coordinator_providers.json", {})
    brain = _read_json(STATE / "brain_status.json", {})
    world_model = _read_json(STATE / "world_model.json", {})
    learning_state = _read_json(STATE / "learning_state.json", {})
    ai_search = _read_json(STATE / "ai_search_cache.json", {})

    polymarket_live = _load_polymarket_state_sync()
    services = _service_statuses()
    portfolio = _build_portfolio_snapshot(telemetry if isinstance(telemetry, dict) else {}, strategy if isinstance(strategy, dict) else {}, polymarket_live)
    council_snapshot = _build_council_snapshot(
        _normalize_council(council),
        brain if isinstance(brain, dict) else {},
        whatif if isinstance(whatif, dict) else {},
        portfolio,
    )
    brain_snapshot = _build_brain_snapshot(
        brain if isinstance(brain, dict) else {},
        world_model if isinstance(world_model, dict) else {},
        ai_search if isinstance(ai_search, dict) else {},
    )
    provider_health = _build_provider_health(provider_state if isinstance(provider_state, dict) else {})
    active_trades = _normalize_positions(active_trades_raw if isinstance(active_trades_raw, (dict, list)) else [], limit=12)

    snapshot = {
        "generated_at": datetime.now(WIB).isoformat(),
        "timezone": "Asia/Jakarta",
        "telemetry": telemetry if isinstance(telemetry, dict) else {},
        "runtime": runtime if isinstance(runtime, dict) else {},
        "strategy": strategy if isinstance(strategy, dict) else {},
        "whatif": whatif if isinstance(whatif, dict) else {},
        "council": council_snapshot,
        "brain": brain_snapshot,
        "world_model": world_model if isinstance(world_model, dict) else {},
        "learning_state": learning_state if isinstance(learning_state, dict) else {},
        "ai_search": ai_search if isinstance(ai_search, dict) else {},
        "active_trades": active_trades,
        "provider_state": provider_state if isinstance(provider_state, dict) else {},
        "provider_health": provider_health,
        "portfolio": portfolio,
        "services": services,
        "snapshots": {
            "runtime_note": _latest_mtime([STATE / "runtime_note.json"]),
            "telemetry_snapshot": _latest_mtime([STATE / "telemetry_snapshot.json"]),
            "whatif_results": _latest_mtime([STATE / "whatif_results.json"]),
            "active_strategy": _latest_mtime([STATE / "active_strategy.json"]),
            "world_model": _latest_mtime([STATE / "world_model.json"]),
        },
    }
    snapshot["events"] = _build_event_trail(snapshot)
    snapshot["canvas"] = _build_canvas(snapshot)
    snapshot["service_counts"] = {
        "active": sum(1 for item in services.values() if isinstance(item, dict) and item.get("status") == "active"),
        "total": len(services),
    }
    snapshot["market_clock"] = {
        "wib": datetime.now(WIB).strftime("%H:%M:%S WIB"),
        "minutes_to_midnight": portfolio["daily_state"]["minutes_to_midnight"],
        "pressure": portfolio["daily_state"]["deadline_pressure"],
        "label": portfolio["daily_state"]["midnight_label"],
    }
    snapshot["mesh"] = telemetry.get("mesh_nodes", {}) if isinstance(telemetry, dict) else {}
    snapshot["system_stats"] = telemetry.get("system_stats", {}) if isinstance(telemetry, dict) else {}
    snapshot["status_text"] = telemetry.get("status_text", {}) if isinstance(telemetry, dict) else {}
    snapshot["heartbeat"] = telemetry.get("heartbeat", "UNKNOWN") if isinstance(telemetry, dict) else "UNKNOWN"
    return snapshot


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    index = ASSETS / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>KiBot Sovereign Dashboard</h1><p>dashboard_assets/index.html missing.</p>")


@app.get("/api/summary")
async def summary() -> JSONResponse:
    return JSONResponse(_build_system_snapshot())


@app.get("/api/canvas")
async def canvas() -> JSONResponse:
    snapshot = _build_system_snapshot()
    return JSONResponse(snapshot["canvas"])


@app.get("/api/events")
async def events(limit: int = Query(default=24, ge=1, le=100)) -> JSONResponse:
    snapshot = _build_system_snapshot()
    events = snapshot.get("events", [])
    return JSONResponse({"events": events[:limit], "generated_at": snapshot["generated_at"]})


@app.get("/api/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "kibot-dashboard", "generated_at": datetime.now(WIB).isoformat()})


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        try:
            while True:
                snapshot = _build_system_snapshot()
                payload = {
                    "generated_at": snapshot["generated_at"],
                    "portfolio": snapshot["portfolio"],
                    "services": snapshot["services"],
                    "council": snapshot["council"],
                    "brain": snapshot["brain"],
                    "world_model": snapshot["world_model"],
                    "events": snapshot["events"][:12],
                    "canvas": snapshot["canvas"],
                    "market_clock": snapshot["market_clock"],
                    "provider_health": snapshot["provider_health"],
                    "snapshots": snapshot["snapshots"],
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/favicon.ico")
async def favicon() -> PlainTextResponse:
    return PlainTextResponse("", status_code=204)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("KIBOT_DASHBOARD_PORT", "8787"))
    uvicorn.run("Core.Intelligence.kibot_dashboard:app", host="0.0.0.0", port=port, reload=False, factory=False)
