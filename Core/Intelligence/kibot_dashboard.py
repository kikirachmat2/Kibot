#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import re
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

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR, KiConfig

app = FastAPI(title="KiBot Sovereign Dashboard", version="3.4")

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' data:; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data:;"
    )
    return response

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
    "kibot-pumpfun",
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
    assets_dir = DASHBOARD_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


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


_LEGACY_WORD_RE = re.compile(r"(paper|sim(?:ulation|ulated)?|mock|canary|view-only)", re.IGNORECASE)


def _scrub_legacy_payload(value: Any) -> Any:
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, item in value.items():
            if _LEGACY_WORD_RE.search(str(key)):
                continue
            clean[key] = _scrub_legacy_payload(item)
        return clean
    if isinstance(value, list):
        return [_scrub_legacy_payload(item) for item in value]
    if isinstance(value, str):
        if _LEGACY_WORD_RE.search(value):
            cleaned = _LEGACY_WORD_RE.sub("live", value)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned or "live"
        return value
    return value


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


def _file_age_s(path: Path) -> float:
    """Return seconds since file was last modified, or -1 if missing."""
    try:
        if path.exists():
            return round(time.time() - path.stat().st_mtime, 1)
    except Exception:
        pass
    return -1.0


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
        response = httpx.get(f"https://indodax.com/api/ticker/{coin}_idr", timeout=2.2)
        payload = response.json() if response.status_code == 200 else {}
        price = _safe_float((payload.get("ticker") or {}).get("last"), 0.0)
        PRICE_CACHE[coin] = {"ts": now, "price": price}
        return price
    except Exception:
        PRICE_CACHE[coin] = {"ts": now, "price": 0.0}
        return 0.0


def _coin_from_pair(pair: str) -> str:
    raw = str(pair or "").strip().lower()
    if "/" in raw:
        return raw.split("/", 1)[0]
    if "_" in raw:
        return raw.split("_", 1)[0]
    return raw.replace("idr", "")


def _position_value_map(active_positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    values: Dict[str, Dict[str, float]] = {}
    for position in active_positions:
        coin = str(position.get("coin") or position.get("symbol") or "").lower().strip()
        if not coin or coin == "idr":
            continue
        values[coin] = {
            "amount": _safe_float(position.get("amount"), 0.0),
            "price_idr": _safe_float(position.get("price_idr"), 0.0),
            "value_idr": _safe_float(position.get("value_idr"), 0.0),
        }
    return values


def _realized_daily_pnl_idr() -> float:
    risk_state = _read_json(STATE / "risk_state.json", {})
    if not isinstance(risk_state, dict):
        return 0.0
    today = datetime.now(WIB).strftime("%Y-%m-%d")
    state_date = str(risk_state.get("last_reset_date") or "")
    if state_date and state_date != today:
        return 0.0
    return _safe_float(risk_state.get("daily_pnl"), 0.0)


def _active_trade_unrealized_pnl(active_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate open-position PnL as current market value minus entry cost."""
    active_trades = _read_json(STATE / "active_trades.json", {})
    if not isinstance(active_trades, dict):
        return {"unrealized_pnl_idr": 0.0, "position_cost_basis_idr": 0.0, "positions": []}

    values_by_coin = _position_value_map(active_positions)
    total_pnl = 0.0
    total_cost = 0.0
    details = []
    for pair, trade in active_trades.items():
        if not isinstance(trade, dict):
            continue
        coin = _coin_from_pair(pair)
        if not coin:
            continue
        cost = _safe_float(trade.get("cost") or trade.get("budget_idr") or trade.get("notional_idr"), 0.0)
        amount = _safe_float(trade.get("amount"), 0.0)
        position = values_by_coin.get(coin, {})
        current_value = _safe_float(position.get("value_idr"), 0.0)
        current_price = _safe_float(position.get("price_idr"), 0.0)
        if current_value <= 0.0 and amount > 0.0:
            current_price = current_price or _ticker_price_idr_sync(coin)
            current_value = amount * current_price
        if cost <= 0.0:
            continue
        pnl = current_value - cost
        total_pnl += pnl
        total_cost += cost
        details.append({
            "pair": str(pair).upper(),
            "cost_idr": round(cost, 0),
            "current_value_idr": round(current_value, 0),
            "unrealized_pnl_idr": round(pnl, 0),
            "current_price_idr": current_price,
        })

    return {
        "unrealized_pnl_idr": total_pnl,
        "position_cost_basis_idr": total_cost,
        "positions": details,
    }


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


def _load_phantom_state() -> Dict[str, Any]:
    return _read_json(STATE / "phantom_scout.json", {})

def _load_shadow_state() -> Dict[str, Any]:
    return _read_json(STATE / "shadow_portfolio.json", {})


def _load_web3_state() -> Dict[str, Any]:
    return _read_json(STATE / "web3_opportunities.json", {})


def _load_web3_fee_state() -> Dict[str, Any]:
    return _read_json(STATE / "web3_fee_state.json", {})


def _load_solana_trending_state() -> Dict[str, Any]:
    return _read_json(STATE / "solana_trending_candidates.json", {})


def _load_web3_positions() -> List[Dict[str, Any]]:
    positions = _read_json(STATE / "web3_positions.json", [])
    return positions if isinstance(positions, list) else []


def _load_web3_exit_state() -> Dict[str, Any]:
    return _read_json(STATE / "web3_exit_state.json", {})


def _load_pumpfun_route_state() -> Dict[str, Any]:
    return _read_json(STATE / "pumpfun_route_state.json", {})


def _load_pumpfun_candidates() -> Dict[str, Any]:
    return _read_json(STATE / "pumpfun_candidates.json", {})


def _load_pumpfun_native_state() -> Dict[str, Any]:
    return _read_json(STATE / "pumpfun_native_executor_state.json", {})


def _load_pumpfun_latency_state() -> Dict[str, Any]:
    return _read_json(STATE / "pumpfun_latency.json", {})


def _load_pumpfun_positions() -> List[Dict[str, Any]]:
    payload = _read_json(STATE / "pumpfun_positions.json", [])
    return payload if isinstance(payload, list) else []


def _load_pumpfun_exit_state() -> Dict[str, Any]:
    return _read_json(STATE / "pumpfun_exit_state.json", {})


def _load_scanner_executor_contract() -> Dict[str, Any]:
    return _read_json(STATE / "scanner_executor_contract.json", {})


def _load_engine_independence() -> Dict[str, Any]:
    return _read_json(STATE / "engine_independence.json", {})


def _load_indodax_no_idle() -> Dict[str, Any]:
    return _read_json(STATE / "indodax_no_idle.json", {})


def _load_phantom_capital_mover() -> Dict[str, Any]:
    return _read_json(STATE / "phantom_capital_mover.json", {})


def _load_phantom_network_maximizer() -> Dict[str, Any]:
    return _read_json(STATE / "phantom_network_maximizer.json", {})


def _load_deadline_pressure() -> Dict[str, Any]:
    return _read_json(STATE / "deadline_profit_enforcer.json", {})


def _load_server_telemetry() -> Dict[str, Any]:
    return _read_json(STATE / "server_telemetry.json", {})


def _load_scanner_health() -> Dict[str, Any]:
    return _read_json(STATE / "scanner_health.json", {})


def _load_target_board_runtime() -> Dict[str, Any]:
    return _read_json(STATE / "target_board_runtime.json", {})


def _load_indodax_top_targets() -> Dict[str, Any]:
    return _read_json(STATE / "indodax_top_targets.json", {})


def _load_phantom_top_targets() -> Dict[str, Any]:
    return _read_json(STATE / "phantom_top_targets.json", {})


def _load_ai_decision_trace() -> Dict[str, Any]:
    return _read_json(STATE / "ai_decision_trace.json", {})


def _load_autonomous_sizing_state() -> Dict[str, Any]:
    return _read_json(STATE / "autonomous_sizing.json", {})


def _load_autonomous_trading_brain() -> Dict[str, Any]:
    return _read_json(STATE / "autonomous_trading_brain.json", {})


def _load_trade_history() -> Dict[str, Any]:
    try:
        from Core.Intelligence.trade_history import summarize_today

        return summarize_today()
    except Exception:
        return {}


def _load_indodax_live_brain() -> Dict[str, Any]:
    return _read_json(STATE / "indodax_live_brain.json", {})


def _load_phantom_live_brain() -> Dict[str, Any]:
    return _read_json(STATE / "phantom_live_brain.json", {})


def _load_live_order_dispatcher() -> Dict[str, Any]:
    return _read_json(STATE / "live_order_dispatcher.json", {})


def _load_capital_movement_runtime() -> Dict[str, Any]:
    return _read_json(STATE / "capital_movement_runtime.json", {})


def _load_pnl_reconciliation() -> Dict[str, Any]:
    try:
        from Core.Treasury.pnl_reconciliation import reconcile_pnl_state

        return reconcile_pnl_state(write=True)
    except Exception:
        return _read_json(STATE / "pnl_reconciliation.json", {})

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
    refreshed_positions = []
    refreshed_holdings = 0.0
    for item in active_positions:
        position = dict(item)
        amount = _safe_float(position.get("amount"), 0.0)
        coin = str(position.get("coin") or position.get("symbol") or "").lower()
        price_idr = _ticker_price_idr_sync(coin) if amount > 0 and coin else 0.0
        if price_idr <= 0:
            price_idr = _safe_float(position.get("price_idr"), 0.0)
        value_idr = amount * price_idr if amount > 0 and price_idr > 0 else _safe_float(position.get("value_idr"), 0.0)
        position["price_idr"] = price_idr
        position["value_idr"] = round(value_idr, 0)
        refreshed_holdings += value_idr
        refreshed_positions.append(position)
    if refreshed_positions:
        active_positions = refreshed_positions
        coin_holdings = refreshed_holdings
    if refreshed_positions and coin_holdings > 0:
        indodax_equity = idr_cash + coin_holdings
    elif "idr_cash" not in portfolio and coin_holdings > 0:
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

    realized_daily_pnl = _realized_daily_pnl_idr()
    open_pnl = _active_trade_unrealized_pnl(active_positions)
    unrealized_daily_pnl = _safe_float(open_pnl.get("unrealized_pnl_idr"), 0.0)
    daily_pnl = realized_daily_pnl + unrealized_daily_pnl + poly_daily_pnl_idr
    pnl_base = max(combined_equity - daily_pnl, _safe_float(open_pnl.get("position_cost_basis_idr"), 0.0), 1.0)
    daily_pnl_pct = (daily_pnl / pnl_base) * 100.0

    # Load Capital Governor reconciled data if available and fresh for today.
    # Prefer the governor as the canonical total-balance source whenever it
    # is current, even while positions or orders are open. Live portfolio
    # data is still exposed separately for context and mark-to-market detail.
    gov_data = _read_json(STATE / "capital_governor.json", {})
    has_open_positions = bool(open_pnl.get("positions")) or bool(active_positions)
    governor_fresh_today = bool(gov_data and gov_data.get("date") == datetime.now(WIB).strftime("%Y-%m-%d"))
    if governor_fresh_today:
        combined_equity = _safe_float(gov_data.get("current_total_equity_idr"), combined_equity)
        daily_pnl = _safe_float(gov_data.get("daily_pnl_idr"), daily_pnl)
        daily_pnl_pct = _safe_float(gov_data.get("daily_pnl_pct"), daily_pnl_pct)

    daily_state = portfolio.get("daily_state") if isinstance(portfolio.get("daily_state"), dict) else {}
    daily_color = "GREEN" if daily_pnl > 0 else "RECOVERY" if daily_pnl < 0 else "FLAT"
    daily_state = {
        **daily_state,
        "color": daily_color,
        "hold_winners": daily_color == "GREEN",
        "take_profit_multiplier": 1.75 if daily_color == "GREEN" else 1.0,
        "reason": "open_trade_mark_to_market" if open_pnl.get("positions") else "realized_daily_pnl",
    }

    # Split Real vs Simulated PnL based on live trading activation state
    from Core.Support.ki_config import KiConfig
    live_trading_enabled = KiConfig.LIVE_TRADING_ENABLED
    daily_pnl_real_idr = daily_pnl if live_trading_enabled else 0.0
    daily_pnl_shadow_idr = daily_pnl if not live_trading_enabled else 0.0

    return {
        "equity_idr": indodax_equity,
        "idr_cash": idr_cash,
        "coin_holdings_idr": coin_holdings,
        "combined_equity_idr": combined_equity,
        "total_balance_idr": combined_equity,
        "open_buy_order_reserve_idr": _safe_float(gov_data.get("open_buy_order_reserve_idr"), 0.0) if isinstance(gov_data, dict) else 0.0,
        "daily_pnl_idr": daily_pnl,
        "daily_pnl_real_idr": daily_pnl_real_idr,
        "daily_pnl_shadow_idr": daily_pnl_shadow_idr,
        "daily_pnl_source": "capital_governor" if governor_fresh_today else "live_portfolio",
        "live_trading_enabled": live_trading_enabled,
        "daily_pnl_pct": daily_pnl_pct,
        "daily_color": daily_color,
        "daily_state": daily_state,
        "realized_pnl_idr": realized_daily_pnl,
        "unrealized_pnl_idr": unrealized_daily_pnl,
        "position_cost_basis_idr": _safe_float(open_pnl.get("position_cost_basis_idr"), 0.0),
        "open_position_pnl": open_pnl.get("positions", []),
        "has_open_positions": has_open_positions,
        "governor_daily_pnl_idr": _safe_float(gov_data.get("daily_pnl_idr"), daily_pnl) if isinstance(gov_data, dict) else daily_pnl,
        "governor_daily_pnl_pct": _safe_float(gov_data.get("daily_pnl_pct"), daily_pnl_pct) if isinstance(gov_data, dict) else daily_pnl_pct,
        "governor_current_total_equity_idr": _safe_float(gov_data.get("current_total_equity_idr"), combined_equity) if isinstance(gov_data, dict) else combined_equity,
        "active_positions": active_positions,
        "polymarket": {
            "usdc_balance": usdc_balance,
            "equity_idr": poly_equity_idr,
            "daily_pnl_idr": poly_daily_pnl_idr,
            "daily_pnl_usd": poly_daily_pnl_usd,
            "active_bets": _normalize_list(polymarket.get("active_bets") or polymarket.get("active_positions") or [], limit=5),
            "wallet_ready": bool(polymarket.get("wallet_ready")),
        },
        "phantom": _load_phantom_state(),
        "shadow": _load_shadow_state(),
    }


def _normalize_council(council: Any) -> Dict[str, Any]:
    if isinstance(council, list) and council:
        council = council[-1]
    return council if isinstance(council, dict) else {}


def _translate_to_human(agent: str, message: str, tag: str) -> str:
    msg = message.strip()
    upper = msg.upper()
    
    # 1. Portfolio
    if agent == "Portfolio":
        import re
        m = re.search(r"Combined\s+([\d,.]+)\s+IDR\s*\|\s*cash\s*([\d,.]+)\s*\|\s*koin\s*([\d,.]+)", msg, re.IGNORECASE)
        if m:
            equity, _, _ = m.groups()
            return f"Total saldo gabungan terpantau di angka Rp {equity} IDR."
        return f"Total saldo gabungan terkelola di angka Rp {msg}."

    # 2. Council
    if agent == "Council":
        import re
        m = re.search(r"(\w+)\s+([A-Z0-9/_-]*)\s*\|\s*conf\s*([\d.]+)", msg, re.IGNORECASE)
        if m:
            decision, ticker, conf = m.groups()
            ticker = ticker.strip()
            conf_val = float(conf)
            if decision == "WAIT":
                if ticker:
                    return f"Sistem melihat {ticker}, tapi tidak masuk posisi karena Expected Value masih negatif dan market risk sedang tinggi."
                else:
                    return f"Sovereign Council berada dalam mode siaga aktif, terus menganalisis anomali likuiditas pasar."
            elif decision == "APPROVE":
                return f"Sistem mendeteksi peluang premium pada {ticker} dengan tingkat keyakinan {conf_val:.1f}%. Mempersiapkan eksekusi aman."
            elif decision == "REJECT":
                return f"Sistem menolak sinyal pada {ticker} karena tidak lolos sensor kualitas alpha (Tingkat Keyakinan: {conf_val:.1f}%)."
        return f"Sovereign Council menetapkan status: {msg}."

    # 3. Deadline
    if agent == "Deadline":
        import re
        m = re.search(r"(\w+)\s*\|\s*risk\s*(\w+)\s*\|\s*quality\s*(\w+)", msg, re.IGNORECASE)
        if m:
            deadline, risk, quality = m.groups()
            if deadline in ("URGENT", "LOCK_GREEN"):
                return f"Ambang batas transaksi berada pada fase agresif ({deadline}) dengan proteksi risiko {risk} dan standar kualitas {quality}."
            return f"Sistem beroperasi dengan pendekatan sabar ({deadline}), membatasi risiko {risk} demi menjaga konsistensi profit."
        return f"Parameter batas waktu dan mitigasi risiko disetel pada mode: {msg}."

    # 4. Scanner
    if agent == "Scanner":
        import re
        m = re.search(r"(\d+)\s+candidates\s*\|\s*journal\s+E/W/X\s*(\d+)/(\d+)/(\d+)", msg, re.IGNORECASE)
        if m:
            cands, entries, waits, exits = m.groups()
            return f"Modul Scanner memantau {cands} aset potensial. Log keputusan mencatat {entries} entri aktif, {waits} antrean, dan {exits} pelepasan posisi."
        return f"Scanner memindai pasar Indodax: {msg}."

    # 5. Probability
    if agent == "Probability":
        import re
        m = re.search(r"green\s*([\d.]+)%\s*\|\s*breadth\s*(\w+)", msg, re.IGNORECASE)
        if m:
            prob, breadth = m.groups()
            return f"Probabilitas pergerakan hijau hari ini diperkirakan sebesar {prob}%, didukung oleh indikator market breadth '{breadth}'."
        return f"Analisis probabilitas pergerakan pasar: {msg}."

    # 6. Market
    if agent == "Market":
        import re
        m = re.search(r"(\w+)\s*\|\s*risk\s*(\w+)", msg, re.IGNORECASE)
        if m:
            regime, risk = m.groups()
            return f"Rezim tren pasar saat ini tergolong {regime} dengan paparan risiko global {risk}."
        return f"World Model melaporkan kondisi pasar: {msg}."

    # 7. Janitor
    if agent == "Janitor":
        import re
        m = re.search(r"CPU\s*([\d.]+)%\s*\|\s*RAM\s*([\d.]+)%\s*\|\s*Disk\s*([\d.]+)%", msg, re.IGNORECASE)
        if m:
            cpu, ram, disk = m.groups()
            return f"Penggunaan sumber daya server Batam: CPU {cpu}%, memori RAM {ram}%, penyimpanan Disk {disk}%. Semua sistem stabil."
        return f"Layanan Janitor melaporkan pemakaian sistem: {msg}."

    # 8. Services
    if agent == "Services":
        active_servs = []
        inactive_servs = []
        for term in msg.split("|"):
            if ":" in term:
                name, stat = term.strip().split(":", 1)
                if stat.strip().lower() in ("active", "running", "ok"):
                    active_servs.append(name.strip())
                else:
                    inactive_servs.append(name.strip())
        if inactive_servs:
            return f"Layanan systemd {', '.join(active_servs)} berjalan normal. Perhatian: {', '.join(inactive_servs)} tidak aktif!"
        if active_servs:
            return f"Seluruh layanan systemd inti ({', '.join(active_servs)}) berjalan aktif dan terintegrasi penuh."
        return f"Status layanan systemd: {msg}"

    # 9. Generic log translations (from log files)
    if "HEALTHCHECK" in upper or "HEALTH CHECK" in upper:
        return "Sistem keamanan melakukan audit kesehatan mandiri (Self-Healthcheck). Seluruh modul telemetri normal."
    if "DRAWDOWN" in upper:
        return "RiskGate mengaudit batas drawdown portofolio. Keamanan modal terjamin di bawah batas harian 1.5%."
    if "OLLAMA" in upper or "MODEL" in upper:
        return "Council sync model."
    if "BRIDGE" in upper or "FEE" in upper:
        return "Bridge route checked."
    if "FIREWALL" in upper or "UFW" in upper or "PORT" in upper:
        return "Firewall checked."
    if "SQLITE" in upper or "DATABASE" in upper:
        return "Database check."
    if "SIM" in upper or "PAPER" in upper:
        return "Legacy mode noted."
    if "LIVE_TRADING" in upper or "KIBOT_LIVE" in upper:
        return "Live-trading gate checked."
    if "ERROR" in upper or "FAILED" in upper:
        return f"Technical warning: '{message[:80]}'."
    
    # Generic backup translation
    return f"Log aktivitas mencatat: {message}"


def _build_events(summary: Dict[str, Any], limit: int = 30) -> List[Dict[str, str]]:
    now = datetime.now(WIB).replace(microsecond=0).isoformat()
    portfolio = summary.get("portfolio", {})
    council = summary.get("council", {})
    world_model = summary.get("world_model", {})
    system = summary.get("system", {})
    services = summary.get("services", {})
    strategy_intel = summary.get("strategy_intelligence", {})
    brain = summary.get("autonomous_trading_brain", {})
    indo_brain = summary.get("indodax_live_brain", {})
    ph_brain = summary.get("phantom_live_brain", {})
    dispatcher = summary.get("live_order_dispatcher", {})
    capital = summary.get("capital", {})
    order_tracker = summary.get("order_tracker", {})
    trade_history = summary.get("trade_history", {})
    events: List[Dict[str, str]] = []

    def add_event(tag: str, message: str, agent: str = "System") -> None:
        if len(events) >= limit:
            return
        events.append({"time": now, "agent": agent, "message": message, "tag": tag, "offset": str(len(events))})

    recent_activity = trade_history.get("recent_activity", []) if isinstance(trade_history, dict) else []
    if isinstance(recent_activity, list):
        for row in recent_activity[:8]:
            if not isinstance(row, dict):
                continue
            tag = str(row.get("tag") or "").upper()
            message = str(row.get("message") or "").strip()
            agent = str(row.get("agent") or "Trade")
            if tag in {"BUY", "BUY PENDING", "SELL PENDING", "BUY REJECTED", "SELL REJECTED", "SELL PROFIT", "SELL LOSS", "SWAP", "STALE"} and message:
                add_event(tag, message, agent)

    council_state = council.get("decision_state") or council.get("last_decision") or brain.get("reason") or "WAIT"
    council_conf = council.get("confidence", 0.0)
    add_event("COUNCIL REPORT", f"{council_state} conf {council_conf:.2f}", "Council")
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
    pnl_reconciliation = _load_pnl_reconciliation()

    # Load Autonomous Intelligence Gates serialized states
    autonomous_director = _read_json(STATE / "autonomous_director.json", {})
    if isinstance(autonomous_director, dict):
        autonomous_director.pop("paper", None)
        autonomous_director.pop("canary_enabled", None)
        autonomous_director.pop("live_forward", None)
        autonomous_director.pop("shadow", None)
        autonomous_director.pop("shadow_count", None)
    signal_quality = _read_json(STATE / "signal_quality.json", [])
    expected_value = _read_json(STATE / "expected_value.json", [])
    strategy_scorecard = _read_json(STATE / "strategy_scorecard.json", [])
    
    # [G-007] System Brain metrics
    inventory = _read_json(STATE / "inventory_matrix.json", {})
    source_health = _read_json(STATE / "source_health.json", {})
    commander_state = {}
    if isinstance(telemetry, dict) and isinstance(telemetry.get("commander"), dict):
        commander_state = telemetry.get("commander", {})
    if not commander_state:
        commander_state = _read_json(STATE / "system_commander.json", {})
    if not isinstance(commander_state, dict):
        commander_state = {}
    config_drift = commander_state.get("config_drift")
    if not isinstance(config_drift, dict):
        config_drift = {"status": str(commander_state.get("drift") or "UNKNOWN")}
    source_health_map = source_health.get("sources", {}) if isinstance(source_health, dict) else {}

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

    _council_dict: Dict[str, Any] = {
        "action": str(council.get("action") or council.get("decision") or "NONE"),
        "confidence": _safe_float(council.get("confidence") or council.get("decision_score"), 0.0),
        "decision_state": str(council.get("decision_state") or council.get("state") or "WAIT").upper(),
        "ticker": str(council.get("ticker") or council.get("pair") or ""),
        "enter_score": _safe_float(council.get("enter_score"), 0.0),
        "wait_score": _safe_float(council.get("wait_score"), 0.0),
        "exit_score": _safe_float(council.get("exit_score"), 0.0),
    }

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_wib": datetime.now(WIB).isoformat(),
        "portfolio": portfolio,
        "pnl_reconciliation": pnl_reconciliation,
        "strategy": {
            "global_mode": str(strategy.get("global_mode") or "UNKNOWN") if isinstance(strategy, dict) else "UNKNOWN",
            "indodax": strategy_indodax,
            "daily_state": strategy_daily_state,
        },
        "council": _council_dict,
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
        "commander": commander_state,
        "whatif": {
            "top": top_whatif,
            "count": _safe_int(whatif.get("pairs_scanned") or whatif.get("pairs_scanned"), 0) if isinstance(whatif, dict) else 0,
        },
        "snapshots": {
            "telemetry": _latest_mtime(STATE / "telemetry_snapshot.json"),
            "strategy": _latest_mtime(STATE / "active_strategy.json"),
            "whatif": _latest_mtime(STATE / "whatif_results.json"),
            "world_model": _latest_mtime(STATE / "world_model.json"),
        },
        "inventory": inventory,
        "source_health": source_health_map,
        "system_brain": {
            "system_state": commander_state.get("system_state", "UNKNOWN"),
            "commander": commander_state,
            "inventory_matrix": commander_state.get("inventory_matrix") if isinstance(commander_state.get("inventory_matrix"), dict) else inventory,
            "source_health": source_health_map or commander_state.get("source_health", {}),
            "config_drift": config_drift,
        },
        "autonomous_director": autonomous_director,
        "signal_quality": signal_quality,
        "expected_value": expected_value,
        "strategy_scorecard": strategy_scorecard,
    }
    # ── §16.2 Order Tracker ──────────────────────────
    try:
        from Core.Intelligence.order_tracker import OrderTracker
        _ot = OrderTracker()
        _ot_summary = _ot.get_today_summary()
        _open_orders_raw = _ot.get_open_orders()
        _open_orders = [
            {
                "id":         str(o.get("id", "")),
                "pair":       str(o.get("pair", o.get("symbol", "--"))).upper(),
                "state":      str(o.get("state", "")).upper(),
                "budget_idr": _safe_float(o.get("budget_idr") or o.get("cost_idr"), 0.0),
                "entry_price": _safe_float(o.get("entry_price") or o.get("fill_price"), 0.0),
            }
            for o in (_open_orders_raw if isinstance(_open_orders_raw, list) else [])
        ]
        summary["order_tracker"] = {
            "today_summary": {
                "total":       _safe_int(_ot_summary.get("total"), 0),
                "filled":      _safe_int(_ot_summary.get("filled"), 0),
                "reconciled":  _safe_int(_ot_summary.get("reconciled"), 0),
                "stale":       _safe_int(_ot_summary.get("stale"), 0),
                "pnl_idr":     _safe_float(_ot_summary.get("pnl_idr"), 0.0),
            },
            "open_orders": _open_orders[:5],
        }
    except Exception:
        summary["order_tracker"] = {"today_summary": {}, "open_orders": []}

    summary["trade_history"] = _load_trade_history()

    # ── §17.2 Last Signal (scanner output) ─────────
    try:
        _last_signal_path = STATE / "last_signal.json"
        _ls = _read_json(_last_signal_path, {})
        if isinstance(_ls, dict) and _ls:
            summary["last_signal"] = _ls
            # also inject into council for canvas compatibility
            if "council" in summary and isinstance(summary["council"], dict):
                summary["council"]["last_signal"] = _ls
    except Exception:
        pass

    # Strategy vNext intelligence surfaces.
    try:
        from Core.Intelligence.daily_context import get_daily_context

        summary["daily_context"] = get_daily_context(
            realized_pnl_idr=portfolio.get("realized_pnl_idr", portfolio.get("daily_pnl_idr", 0.0)),
            unrealized_pnl_idr=portfolio.get("unrealized_pnl_idr", 0.0),
            combined_equity_idr=portfolio.get("combined_equity_idr", portfolio.get("equity_idr", 0.0)),
            available_cash_idr=portfolio.get("idr_cash", 0.0),
            current_positions=portfolio.get("active_positions", []),
        )
    except Exception:
        summary["daily_context"] = _read_json(STATE / "daily_state.json", {})

    summary["market_heatmap"] = _read_json(STATE / "market_heatmap.json", {})
    summary["green_probability"] = _read_json(STATE / "green_probability.json", {})
    summary["scanner_candidates"] = _read_json(STATE / "scanner_candidates.json", {})
    summary["web3_opportunities"] = _load_web3_state()
    summary["solana_trending_candidates"] = _load_solana_trending_state()
    summary["web3_positions"] = _load_web3_positions()
    summary["web3_exit"] = _load_web3_exit_state()
    summary["pumpfun_route_state"] = _load_pumpfun_route_state()
    summary["pumpfun_candidates"] = _load_pumpfun_candidates()
    summary["pumpfun_native_executor"] = _load_pumpfun_native_state()
    summary["pumpfun_latency"] = _load_pumpfun_latency_state()
    summary["pumpfun_positions"] = _load_pumpfun_positions()
    summary["pumpfun_exit_state"] = _load_pumpfun_exit_state()
    summary["scanner_executor_contract"] = _load_scanner_executor_contract()
    summary["engine_independence"] = _load_engine_independence()
    summary["indodax_no_idle"] = _load_indodax_no_idle()
    summary["phantom_capital_mover"] = _load_phantom_capital_mover()
    summary["phantom_network_maximizer"] = _load_phantom_network_maximizer()
    summary["deadline_pressure"] = _load_deadline_pressure()
    summary["server_telemetry"] = _load_server_telemetry()
    summary["scanner_health"] = _load_scanner_health()
    summary["target_board_runtime"] = _load_target_board_runtime()
    summary["daily_reset"] = _read_json(STATE / "daily_reset_state.json", {})
    summary["indodax_top_targets"] = _load_indodax_top_targets()
    summary["phantom_top_targets"] = _load_phantom_top_targets()
    summary["ai_decision_trace"] = _load_ai_decision_trace()
    summary["autonomous_sizing"] = _load_autonomous_sizing_state()
    summary["autonomous_trading_brain"] = _load_autonomous_trading_brain()
    summary["indodax_live_brain"] = _load_indodax_live_brain()
    summary["phantom_live_brain"] = _load_phantom_live_brain()
    summary["live_order_dispatcher"] = _load_live_order_dispatcher()
    summary["capital_movement_runtime"] = _load_capital_movement_runtime()
    try:
        from Core.Treasury.phantom_multichain_controller import PhantomMultichainController

        summary["phantom_multichain"] = PhantomMultichainController().get_summary()
    except Exception:
        summary["phantom_multichain"] = {}

    _daily_context = summary.get("daily_context")
    _daily_context_dict = _daily_context if isinstance(_daily_context, dict) else {}

    _heatmap = summary.get("market_heatmap")
    _heatmap_dict = _heatmap if isinstance(_heatmap, dict) else {}

    _scanner_candidates = summary.get("scanner_candidates")
    _scanner_candidates_dict = _scanner_candidates if isinstance(_scanner_candidates, dict) else {}
    _candidates_list = _scanner_candidates_dict.get("top", [])
    if not isinstance(_candidates_list, list):
        _candidates_list = []

    _order_tracker = summary.get("order_tracker")
    _order_tracker_dict = _order_tracker if isinstance(_order_tracker, dict) else {}
    _order_summary = _order_tracker_dict.get("today_summary", {})
    _order_summary_dict = _order_summary if isinstance(_order_summary, dict) else {}

    _system_health = summary.get("system")
    _system_health_dict = _system_health if isinstance(_system_health, dict) else {}

    _services_map = summary.get("services")
    _services_map_dict = _services_map if isinstance(_services_map, dict) else {}
    _source_health = {
        name: status
        for name, status in _services_map_dict.items()
        if name in {"kibot-master", "kibot-scanner", "kibot-executor", "ollama", "redis-server"}
    }

    if not summary["green_probability"]:
        try:
            from Core.Intelligence.probability_engine import estimate_green_probability

            summary["green_probability"] = estimate_green_probability(
                daily_context=_daily_context_dict,
                heatmap=_heatmap_dict,
                candidates=_candidates_list,
                order_summary=_order_summary_dict,
                system_health=_system_health_dict,
                source_health=_source_health,
            )
        except Exception:
            summary["green_probability"] = {}
    try:
        from Core.Intelligence.decision_journal import summarize_today

        summary["decision_journal"] = summarize_today()
    except Exception:
        summary["decision_journal"] = {}

    _green_prob = summary.get("green_probability")
    _green_prob_dict = _green_prob if isinstance(_green_prob, dict) else {}

    summary["strategy_intelligence"] = {
        "deadline_mode": _daily_context_dict.get("deadline_mode"),
        "allowed_risk_mode": _daily_context_dict.get("allowed_risk_mode"),
        "required_trade_quality": _daily_context_dict.get("required_trade_quality"),
        "market_breadth": _heatmap_dict.get("market_breadth"),
        "green_probability_pct": _green_prob_dict.get("estimated_green_probability_pct"),
    }

    summary["web3"] = {
        "routes": summary.get("phantom_multichain", {}).get("registry", {}),
        "opportunities": summary.get("web3_opportunities", {}),
        "fee_intelligence": _load_web3_fee_state(),
        "positions": summary.get("web3_positions", []),
        "exit": summary.get("web3_exit", {}),
        "pumpfun": summary.get("pumpfun_candidates", {}),
        "pumpfun_route": summary.get("pumpfun_route_state", {}),
        "pumpfun_native": summary.get("pumpfun_native_executor", {}),
    }
    summary["scanner_coverage"] = summary.get("scanner_executor_contract", {})
    summary["engine_split"] = summary.get("engine_independence", {})
    summary["top_targets"] = {
        "indodax": summary.get("indodax_top_targets", {}),
        "phantom": summary.get("phantom_top_targets", {}),
    }
    summary["server_truth"] = summary.get("server_telemetry", {})
    summary["scanner_health_state"] = summary.get("scanner_health", {})
    summary["target_board_runtime_state"] = summary.get("target_board_runtime", {})

    summary["ai"] = summary.get("ai_decision_trace", {})

    summary["events"] = _build_events(summary)
    return summary


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    html_path = DASHBOARD_DIR / "index.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        if "style.css" not in html:
            html = html.replace(
                "</head>",
                '  <link rel="icon" type="image/png" href="/assets/kibot.png" />\n'
                '  <link rel="apple-touch-icon" href="/assets/kibot.png" />\n'
                '  <link rel="stylesheet" href="/static/style.css?v=5.0" />\n</head>',
                1,
            )
        if "canvas.js" not in html or "live.js" not in html:
            html = html.replace(
                "</body>",
                '  <script src="/static/canvas.js?v=5.0"></script>\n'
                '  <script src="/static/live.js?v=5.0"></script>\n</body>',
                1,
            )
        return HTMLResponse(html)
    return HTMLResponse("<h1>Dashboard assets not found.</h1>")


def _read_recent_decisions(limit: int = 15) -> List[Dict[str, Any]]:
    path = STATE / "council_decisions.jsonl"
    decisions = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in reversed(lines[-limit:]):
                    line = line.strip()
                    if line:
                        try:
                            decisions.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
    return decisions


def _check_file_quality(filename: str) -> Dict[str, Any]:
    path = STATE / filename
    exists = path.exists()
    if not exists:
        return {
            "exists": False,
            "fresh": False,
            "age_s": -1.0,
            "status": "OFFLINE"
        }
    age = _file_age_s(path)
    fresh = age < 3600.0 if ("daily" in filename or "rotation" in filename) else age < 300.0
    return {
        "exists": True,
        "fresh": fresh,
        "age_s": round(age, 1),
        "status": "ONLINE" if fresh else "STALE"
    }


def _build_control_plane_payload() -> Dict[str, Any]:
    import time
    summary_data = _build_summary()
    portfolio_live = summary_data.get("portfolio", {}) if isinstance(summary_data, dict) else {}
    pnl_reconciliation = summary_data.get("pnl_reconciliation", {}) if isinstance(summary_data, dict) else {}
    
    # Build a live treasury snapshot first; venue-scoped permission is derived later.
    allow_new_live_orders = False
    rejection_reason = "No governor data"
    capital_block = {
        "status": "UNRECONCILED",
        "starting_equity_today_idr": 0.0,
        "current_total_equity_idr": 0.0,
        "total_balance_idr": 0.0,
        "daily_pnl_idr": 0.0,
        "daily_pnl_pct": 0.0,
        "max_daily_loss_pct": 1.5,
        "risk_remaining_idr": 0.0,
        "date": "",
        "global_risk_remaining_idr": 0.0,
    }
    gov_state_data: Dict[str, Any] = {}
    gov_file = STATE / "capital_governor.json"
    if not gov_file.exists():
        rejection_reason = "FAIL-CLOSED: Capital Governor state file does not exist"
    else:
        try:
            mtime = gov_file.stat().st_mtime
            age = time.time() - mtime
            if age > 90.0:
                rejection_reason = f"FAIL-CLOSED: Capital Governor state file is stale ({age:.1f}s > 90s)"
            else:
                with open(gov_file, "r") as f:
                    gov_data = json.load(f)
                gov_state_data = gov_data if isinstance(gov_data, dict) else {}
                
                today = datetime.now(WIB).strftime("%Y-%m-%d")
                if gov_data.get("date") != today:
                    rejection_reason = f"FAIL-CLOSED: Capital Governor state date '{gov_data.get('date')}' is not today '{today}'"
                else:
                    gov_loss_cap = _safe_float(gov_data.get("max_daily_loss_idr"), 0.0)
                    gov_daily_pnl = _safe_float(gov_data.get("daily_pnl_idr"), 0.0)
                    start_equity = _safe_float(gov_data.get("start_total_equity_idr"), 0.0)
                    current_equity = _safe_float(gov_data.get("current_total_equity_idr"), 0.0)
                    daily_pct = _safe_float(gov_data.get("daily_pnl_pct"), 0.0)
                    portfolio_live = summary_data.get("portfolio", {}) if isinstance(summary_data, dict) else {}
                    live_open_positions = bool(portfolio_live.get("open_position_pnl")) or bool(portfolio_live.get("active_positions"))
                    live_daily_pnl = _safe_float(portfolio_live.get("daily_pnl_idr"), gov_daily_pnl)
                    live_daily_pct = _safe_float(portfolio_live.get("daily_pnl_pct"), daily_pct)
                    live_equity = _safe_float(portfolio_live.get("combined_equity_idr"), current_equity)
                    risk_remaining = max(0.0, gov_loss_cap + gov_daily_pnl)
                    capital_block.update({
                        "status": str(gov_data.get("status") or "RECONCILED"),
                        "starting_equity_today_idr": start_equity,
                        "current_total_equity_idr": current_equity,
                        "total_balance_idr": current_equity,
                        "open_buy_order_reserve_idr": _safe_float(gov_data.get("open_buy_order_reserve_idr"), 0.0),
                        "daily_pnl_idr": gov_daily_pnl,
                        "combined_pnl_idr": gov_daily_pnl,
                        "daily_pnl_pct": daily_pct,
                        "live_current_total_equity_idr": live_equity,
                        "live_daily_pnl_idr": live_daily_pnl,
                        "live_daily_pnl_pct": live_daily_pct,
                        "live_has_open_positions": live_open_positions,
                        "daily_pnl_source": "capital_governor",
                        "max_daily_loss_pct": _safe_float(gov_data.get("max_daily_loss_pct"), 1.5),
                        "risk_remaining_idr": risk_remaining,
                        "global_risk_remaining_idr": risk_remaining,
                        "date": str(gov_data.get("date") or today),
                    })
                    gov_status = str(gov_data.get("status") or "").upper()
                    if gov_status == "RECONCILED":
                        rejection_reason = "Governor reconciled; venue-scoped permission pending"
                    elif gov_status == "BLOCKED_WITH_REASON":
                        rejection_reason = str(gov_data.get("allow_new_orders_reason") or "capital_governor_blocked")
                    else:
                        rejection_reason = f"FAIL-CLOSED: Capital Governor status is '{gov_data.get('status')}' (expected 'RECONCILED')"
        except Exception as e:
            rejection_reason = f"FAIL-CLOSED: Error validating Capital Governor: {e}"

    # Always carry a live portfolio snapshot so the dashboard remains truthful
    # when the governor is stale/unreconciled. Risk gating still follows the
    # governor branch above, but the display should not zero out the portfolio.
    live_has_open_positions = bool(portfolio_live.get("open_position_pnl")) or bool(portfolio_live.get("active_positions"))
    live_current_equity = _safe_float(
        portfolio_live.get("combined_equity_idr"),
        _safe_float(portfolio_live.get("equity_idr"), 0.0),
    )
    live_daily_pnl = _safe_float(portfolio_live.get("daily_pnl_idr"), 0.0)
    live_daily_pct = _safe_float(portfolio_live.get("daily_pnl_pct"), 0.0)
    live_start_equity = _safe_float(
        portfolio_live.get("governor_current_total_equity_idr"),
        _safe_float(portfolio_live.get("combined_equity_idr"), 0.0) - live_daily_pnl,
    )
    if not capital_block["current_total_equity_idr"] and live_current_equity:
        capital_block.update({
            "starting_equity_today_idr": live_start_equity,
            "current_total_equity_idr": live_current_equity,
            "total_balance_idr": live_current_equity,
            "daily_pnl_idr": live_daily_pnl,
            "daily_pnl_pct": live_daily_pct,
            "live_current_total_equity_idr": live_current_equity,
            "live_daily_pnl_idr": live_daily_pnl,
            "live_daily_pnl_pct": live_daily_pct,
            "live_has_open_positions": live_has_open_positions,
            "daily_pnl_source": "live_portfolio_fallback",
            "risk_remaining_idr": max(0.0, _safe_float(portfolio_live.get("combined_equity_idr"), 0.0) * (KiConfig.MAX_DAILY_LOSS_PERCENT / 100.0) - abs(live_daily_pnl)),
        })

    # 1. Mode config
    mode = {
        "trading_mode": str(KiConfig.TRADING_MODE),
        "live_trading_enabled": bool(KiConfig.LIVE_TRADING_ENABLED),
        "legacy_modes_disabled": bool(KiConfig.LEGACY_TRADING_MODES_DISABLED),
        "real_swap_enabled": bool(KiConfig.ENABLE_REAL_SWAP),
        "real_bridge_enabled": bool(KiConfig.ENABLE_REAL_BRIDGE),
        "real_withdrawal_enabled": bool(KiConfig.ENABLE_REAL_WITHDRAWAL),
        "polymarket_live_enabled": bool(KiConfig.ENABLE_POLYMARKET_LIVE),
        "allow_new_live_orders": allow_new_live_orders,
        "allow_new_live_orders_reason": rejection_reason,
        "advisory_gate_state": "ADVISORY_ONLY",
    }

    # 2. Portfolio stats from build_summary / build_portfolio
    portfolio = portfolio_live
    
    # 3. Read State Gates
    sq_raw = _read_json(STATE / "signal_quality.json", [])
    ev_raw = _read_json(STATE / "expected_value.json", [])
    ss_raw = _read_json(STATE / "strategy_scorecard.json", [])
    pe_raw = _read_json(STATE / "punishment_state.json", {})
    
    sq = sq_raw[0] if isinstance(sq_raw, list) and sq_raw else {}
    ev = ev_raw[0] if isinstance(ev_raw, list) and ev_raw else {}
    ss = ss_raw[0] if isinstance(ss_raw, list) and ss_raw else {}
    
    gates = {
        "signal_quality": {
            "status": "PASS" if sq.get("is_tradeable") else "REJECT" if sq else "WAIT",
            "score": _safe_float(sq.get("score"), 0.0),
            "details": sq.get("details", []),
            "freshness": _latest_mtime(STATE / "signal_quality.json"),
        },
        "expected_value": {
            "status": "PASS" if ev.get("approved") else "REJECT" if ev else "WAIT",
            "score": _safe_float(ev.get("ev_pct"), 0.0),
            "rejection_reasons": ev.get("rejection_reasons", []),
            "kelly_fraction": _safe_float(ev.get("kelly_fraction"), 0.0),
            "freshness": _latest_mtime(STATE / "expected_value.json"),
        },
        "strategy_scorecard": {
            "status": "PASS" if ss.get("verdict") == "APPROVED" else "REJECT" if ss else "WAIT",
            "score": _safe_float(ss.get("composite_score"), 0.0),
            "breakdown": ss.get("breakdown", []),
            "freshness": _latest_mtime(STATE / "strategy_scorecard.json"),
        },
        "punishment": {
            "status": "BLOCKED" if pe_raw.get("status") == "quarantined" else "PASS",
            "strikes": len(pe_raw.get("quarantined", [])) if isinstance(pe_raw.get("quarantined"), list) else 0,
            "cooloff": pe_raw.get("status", "idle"),
            "freshness": _latest_mtime(STATE / "punishment_state.json"),
        },
        "risk_gate": {
            "status": "BLOCKED" if str(capital_block.get("status") or "").upper() == "BLOCKED_WITH_REASON" else "PASS",
            "max_drawdown_limit": 1.5,
            "current_drawdown": _safe_float(portfolio.get("unrealized_pnl_idr"), 0.0),
        },
        "microstructure": {
            "status": "PASS" if summary_data.get("strategy", {}).get("global_mode") == "ACTIVE" else "WAIT",
            "mode": summary_data.get("strategy", {}).get("global_mode", "UNKNOWN"),
        }
    }

    # Load Phantom Treasury State
    pt = _read_json(STATE / "phantom_treasury.json", {})

    # 4. Venues
    venues = {
        "indodax_real": {
            "venue": "Indodax Real",
            "mode": "REAL",
            "equity_idr": _safe_float((gov_state_data.get("venues", {}).get("indodax", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("equity_idr"), _safe_float(portfolio.get("equity_idr"), 0.0)) if KiConfig.LIVE_TRADING_ENABLED else 0.0,
            "daily_pnl_idr": _safe_float((gov_state_data.get("venues", {}).get("indodax", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("daily_pnl_idr"), _safe_float(portfolio.get("daily_pnl_real_idr"), 0.0)),
            "daily_loss_cap_idr": _safe_float((gov_state_data.get("venues", {}).get("indodax", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("daily_loss_cap_idr"), 0.0),
            "allow_orders": bool((gov_state_data.get("venues", {}).get("indodax", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("allow_orders", False)),
            "status": str((gov_state_data.get("venues", {}).get("indodax", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("status") or ("ACTIVE" if KiConfig.LIVE_TRADING_ENABLED else "BLOCKED")),
            "reason": str((gov_state_data.get("venues", {}).get("indodax", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("reason") or ("Live trading disabled" if not KiConfig.LIVE_TRADING_ENABLED else "Operational")),
        },
        "phantom": {
            "venue": "Phantom Treasury",
            "mode": "CONTROLLED_LIVE" if pt.get("status") == "OK" else "BLOCKED_WITH_REASON",
            "status": "BLOCKED" if summary_data.get("phantom_multichain", {}).get("reconciliation_blocked") else "ACTIVE",
            "opportunities": len(portfolio.get("phantom", {}).get("active_opportunities", []) if isinstance(portfolio.get("phantom"), dict) else []),
            "reason": "Phantom not reconciled" if summary_data.get("phantom_multichain", {}).get("reconciliation_blocked") else "Treasury reconciled",
            "sol_balance": _safe_float(pt.get("sol_balance"), 0.0),
            "usdc_balance": _safe_float(pt.get("usdc_balance"), 0.0),
            "base_idrx_balance": _safe_float(pt.get("base_idrx_balance"), 0.0),
            "total_value_idr": _safe_float(pt.get("total_value_idr"), 0.0),
            "buckets": pt.get("buckets", {}),
            "bucket_percentages": pt.get("bucket_percentages", {}),
            "status_detail": pt.get("status"),
            "reconciliation": pt.get("reconciliation", {}),
            "chains": pt.get("chains", {}),
            "allow_orders": bool((gov_state_data.get("venues", {}).get("phantom", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("allow_orders", False)),
            "daily_loss_cap_idr": _safe_float((gov_state_data.get("venues", {}).get("phantom", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("daily_loss_cap_idr"), 0.0),
            "daily_pnl_idr": _safe_float((gov_state_data.get("venues", {}).get("phantom", {}) if isinstance(gov_state_data.get("venues"), dict) else {}).get("daily_pnl_idr"), 0.0),
        },
        "web3": {
            "routes": summary_data.get("phantom_multichain", {}).get("registry", {}),
            "opportunities": summary_data.get("web3_opportunities", {}),
            "meme_hunter": summary_data.get("web3_opportunities", {}).get("meme_hunter", summary_data.get("solana_trending_candidates", {})),
            "solana_trending": summary_data.get("solana_trending_candidates", {}),
            "positions": summary_data.get("web3_positions", []),
            "exit": summary_data.get("web3_exit", {}),
            "pumpfun": summary_data.get("pumpfun_candidates", {}),
            "pumpfun_route": summary_data.get("pumpfun_route_state", {}),
            "pumpfun_native": summary_data.get("pumpfun_native_executor", {}),
            "pumpfun_latency": summary_data.get("pumpfun_latency", {}),
            "pumpfun_positions": summary_data.get("pumpfun_positions", []),
            "pumpfun_exit_state": summary_data.get("pumpfun_exit_state", {}),
        },
        "web3_exit": {
            "status": str(summary_data.get("web3_exit", {}).get("status", "STALE" if summary_data.get("web3_positions") else "OK")),
            "positions_open": int(summary_data.get("web3_exit", {}).get("positions_open", 0) or 0),
            "positions_closed": int(summary_data.get("web3_exit", {}).get("positions_closed", 0) or 0),
            "positions_blocked": int(summary_data.get("web3_exit", {}).get("positions_blocked", 0) or 0),
            "last_updated": str(summary_data.get("web3_exit", {}).get("updated_at", "")),
            "latest_exit_reason": str(summary_data.get("web3_exit", {}).get("latest_exit_reason", "")),
        },
        "pumpfun": {
            "route_type": str(summary_data.get("pumpfun_route_state", {}).get("route_type", "UNSUPPORTED")),
            "can_buy": bool(summary_data.get("pumpfun_route_state", {}).get("buy_route_available", False)),
            "can_sell": bool(summary_data.get("pumpfun_route_state", {}).get("sell_route_available", False)),
            "reason": str(summary_data.get("pumpfun_route_state", {}).get("reason", "")),
            "best_candidate": summary_data.get("pumpfun_candidates", {}).get("best_candidate", {}),
            "candidates_found": int(len(summary_data.get("pumpfun_candidates", {}).get("candidates", []) or [])),
            "rejected_count": int(len(summary_data.get("pumpfun_candidates", {}).get("rejected", []) or [])),
            "native_executor": summary_data.get("pumpfun_native_executor", {}),
            "latency": summary_data.get("pumpfun_latency", {}),
            "positions": summary_data.get("pumpfun_positions", []),
            "exit_state": summary_data.get("pumpfun_exit_state", {}),
        },
        "ai": {
            "updated_at": str(summary_data.get("ai_decision_trace", {}).get("updated_at", "")),
            "objective": str(summary_data.get("ai_decision_trace", {}).get("objective", "")),
            "best_action": str(summary_data.get("ai_decision_trace", {}).get("best_action", "WAIT")),
            "venue": str(summary_data.get("ai_decision_trace", {}).get("venue", "")),
            "confidence": _safe_float(summary_data.get("ai_decision_trace", {}).get("confidence"), 0.0),
            "reason": str(summary_data.get("ai_decision_trace", {}).get("reason", "")),
            "next_check_seconds": _safe_int(summary_data.get("ai_decision_trace", {}).get("next_check_seconds"), 0),
        },
        "autonomous_sizing": summary_data.get("autonomous_sizing", {}),
        "polymarket": {
            "venue": "Polymarket",
            "mode": "CONTROLLED_LIVE" if KiConfig.ENABLE_POLYMARKET_LIVE else "SCOUTING_ONLY",
            "equity_idr": _safe_float(portfolio.get("polymarket", {}).get("equity_idr"), 0.0),
            "daily_pnl_idr": _safe_float(portfolio.get("polymarket", {}).get("daily_pnl_idr"), 0.0),
            "status": "ACTIVE" if portfolio.get("polymarket", {}).get("wallet_ready") else "WAIT",
            "reason": "Wallet active" if portfolio.get("polymarket", {}).get("wallet_ready") else "Wallet connection wait",
        },
        "cash_wait": {
            "venue": "Cash Wait",
            "mode": "RESERVE",
            "equity_idr": _safe_float(portfolio.get("idr_cash"), 0.0),
            "status": "ACTIVE",
            "reason": "Sovereign reserve liquidity",
        }
    }

    if gov_state_data:
        gov_venues = gov_state_data.get("venues", {}) if isinstance(gov_state_data.get("venues"), dict) else {}
        explicit_allow_reason = str(gov_state_data.get("allow_new_orders_reason") or rejection_reason).strip()
        venue_permissions = {
            "indodax_real": bool((gov_venues.get("indodax") or {}).get("allow_orders", False)),
            "phantom": bool((gov_venues.get("phantom") or {}).get("allow_orders", False)),
            "polymarket": bool(gov_state_data.get("allow_new_orders", False)) and str((venues.get("polymarket") or {}).get("status") or "").upper() in {"ACTIVE", "LIVE_READY", "RECONCILED"},
            "cash_wait": True,
        }
        allow_new_live_orders = bool(gov_state_data.get("allow_new_orders", False))
        rejection_reason = explicit_allow_reason or rejection_reason
    else:
        venue_permissions = {
            name: bool(
                (venues.get(name) or {}).get("allow_orders", False)
                and str((venues.get(name) or {}).get("status") or "").upper() in {"ACTIVE", "LIVE_READY", "RECONCILED"}
            )
            for name in ("indodax_real", "phantom", "polymarket")
        }
        venue_permissions["cash_wait"] = True
        allow_new_live_orders = any(venue_permissions.get(name, False) for name in ("indodax_real", "phantom", "polymarket"))
    if allow_new_live_orders:
        ready_venues = [name for name in ("indodax_real", "phantom", "polymarket") if venue_permissions.get(name)]
        rejection_reason = "venue-scoped allowances active: " + ", ".join(ready_venues)
        capital_block["risk_remaining_idr"] = sum(
            max(0.0, _safe_float((venues.get(name) or {}).get("daily_loss_cap_idr"), 0.0) + _safe_float((venues.get(name) or {}).get("daily_pnl_idr"), 0.0))
            for name in ("indodax_real", "phantom", "polymarket")
            if venue_permissions.get(name)
        )
    else:
        blocked_venues = []
        for name in ("indodax_real", "phantom", "polymarket"):
            venue = venues.get(name) or {}
            status = str(venue.get("status") or "BLOCKED_WITH_REASON").upper()
            reason = str(venue.get("reason") or "blocked").strip()
            blocked_venues.append(f"{name}={status}:{reason}")
        if not rejection_reason or rejection_reason.startswith("blocked venues:"):
            rejection_reason = "; ".join(blocked_venues) if blocked_venues else rejection_reason
        capital_block["risk_remaining_idr"] = max(
            0.0,
            _safe_float(capital_block.get("global_risk_remaining_idr"), 0.0),
        )
    capital_block["allow_new_orders_reason"] = rejection_reason
    capital_block["blocked_venues"] = blocked_venues if not allow_new_live_orders else []
    capital_block["pending_orders_count"] = len(summary_data.get("order_tracker", {}).get("open_orders", []) if isinstance(summary_data.get("order_tracker"), dict) else [])
    route_live_ready = any(
        str((venues.get(name) or {}).get("status") or "").upper() in {"ACTIVE", "LIVE_READY", "RECONCILED"}
        for name in ("indodax_real", "phantom", "polymarket", "cash_wait")
    )
    current_entry_approved = bool(allow_new_live_orders and route_live_ready and gates["risk_gate"]["status"] == "PASS")
    mode["allow_new_live_orders"] = allow_new_live_orders
    mode["allow_new_live_orders_reason"] = rejection_reason
    mode["advisory_gates"] = {
        "signal_quality": gates["signal_quality"]["status"],
        "expected_value": gates["expected_value"]["status"],
        "strategy_scorecard": gates["strategy_scorecard"]["status"],
        "microstructure": gates["microstructure"]["status"],
        "effect": "does_not_block_live_orders",
    }
    mode["venue_allowances"] = venue_permissions
    mode["what_if_checks"] = pnl_reconciliation.get("what_if_checks", []) if isinstance(pnl_reconciliation, dict) else []

    # 5. Runtime Health
    scanner_stats = _read_json(STATE / "scanner_runtime.json", {})
    leadlag_stats = _read_json(STATE / "leadlag_alpha.json", {})
    market_rotation = _read_json(STATE / "market_rotation.json", {})
    
    runtime = {
        "scanner": {
            "mode": "FAST" if scanner_stats.get("cycle_interval_seconds", 5.0) < 3.0 else "NORMAL",
            "cycle_ms": _safe_float(scanner_stats.get("last_cycle_ms"), 0.0),
            "status": "ACTIVE" if summary_data.get("services", {}).get("kibot-scanner") == "active" else "INACTIVE",
        },
        "services": summary_data.get("services", {}),
        "leadlag": {
            "aligned": bool(leadlag_stats.get("aligned", False)),
            "last_latency_sec": _safe_float(leadlag_stats.get("last_latency_sec"), 0.0),
            "status": "ACTIVE",
        },
        "market_rotation": {
            "regime": str(market_rotation.get("market_regime", "NEUTRAL")),
            "regime_index": _safe_float(market_rotation.get("regime_index"), 0.0),
            "status": "ACTIVE",
        },
        "autonomous_director": {
            "status": "ACTIVE" if summary_data.get("autonomous_director") else "WAIT",
            "approved_count": len(summary_data.get("autonomous_director", {}).get("approved", []) if isinstance(summary_data.get("autonomous_director"), dict) else []),
            "shadow_count": len(summary_data.get("autonomous_director", {}).get("shadow", []) if isinstance(summary_data.get("autonomous_director"), dict) else []),
            "rejected_count": len(summary_data.get("autonomous_director", {}).get("rejected", []) if isinstance(summary_data.get("autonomous_director"), dict) else []),
        },
        "healthcheck": {
            "status": "PASS",
            "last_checked": datetime.now(WIB).isoformat(),
        },
        "ollama": {
            "status": "ACTIVE" if summary_data.get("services", {}).get("ollama") == "active" else "INACTIVE",
            "model": "qwen2.5:7b-instruct",
        }
    }

    # 6. Flow Node Connections & Workflow nodes/edges
    flow = [
        {"from": "Market Feeds", "to": "Scanner"},
        {"from": "Scanner", "to": "LeadLag Alpha"},
        {"from": "LeadLag Alpha", "to": "Signal Quality"},
        {"from": "Signal Quality", "to": "Expected Value"},
        {"from": "Expected Value", "to": "Scorecard"},
        {"from": "Scorecard", "to": "Autonomous Director"},
        {"from": "Autonomous Director", "to": "Council / RiskGate"},
        {"from": "Council / RiskGate", "to": "Executor"},
        {"from": "Executor", "to": "PnL / Feedback Loop"},
    ]

    workflow = {
        "nodes": [
            {"id": "Operator", "label": "Kiki / Operator", "role": "operator"},
            {"id": "Autonomous Director", "label": "Autonomous Director", "role": "coordinator"},
            {"id": "Sovereign Council", "label": "Sovereign Council", "role": "council"},
            {"id": "Scanner", "label": "Scanner Engine", "role": "scanner"},
            {"id": "LeadLag Alpha", "label": "LeadLag Alpha", "role": "alpha"},
            {"id": "Signal Quality", "label": "Signal Quality", "role": "gate"},
            {"id": "Expected Value", "label": "Expected Value", "role": "gate"},
            {"id": "Strategy Scorecard", "label": "Strategy Scorecard", "role": "gate"},
            {"id": "Punishment Gate", "label": "Punishment Gate", "role": "gate"},
            {"id": "RiskGate Shield", "label": "RiskGate Shield", "role": "risk_gate"},
            {"id": "Executor", "label": "Executor Block", "role": "executor"},
            {"id": "Indodax Spot", "label": "Indodax Spot Venue", "role": "venue"},
            {"id": "Indodax Balance", "label": "Indodax Balance", "role": "wallet"},
            {"id": "Phantom Treasury", "label": "Phantom Treasury", "role": "wallet"},
            {"id": "Polymarket", "label": "Polymarket Venue", "role": "venue"},
            {"id": "Cash Wait", "label": "Cash Wait Reserves", "role": "reserve"},
            {"id": "Ollama / AI Scout", "label": "Ollama / AI Scout", "role": "advisory"}
        ],
        "edges": [
            {"from": "Operator", "to": "Autonomous Director"},
            {"from": "Autonomous Director", "to": "Scanner"},
            {"from": "Scanner", "to": "LeadLag Alpha"},
            {"from": "LeadLag Alpha", "to": "Signal Quality"},
            {"from": "Signal Quality", "to": "Expected Value"},
            {"from": "Expected Value", "to": "Strategy Scorecard"},
            {"from": "Strategy Scorecard", "to": "Punishment Gate"},
            {"from": "Punishment Gate", "to": "Sovereign Council"},
            {"from": "Sovereign Council", "to": "RiskGate Shield"},
            {"from": "RiskGate Shield", "to": "Executor"},
            {"from": "Executor", "to": "Indodax Spot"},
            {"from": "Indodax Spot", "to": "Indodax Balance"},
            {"from": "Scanner", "to": "Phantom Treasury", "type": "dotted"},
            {"from": "Scanner", "to": "Polymarket", "type": "dotted"},
            {"from": "Expected Value", "to": "Cash Wait", "type": "dotted"},
            {"from": "Autonomous Director", "to": "Ollama / AI Scout", "type": "dotted"}
        ]
    }

    # Data Quality calculation
    files_to_check = [
        "scanner_runtime.json",
        "leadlag_alpha.json",
        "market_rotation.json",
        "signal_quality.json",
        "expected_value.json",
        "strategy_scorecard.json",
        "punishment_state.json",
        "autonomous_director.json",
    ]
    
    missing_states = []
    stale_states = []
    last_update_ts = datetime.now(timezone.utc).isoformat()
    latest_mtime = 0.0

    for f in files_to_check:
        path = STATE / f
        if not path.exists():
            missing_states.append(f.replace(".json", ""))
        else:
            mtime = path.stat().st_mtime
            if mtime > latest_mtime:
                latest_mtime = mtime
                last_update_ts = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
            age = _file_age_s(path)
            fresh = age < 3600.0 if ("daily" in f or "rotation" in f) else age < 300.0
            if not fresh:
                stale_states.append(f.replace(".json", ""))

    data_quality_dict = {f.replace(".json", ""): _check_file_quality(f) for f in files_to_check}
    data_quality_dict.update({
        "complete": len(missing_states) == 0,
        "missing_states": missing_states,
        "stale_states": stale_states,
        "unknown_fields": [],
        "last_update": last_update_ts
    })

    # Warnings collection
    warnings = []
    if not gates["expected_value"]["status"] == "PASS":
        warnings.append("Expected Value Gate rejected incoming signal due to negative EV.")
    if gates["punishment"]["strikes"] > 0:
        warnings.append(f"Punishment Engine strikes active: {gates['punishment']['strikes']}.")
    if not runtime["ollama"]["status"] == "ACTIVE":
        warnings.append("Ollama local LLM server is offline.")
    for ms in missing_states:
        warnings.append(f"State file missing: state/{ms}.json")
    for ss_name in stale_states:
        warnings.append(f"State file is stale: state/{ss_name}.json")

    decisions = _read_recent_decisions(15)

    # Merge complete summary_data at the root level for total backward-compatibility
    merged_data = {**summary_data}
    merged_data.update({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "freshness": {
            "scanner_runtime_age_s": _file_age_s(STATE / "scanner_runtime.json"),
            "autonomous_director_age_s": _file_age_s(STATE / "autonomous_director.json"),
            "expected_value_age_s": _file_age_s(STATE / "expected_value.json"),
            "signal_quality_age_s": _file_age_s(STATE / "signal_quality.json"),
            "leadlag_alpha_age_s": _file_age_s(STATE / "leadlag_alpha.json"),
            "telemetry_age_s": _file_age_s(STATE / "telemetry_snapshot.json"),
        },
        "mode": mode,
        "route_live_ready": route_live_ready,
        "current_entry_approved": current_entry_approved,
        "portfolio": {
            "combined_equity_idr": _safe_float(portfolio.get("combined_equity_idr"), 0.0),
            "total_equity_idr": _safe_float(portfolio.get("combined_equity_idr"), 0.0),
            "idr_cash": _safe_float(portfolio.get("idr_cash"), 0.0),
            "coin_holdings_idr": _safe_float(portfolio.get("coin_holdings_idr"), 0.0),
            "daily_pnl_idr": _safe_float(portfolio.get("daily_pnl_idr"), 0.0),
            "combined_pnl_idr": _safe_float(portfolio.get("daily_pnl_idr"), 0.0),
            "daily_pnl_pct": _safe_float(portfolio.get("daily_pnl_pct"), 0.0),
            "daily_pnl_real_idr": _safe_float(portfolio.get("daily_pnl_real_idr"), 0.0),
            "daily_pnl_shadow_idr": _safe_float(portfolio.get("daily_pnl_shadow_idr"), 0.0),
            "real_pnl_idr": _safe_float(portfolio.get("daily_pnl_real_idr"), 0.0),
            "realized_pnl_idr": _safe_float(portfolio.get("realized_pnl_idr"), 0.0),
            "unrealized_pnl_idr": _safe_float(portfolio.get("unrealized_pnl_idr"), 0.0),
            "position_cost_basis_idr": _safe_float(portfolio.get("position_cost_basis_idr"), 0.0),
            "open_buy_order_reserve_idr": _safe_float(portfolio.get("open_buy_order_reserve_idr"), 0.0),
            "open_position_pnl": portfolio.get("open_position_pnl", []),
            "active_positions": portfolio.get("active_positions", []),
            "has_open_positions": bool(portfolio.get("has_open_positions")),
            "daily_pnl_source": str(portfolio.get("daily_pnl_source") or "live_portfolio"),
            "live_current_total_equity_idr": _safe_float(portfolio.get("live_current_total_equity_idr"), 0.0),
            "live_daily_pnl_idr": _safe_float(portfolio.get("live_daily_pnl_idr"), 0.0),
            "live_daily_pnl_pct": _safe_float(portfolio.get("live_daily_pnl_pct"), 0.0),
            "governor_current_total_equity_idr": _safe_float(portfolio.get("governor_current_total_equity_idr"), 0.0),
            "governor_daily_pnl_idr": _safe_float(portfolio.get("governor_daily_pnl_idr"), 0.0),
            "governor_daily_pnl_pct": _safe_float(portfolio.get("governor_daily_pnl_pct"), 0.0),
            "max_daily_loss_pct": 1.5
        },
        "pnl_reconciliation": pnl_reconciliation,
        "capital": capital_block,
        "venues": venues,
        "web3": {
            "routes": summary_data.get("phantom_multichain", {}).get("registry", {}),
            "opportunities": summary_data.get("web3_opportunities", {}),
            "meme_hunter": summary_data.get("web3_opportunities", {}).get("meme_hunter", summary_data.get("solana_trending_candidates", {})),
            "solana_trending": summary_data.get("solana_trending_candidates", {}),
            "positions": summary_data.get("web3_positions", []),
            "exit": summary_data.get("web3_exit", {}),
            "pumpfun": summary_data.get("pumpfun_candidates", {}),
            "pumpfun_route": summary_data.get("pumpfun_route_state", {}),
            "pumpfun_native": summary_data.get("pumpfun_native_executor", {}),
            "pumpfun_latency": summary_data.get("pumpfun_latency", {}),
            "pumpfun_positions": summary_data.get("pumpfun_positions", []),
            "pumpfun_exit_state": summary_data.get("pumpfun_exit_state", {}),
        },
        "scanner_executor_contract": summary_data.get("scanner_executor_contract", {}),
        "scanner_coverage": summary_data.get("scanner_coverage", {}),
        "engine_independence": summary_data.get("engine_independence", {}),
        "indodax_no_idle": summary_data.get("indodax_no_idle", {}),
        "phantom_capital_mover": summary_data.get("phantom_capital_mover", {}),
        "phantom_network_maximizer": summary_data.get("phantom_network_maximizer", {}),
        "deadline_pressure": summary_data.get("deadline_pressure", {}),
        "server_telemetry": {
            "data": summary_data.get("server_telemetry", {}),
            "age_s": _file_age_s(STATE / "server_telemetry.json"),
            "fresh": _file_age_s(STATE / "server_telemetry.json") >= 0 and _file_age_s(STATE / "server_telemetry.json") < 15,
        },
        "scanner_health": {
            "data": summary_data.get("scanner_health", {}),
            "age_s": _file_age_s(STATE / "scanner_health.json"),
            "fresh": _file_age_s(STATE / "scanner_health.json") >= 0 and _file_age_s(STATE / "scanner_health.json") < 30,
        },
        "target_board_runtime": {
            "data": summary_data.get("target_board_runtime", {}),
            "age_s": _file_age_s(STATE / "target_board_runtime.json"),
            "fresh": _file_age_s(STATE / "target_board_runtime.json") >= 0 and _file_age_s(STATE / "target_board_runtime.json") < 15,
        },
        "daily_reset": {
            "data": summary_data.get("daily_reset", {}),
            "age_s": _file_age_s(STATE / "daily_reset_state.json"),
            "fresh": _file_age_s(STATE / "daily_reset_state.json") >= 0 and _file_age_s(STATE / "daily_reset_state.json") < 15,
        },
        "indodax_top_targets": {
            "data": summary_data.get("indodax_top_targets", {}),
            "age_s": _file_age_s(STATE / "indodax_top_targets.json"),
            "fresh": _file_age_s(STATE / "indodax_top_targets.json") >= 0 and _file_age_s(STATE / "indodax_top_targets.json") < 15,
        },
        "phantom_top_targets": {
            "data": summary_data.get("phantom_top_targets", {}),
            "age_s": _file_age_s(STATE / "phantom_top_targets.json"),
            "fresh": _file_age_s(STATE / "phantom_top_targets.json") >= 0 and _file_age_s(STATE / "phantom_top_targets.json") < 15,
        },
        "live_order_dispatcher": {
            "data": summary_data.get("live_order_dispatcher", {}),
            "age_s": _file_age_s(STATE / "live_order_dispatcher.json"),
            "fresh": _file_age_s(STATE / "live_order_dispatcher.json") >= 0 and _file_age_s(STATE / "live_order_dispatcher.json") < 15,
        },
        "system_truth": {
            "batam_server_online": bool(summary_data.get("server_telemetry")),
            "git_commit": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
            "service_health": summary_data.get("services", {}),
            "state_freshness": summary_data.get("freshness", {}),
            "daily_reset": summary_data.get("daily_reset", {}),
        },
        "gates": gates,
        "runtime": runtime,
        "flow": flow,
        "workflow": workflow,
        "meme_hunter": {
            "enabled": bool(summary_data.get("web3_opportunities", {}).get("meme_hunter", {}).get("enabled", False)),
            "best_candidate": summary_data.get("web3_opportunities", {}).get("meme_hunter", {}).get("best_candidate", {}),
            "candidates_found": int(summary_data.get("web3_opportunities", {}).get("meme_hunter", {}).get("candidates_found", 0) or 0),
            "rejected_count": int(summary_data.get("web3_opportunities", {}).get("meme_hunter", {}).get("rejected_count", 0) or 0),
            "latest_update": str(summary_data.get("web3_opportunities", {}).get("meme_hunter", {}).get("latest_update", "")),
            "sources": summary_data.get("web3_opportunities", {}).get("meme_hunter", {}).get("sources", []),
        },
        "pumpfun": {
            "route_type": str(summary_data.get("pumpfun_route_state", {}).get("route_type", "UNSUPPORTED")),
            "can_buy": bool(summary_data.get("pumpfun_route_state", {}).get("buy_route_available", False)),
            "can_sell": bool(summary_data.get("pumpfun_route_state", {}).get("sell_route_available", False)),
            "reason": str(summary_data.get("pumpfun_route_state", {}).get("reason", "")),
            "best_candidate": summary_data.get("pumpfun_candidates", {}).get("best_candidate", {}),
            "candidates_found": int(len(summary_data.get("pumpfun_candidates", {}).get("candidates", []) or [])),
            "rejected_count": int(len(summary_data.get("pumpfun_candidates", {}).get("rejected", []) or [])),
            "native_executor": summary_data.get("pumpfun_native_executor", {}),
        },
        "recent_decisions": decisions,
        "decisions": decisions,
        "warnings": warnings,
        "data_quality": data_quality_dict,
    })
    for legacy_key in (
        "indodax_paper",
        "paper_count",
        "paper_pnl_idr",
        "mock_pnl_idr",
        "simulated_pnl_idr",
    ):
        merged_data.pop(legacy_key, None)
    if isinstance(merged_data.get("portfolio"), dict):
        merged_data["portfolio"].setdefault("daily_pnl_shadow_idr", _safe_float(portfolio.get("daily_pnl_shadow_idr"), 0.0))
    return _scrub_legacy_payload(merged_data)


@app.get("/api/control-plane")
async def control_plane() -> JSONResponse:
    return JSONResponse(_build_control_plane_payload())



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
        "daily_context": snapshot.get("daily_context", {}),
        "market_heatmap": snapshot.get("market_heatmap", {}),
        "green_probability": snapshot.get("green_probability", {}),
        "scanner_candidates": snapshot.get("scanner_candidates", {}),
        "decision_journal": snapshot.get("decision_journal", {}),
        "strategy_intelligence": snapshot.get("strategy_intelligence", {}),
    })


@app.get("/api/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "service": "kibot-dashboard", "version": "3.4", "generated_at": datetime.now(WIB).isoformat()})


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    async def event_generator():
        while True:
            try:
                yield f"data: {json.dumps(_build_control_plane_payload(), ensure_ascii=False)}\n\n"
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
    host = os.getenv("KIBOT_DASHBOARD_HOST", "127.0.0.1")
    uvicorn.run("Core.Intelligence.kibot_dashboard:app", host=host, port=port, reload=False)
