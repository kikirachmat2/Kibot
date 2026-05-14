#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR

app = FastAPI(title="KiBot Sovereign Dashboard", version="3.0")

ROOT = Path(PROJECT_ROOT)
STATE = Path(STATE_DIR)
DASHBOARD_DIR = ROOT / "Core" / "Intelligence" / "dashboard"
LOGS = ROOT / "Logs"
WIB = ZoneInfo("Asia/Jakarta")
POLYMARKET_STATE_URL = os.getenv("KIBOT_POLYMARKET_STATE_URL", "http://127.0.0.1:11600/api/state").strip()
USD_IDR_RATE = float(os.getenv("USD_IDR_RATE", "16000") or 16000)

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
PRICE_CACHE: Dict[str, Any] = {}
PRICE_CACHE_TTL_SEC = 15.0

if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")


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


def _latest_mtime(path: Path) -> str:
    try:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=WIB).strftime("%H:%M:%S")
    except Exception:
        pass
    return "missing"


def _normalize_list(value: Any, limit: int = 8) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        items = []
        for key, payload in value.items():
            if str(key).lower() == "idr":
                continue
            if isinstance(payload, dict):
                item = dict(payload)
                item.setdefault("coin", key)
                item.setdefault("symbol", key)
                items.append(item)
            else:
                items.append({"coin": key, "amount": payload})
        return items[:limit]
    if isinstance(value, list):
        return [
            item
            for item in value
            if isinstance(item, dict)
            and str(item.get("coin") or item.get("symbol") or item.get("asset") or "").lower() != "idr"
        ][:limit]
    return []


def _ticker_price_idr_sync(coin: str) -> float:
    coin = str(coin or "").lower().strip()
    if not coin or coin == "idr":
        return 0.0
    now = time.time()
    cached = PRICE_CACHE.get(coin)
    if cached and now - float(cached.get("ts", 0.0)) < PRICE_CACHE_TTL_SEC:
        return _safe_float(cached.get("price"), 0.0)

    try:
        response = httpx.get(f"https://indodax.com/api/{coin}_idr/ticker", timeout=2.2)
        payload = response.json() if response.status_code == 200 else {}
        price = _safe_float((payload.get("ticker") or {}).get("last"), 0.0)
        PRICE_CACHE[coin] = {"ts": now, "price": price}
        return price
    except Exception:
        PRICE_CACHE[coin] = {"ts": now, "price": 0.0}
        return 0.0


def _service_statuses(telemetry: Dict[str, Any]) -> Dict[str, str]:
    now = time.time()
    cached = SERVICE_CACHE.get("data") or {}
    if now - float(SERVICE_CACHE.get("ts", 0.0) or 0.0) < SERVICE_CACHE_TTL_SEC and cached:
        return cached

    statuses: Dict[str, str] = {}
    telemetry_services = telemetry.get("services", {}) if isinstance(telemetry, dict) else {}
    for name in SERVICE_NAMES:
        status = "unknown"
        if isinstance(telemetry_services, dict) and telemetry_services.get(name):
            raw = telemetry_services.get(name)
            status = str(raw.get("status") if isinstance(raw, dict) else raw)
        try:
            result = subprocess.run(
                ["systemctl", "is-active", name],
                capture_output=True,
                text=True,
                timeout=1.2,
                check=False,
            )
            systemd_status = (result.stdout or result.stderr or "").strip()
            if systemd_status:
                status = systemd_status
        except Exception:
            pass
        statuses[name] = status or "unknown"

    SERVICE_CACHE["ts"] = now
    SERVICE_CACHE["data"] = statuses
    return statuses


def _load_polymarket_state() -> Dict[str, Any]:
    try:
        import urllib.request

        with urllib.request.urlopen(POLYMARKET_STATE_URL, timeout=2.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _build_portfolio(telemetry: Dict[str, Any]) -> Dict[str, Any]:
    portfolio = telemetry.get("portfolio") if isinstance(telemetry, dict) else {}
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    polymarket_live = _load_polymarket_state()
    polymarket = portfolio.get("polymarket") if isinstance(portfolio.get("polymarket"), dict) else {}
    if polymarket_live:
        polymarket = {**polymarket, **polymarket_live}

    active_positions = _normalize_list(portfolio.get("active_positions") or portfolio.get("positions") or [], limit=10)
    indodax_equity = _safe_float(portfolio.get("equity_idr"), 0.0)
    idr_cash = _safe_float(portfolio.get("idr_cash"), indodax_equity)
    coin_holdings = _safe_float(portfolio.get("coin_holdings_idr"), 0.0)
    if coin_holdings <= 0:
        estimated_positions = []
        for item in active_positions:
            position = dict(item)
            value_idr = _safe_float(position.get("value_idr"), 0.0)
            price_idr = _safe_float(position.get("price_idr"), 0.0)
            amount = _safe_float(position.get("amount"), 0.0)
            coin = str(position.get("coin") or position.get("symbol") or "").lower()
            if value_idr <= 0 and amount > 0 and coin:
                price_idr = price_idr or _ticker_price_idr_sync(coin)
                value_idr = amount * price_idr
                position["price_idr"] = price_idr
                position["value_idr"] = round(value_idr, 0)
            estimated_positions.append(position)
        active_positions = estimated_positions
        coin_holdings = sum(_safe_float(item.get("value_idr"), 0.0) for item in active_positions)
    if "idr_cash" not in portfolio and coin_holdings > 0:
        indodax_equity = idr_cash + coin_holdings
    if indodax_equity <= 0:
        indodax_equity = idr_cash + coin_holdings

    usdc_balance = _safe_float(polymarket.get("usdc_balance"), 0.0)
    poly_equity_idr = _safe_float(polymarket.get("equity_idr"), usdc_balance * USD_IDR_RATE)
    poly_daily_pnl_usd = _safe_float(polymarket.get("daily_pnl_usd"), 0.0)
    poly_daily_pnl_idr = _safe_float(polymarket.get("daily_pnl_idr"), poly_daily_pnl_usd * USD_IDR_RATE)

    # Recompute combined equity from live components. The telemetry field can lag
    # behind `equity_idr` when held coins are repriced, so do not let stale cash
    # overwrite the real portfolio total shown in the control plane.
    combined_equity = indodax_equity + poly_equity_idr

    daily_pnl = _safe_float(portfolio.get("daily_pnl_idr"), 0.0) + poly_daily_pnl_idr
    daily_state = portfolio.get("daily_state") if isinstance(portfolio.get("daily_state"), dict) else {}
    daily_color = str(daily_state.get("color") or "").upper()
    if daily_color not in {"GREEN", "RECOVERY", "FLAT"}:
        daily_color = "GREEN" if daily_pnl > 0 else "RECOVERY" if daily_pnl < 0 else "FLAT"
    daily_state = {
        **daily_state,
        "color": daily_color,
        "reason": daily_state.get("reason") or ("green_state" if daily_color == "GREEN" else "recovery_state" if daily_color == "RECOVERY" else "flat_state"),
    }

    return {
        "equity_idr": indodax_equity,
        "idr_cash": idr_cash,
        "coin_holdings_idr": coin_holdings,
        "combined_equity_idr": combined_equity,
        "daily_pnl_idr": daily_pnl,
        "daily_color": daily_color,
        "daily_state": daily_state,
        "active_positions": active_positions,
        "polymarket": {
            "usdc_balance": usdc_balance,
            "equity_idr": poly_equity_idr,
            "daily_pnl_idr": poly_daily_pnl_idr,
            "daily_pnl_usd": poly_daily_pnl_usd,
            "active_bets": _normalize_list(polymarket.get("active_bets") or polymarket.get("active_positions") or [], limit=5),
            "wallet_ready": bool(polymarket.get("wallet_ready")),
        },
    }


def _normalize_council(council: Any) -> Dict[str, Any]:
    if isinstance(council, list) and council:
        council = council[-1]
    return council if isinstance(council, dict) else {}


def _build_events(summary: Dict[str, Any], limit: int = 30) -> List[Dict[str, str]]:
    now = datetime.now(WIB)
    portfolio = summary.get("portfolio", {})
    council = summary.get("council", {})
    world_model = summary.get("world_model", {})
    system = summary.get("system", {})
    services = summary.get("services", {})
    base_events = [
        ("Portfolio", f"Combined {portfolio.get('combined_equity_idr', 0):,.0f} IDR | cash {portfolio.get('idr_cash', 0):,.0f} | koin {portfolio.get('coin_holdings_idr', 0):,.0f}", "INFO"),
        ("Council", f"{council.get('decision_state', 'WAIT')} {council.get('ticker', '')} | conf {council.get('confidence', 0):.2f}", "INFO"),
        ("Market", f"{world_model.get('market_regime', 'NEUTRAL')} | risk {world_model.get('risk_level', 'LOW')}", "INFO"),
        ("Janitor", f"CPU {system.get('cpu', 0):.1f}% | RAM {system.get('ram', 0):.1f}% | Disk {system.get('disk', 0):.1f}%", "WARN" if _safe_float(system.get("disk"), 0) > 85 else "INFO"),
        ("Services", " | ".join(f"{name}:{status}" for name, status in services.items() if name in ("kibot-master", "kibot-scanner", "kibot-executor", "ollama")), "INFO"),
    ]
    events = []
    for index, (agent, message, tag) in enumerate(base_events):
        events.append({
            "time": (now.replace(microsecond=0)).isoformat(),
            "agent": agent,
            "message": message,
            "tag": tag,
            "offset": str(index),
        })

    for path in (LOGS / "kibot_sovereign.log", LOGS / "startup.log"):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-10:]
        except Exception:
            lines = []
        for line in reversed(lines):
            upper = line.upper()
            tag = "ERROR" if "ERROR" in upper or "FAILED" in upper else "WARN" if "WARN" in upper else "INFO"
            agent = "Log"
            if "SCANNER" in upper:
                agent = "Scanner"
            elif "COUNCIL" in upper:
                agent = "Council"
            elif "EXECUTOR" in upper:
                agent = "Executor"
            elif "JANITOR" in upper:
                agent = "Janitor"
            events.append({
                "time": now.replace(microsecond=0).isoformat(),
                "agent": agent,
                "message": line[-180:],
                "tag": tag,
            })
    return events[:limit]


def _build_summary() -> Dict[str, Any]:
    telemetry = _read_json(STATE / "telemetry_snapshot.json", {})
    strategy = _read_json(STATE / "active_strategy.json", {})
    whatif = _read_json(STATE / "whatif_results.json", {})
    council = _normalize_council(_read_json(STATE / "council_directives.json", {}))
    active_trades = _read_json(STATE / "active_trades.json", {})
    world_model = _read_json(STATE / "world_model.json", {})
    brain_state = _read_json(STATE / "brain_status.json", {})
    services = _service_statuses(telemetry if isinstance(telemetry, dict) else {})
    portfolio = _build_portfolio(telemetry if isinstance(telemetry, dict) else {})

    intelligence = world_model.get("intelligence") if isinstance(world_model, dict) else {}
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    ai_critic = brain_state.get("ai_critic") if isinstance(brain_state, dict) else {}
    ai_critic = ai_critic if isinstance(ai_critic, dict) else {}
    system_stats = telemetry.get("system_stats", {}) if isinstance(telemetry, dict) else {}
    sys_stats = system_stats.get("BATAM_MASTER", {}) if isinstance(system_stats, dict) else {}

    top_whatif = []
    for key in ("topOpportunities", "top_opportunities", "opportunities", "results"):
        value = whatif.get(key) if isinstance(whatif, dict) else None
        if isinstance(value, list):
            top_whatif = value[:3]
            break

    strategy_indodax = strategy.get("indodax") if isinstance(strategy, dict) and isinstance(strategy.get("indodax"), dict) else {}
    strategy_daily_state = strategy.get("daily_state") if isinstance(strategy, dict) and isinstance(strategy.get("daily_state"), dict) else {}

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_wib": datetime.now(WIB).isoformat(),
        "portfolio": portfolio,
        "strategy": {
            "global_mode": str(strategy.get("global_mode") or "UNKNOWN") if isinstance(strategy, dict) else "UNKNOWN",
            "indodax": strategy_indodax,
            "daily_state": strategy_daily_state,
        },
        "council": {
            "action": str(council.get("action") or council.get("decision") or "NONE"),
            "confidence": _safe_float(council.get("confidence") or council.get("decision_score"), 0.0),
            "decision_state": str(council.get("decision_state") or council.get("state") or "WAIT").upper(),
            "ticker": str(council.get("ticker") or council.get("pair") or ""),
            "enter_score": _safe_float(council.get("enter_score"), 0.0),
            "wait_score": _safe_float(council.get("wait_score"), 0.0),
            "exit_score": _safe_float(council.get("exit_score"), 0.0),
        },
        "services": services,
        "active_trades": active_trades,
        "world_model": {
            "market_regime": str(intelligence.get("market_sentiment") or "NEUTRAL"),
            "risk_level": str(intelligence.get("risk_level") or "LOW"),
            "last_updated": world_model.get("last_updated_str") or _latest_mtime(STATE / "world_model.json"),
        },
        "brain": {
            "status": str(brain_state.get("status") or ""),
            "risk": str(ai_critic.get("risk_bias") or brain_state.get("risk_bias") or "MIXED"),
            "posture": str(ai_critic.get("capital_posture") or intelligence.get("suggested_posture") or "NEUTRAL"),
        },
        "system": {
            "cpu": _safe_float(sys_stats.get("cpu"), 0.0),
            "ram": _safe_float(sys_stats.get("ram"), 0.0),
            "disk": _safe_float(sys_stats.get("disk"), 0.0),
        },
        "whatif": {
            "top": top_whatif,
            "count": _safe_int(whatif.get("pairsSimulated") or whatif.get("pairs_simulated"), 0) if isinstance(whatif, dict) else 0,
        },
        "snapshots": {
            "telemetry": _latest_mtime(STATE / "telemetry_snapshot.json"),
            "strategy": _latest_mtime(STATE / "active_strategy.json"),
            "whatif": _latest_mtime(STATE / "whatif_results.json"),
            "world_model": _latest_mtime(STATE / "world_model.json"),
        },
    }
    summary["events"] = _build_events(summary)
    return summary


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    html_path = DASHBOARD_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard assets not found.</h1>")


@app.get("/api/summary")
async def summary() -> JSONResponse:
    return JSONResponse(_build_summary())


@app.get("/api/events")
async def events(limit: int = Query(default=30, ge=1, le=100)) -> JSONResponse:
    snapshot = _build_summary()
    return JSONResponse({"events": snapshot.get("events", [])[:limit], "generated_at": snapshot["generated_at"]})


@app.get("/api/canvas")
async def canvas() -> JSONResponse:
    snapshot = _build_summary()
    return JSONResponse({
        "portfolio": snapshot["portfolio"],
        "council": snapshot["council"],
        "services": snapshot["services"],
        "system": snapshot["system"],
    })


@app.get("/api/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "kibot-dashboard", "version": "3.0", "generated_at": datetime.now(WIB).isoformat()})


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        while True:
            try:
                yield f"data: {json.dumps(_build_summary(), ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("KIBOT_DASHBOARD_PORT", "8787"))
    uvicorn.run("Core.Intelligence.kibot_dashboard:app", host="0.0.0.0", port=port, reload=False)
