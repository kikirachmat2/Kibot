#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from Core.Support.ki_config import PROJECT_ROOT, STATE_DIR

app = FastAPI(title="KiBot Sovereign Dashboard", version="1.0")

ROOT = Path(PROJECT_ROOT)
STATE = Path(STATE_DIR)
LOGS = ROOT / "Logs"


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


def _latest_mtime(paths: List[Path]) -> str:
    mtimes = []
    for path in paths:
        if path.exists():
            try:
                mtimes.append(path.stat().st_mtime)
            except Exception:
                pass
    if not mtimes:
        return "unknown"
    return datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat()


def _build_summary() -> Dict[str, Any]:
    telemetry = _read_json(STATE / "telemetry_snapshot.json", {})
    runtime = _read_json(STATE / "runtime_note.json", {})
    strategy = _read_json(STATE / "active_strategy.json", {})
    whatif = _read_json(STATE / "whatif_results.json", {})
    council = _read_json(STATE / "council_directives.json", {})
    active_trades = _read_json(STATE / "active_trades.json", {})
    logger_state = _read_json(STATE / "ai_coordinator_providers.json", {})
    brain_state = _read_json(STATE / "brain_status.json", {})
    world_model = _read_json(STATE / "world_model.json", {})
    agent_state = _read_json(STATE / "learning_state.json", {})
    ai_search = _read_json(STATE / "ai_search_cache.json", {})

    portfolio = telemetry.get("portfolio") or {}
    indodax_equity = float(portfolio.get("equity_idr") or 0.0)
    combined_equity = float(portfolio.get("combined_equity_idr") or indodax_equity or 0.0)
    daily_pnl = float(portfolio.get("daily_pnl_idr") or 0.0)
    daily_state = portfolio.get("daily_state") or {}
    polymarket = portfolio.get("polymarket") or {}

    services = {}
    for name in [
        "kibot-master",
        "kibot-scanner",
        "kibot-executor",
        "kibot-executor-polymarket",
        "kibot-ai-scout",
        "kibot-janitor",
        "ollama",
        "redis-server",
    ]:
        services[name] = "unknown"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "telemetry": telemetry,
        "runtime": runtime,
        "strategy": strategy,
        "whatif": whatif,
        "council": council,
        "brain": brain_state,
        "world_model": world_model,
        "learning_state": agent_state,
        "ai_search": ai_search,
        "active_trades": active_trades,
        "provider_state": logger_state,
        "portfolio": {
            "indodax_equity_idr": indodax_equity,
            "combined_equity_idr": combined_equity,
            "daily_pnl_idr": daily_pnl,
            "daily_state": daily_state,
            "polymarket": polymarket,
            "indodax_balance": indodax_equity,
            "polymarket_balance_idr": float(polymarket.get("equity_idr") or 0.0),
            "polymarket_usdc_balance": float(polymarket.get("usdc_balance") or 0.0),
        },
        "services": services,
        "logs": {
            "master": _load_lines(LOGS / "kibot-master.log", 40),
            "scanner": _load_lines(LOGS / "kibot-scanner.log", 40),
            "executor": _load_lines(LOGS / "kibot-executor.log", 40),
        },
        "snapshots": {
            "runtime_note": _latest_mtime([STATE / "runtime_note.json"]),
            "telemetry_snapshot": _latest_mtime([STATE / "telemetry_snapshot.json"]),
            "whatif_results": _latest_mtime([STATE / "whatif_results.json"]),
        },
    }


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    return """
    <!doctype html>
    <html lang="id">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>KiBot Sovereign Dashboard</title>
      <style>
        :root {
          --bg: #07111f;
          --panel: rgba(14, 23, 38, 0.88);
          --panel2: rgba(9, 15, 26, 0.92);
          --line: rgba(110, 181, 255, 0.22);
          --text: #e8f2ff;
          --muted: #8fa7c2;
          --green: #48e091;
          --amber: #ffcf5a;
          --red: #ff6b6b;
          --blue: #6eb5ff;
          --accent: #62d6ff;
        }
        body {
          margin: 0;
          font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          background:
            radial-gradient(circle at top left, rgba(98,214,255,0.18), transparent 28%),
            radial-gradient(circle at top right, rgba(72,224,145,0.10), transparent 24%),
            linear-gradient(180deg, #05101d 0%, #091428 44%, #050a14 100%);
          color: var(--text);
        }
        .wrap { max-width: 1560px; margin: 0 auto; padding: 28px; }
        .hero {
          display: grid; grid-template-columns: 1.35fr 0.65fr; gap: 18px;
        }
        .card {
          background: linear-gradient(180deg, var(--panel), var(--panel2));
          border: 1px solid var(--line);
          border-radius: 20px;
          padding: 18px;
          box-shadow: 0 18px 60px rgba(0,0,0,0.28);
        }
        .title { font-size: 36px; font-weight: 800; letter-spacing: -0.05em; margin: 0 0 8px; }
        .sub { color: var(--muted); line-height: 1.5; margin: 0; }
        .grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 18px; }
        .tile { padding: 14px; border-radius: 16px; background: rgba(255,255,255,0.03); border: 1px solid var(--line); min-height: 86px; }
        .label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
        .value { font-size: 22px; font-weight: 700; margin-top: 6px; }
        .section { margin-top: 20px; }
        .section h2 { margin: 0 0 12px; font-size: 18px; letter-spacing: -0.02em; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 12px; border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; font-size: 14px; }
        th { color: var(--muted); font-weight: 600; }
        .pill { display:inline-block; padding: 6px 10px; border-radius: 999px; font-size: 12px; background: rgba(98,214,255,0.12); color: var(--accent); border: 1px solid rgba(98,214,255,0.18); margin-right: 8px; margin-top: 6px; }
        .green { color: var(--green); }
        .amber { color: var(--amber); }
        .red { color: var(--red); }
        pre { white-space: pre-wrap; word-break: break-word; margin: 0; color: #cfe1ff; }
        .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .canvas {
          position: relative;
          min-height: 420px;
          overflow: hidden;
          background:
            radial-gradient(circle at 20% 20%, rgba(98,214,255,0.14), transparent 20%),
            radial-gradient(circle at 80% 10%, rgba(72,224,145,0.12), transparent 18%),
            linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.015));
        }
        .canvas-grid {
          position: absolute;
          inset: 0;
          background-image:
            linear-gradient(rgba(255,255,255,0.045) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px);
          background-size: 38px 38px;
          mask-image: linear-gradient(180deg, rgba(0,0,0,0.75), transparent 92%);
          pointer-events: none;
        }
        .node {
          position: absolute;
          width: 210px;
          border-radius: 18px;
          border: 1px solid rgba(110,181,255,0.22);
          background: rgba(7, 16, 30, 0.88);
          box-shadow: 0 16px 30px rgba(0,0,0,0.22);
          padding: 14px 14px 12px;
          backdrop-filter: blur(12px);
        }
        .node .k { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.09em; }
        .node .v { font-size: 18px; font-weight: 800; margin-top: 4px; }
        .node .s { font-size: 12px; color: #cfe1ff; opacity: 0.9; margin-top: 6px; line-height: 1.45; }
        .node.live { border-color: rgba(72,224,145,0.35); }
        .node.alert { border-color: rgba(255,107,107,0.35); }
        .node.warn { border-color: rgba(255,207,90,0.35); }
        .wire {
          position: absolute;
          height: 3px;
          background: linear-gradient(90deg, rgba(98,214,255,0.0), rgba(98,214,255,0.7), rgba(72,224,145,0.75), rgba(98,214,255,0.0));
          box-shadow: 0 0 16px rgba(98,214,255,0.18);
          border-radius: 999px;
          transform-origin: left center;
        }
        .wire::after {
          content: "";
          position: absolute;
          right: -7px;
          top: -5px;
          width: 12px;
          height: 12px;
          border-radius: 999px;
          background: var(--green);
          box-shadow: 0 0 18px rgba(72,224,145,0.7);
        }
        .flow-title { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
        .mini { font-size: 12px; color: var(--muted); }
        @media (max-width: 1100px) { .hero, .two, .grid { grid-template-columns: 1fr; } }
      </style>
      <script>
        async function refresh() {
          const r = await fetch('/api/summary');
          const d = await r.json();
          document.getElementById('gen').textContent = d.generated_at;
          document.getElementById('equity').textContent = d.portfolio?.combined_equity_idr ? 'Rp ' + Number(d.portfolio.combined_equity_idr).toLocaleString('id-ID') : 'n/a';
          document.getElementById('pnl').textContent = d.portfolio?.daily_pnl_idr ? 'Rp ' + Number(d.portfolio.daily_pnl_idr).toLocaleString('id-ID') : 'n/a';
          document.getElementById('mode').textContent = d.strategy?.global_mode || 'unknown';
          document.getElementById('strategy-mini').textContent = d.strategy?.indodax?.take_profit_pct ? `TP ${d.strategy.indodax.take_profit_pct}% | Conf ${d.strategy.indodax.min_confidence || 'n/a'}` : 'strategy n/a';
          document.getElementById('whatif').textContent = d.whatif?.state || d.world_model?.status || 'n/a';
          document.getElementById('runtime').textContent = d.portfolio?.daily_state?.color || d.runtime?.daily_state || 'n/a';
          document.getElementById('services').textContent = Object.entries(d.services).map(([k,v]) => `${k}: ${v}`).join(' | ');
          document.getElementById('indodax').textContent = d.portfolio?.indodax_equity_idr ? 'Rp ' + Number(d.portfolio.indodax_equity_idr).toLocaleString('id-ID') : 'n/a';
          document.getElementById('poly').textContent = d.portfolio?.polymarket_balance_idr ? 'Rp ' + Number(d.portfolio.polymarket_balance_idr).toLocaleString('id-ID') : 'n/a';
          document.getElementById('usdc').textContent = d.portfolio?.polymarket_usdc_balance ? Number(d.portfolio.polymarket_usdc_balance).toFixed(4) + ' USDC' : 'n/a';
          document.getElementById('scanner-status').textContent = d.services?.['kibot-scanner'] || 'unknown';
          document.getElementById('council-status').textContent = d.council?.decision_state || d.council?.action || 'unknown';
          document.getElementById('executor-status').textContent = d.services?.['kibot-executor'] || 'unknown';
          document.getElementById('janitor-status').textContent = d.services?.['kibot-janitor'] || 'unknown';
          document.getElementById('state').textContent = JSON.stringify({
            daily_state: d.portfolio?.daily_state,
            active_trades: Object.keys(d.active_trades || {}).length,
            whatif: d.whatif?.state || null,
            council: d.council?.decision_state || d.council?.action || null,
            brain: d.brain?.status || null
          }, null, 2);
          document.getElementById('flow-state').textContent = d.portfolio?.daily_state?.color || 'UNKNOWN';
        }
        window.addEventListener('load', refresh);
        setInterval(refresh, 15000);
      </script>
    </head>
    <body>
      <div class="wrap">
        <div class="hero">
          <div class="card">
            <div class="title">KiBot Sovereign Dashboard</div>
            <p class="sub">Delegation-first control room: scanner, council, executor, verifier, janitor, and runtime state in one visual plane.</p>
            <div class="grid">
              <div class="tile"><div class="label">Generated</div><div class="value" id="gen">loading...</div></div>
              <div class="tile"><div class="label">Combined Equity</div><div class="value green" id="equity">loading...</div></div>
              <div class="tile"><div class="label">Daily PnL</div><div class="value" id="pnl">loading...</div></div>
              <div class="tile"><div class="label">Strategy</div><div class="value" id="mode">loading...</div></div>
            </div>
            <div class="grid">
              <div class="tile"><div class="label">Indodax Balance</div><div class="value" id="indodax">loading...</div></div>
              <div class="tile"><div class="label">Polymarket IDR</div><div class="value" id="poly">loading...</div></div>
              <div class="tile"><div class="label">Polymarket USDC</div><div class="value" id="usdc">loading...</div></div>
              <div class="tile"><div class="label">State</div><div class="value" id="runtime">loading...</div><div class="mini" id="strategy-mini">loading...</div></div>
            </div>
            <div class="section">
              <div class="flow-title">
                <h2>Live Flow Canvas</h2>
                <div class="mini">current posture: <span class="green" id="flow-state">loading...</span></div>
              </div>
              <div class="card canvas">
                <div class="canvas-grid"></div>
                <div class="wire" style="left: 180px; top: 126px; width: 165px; transform: rotate(0deg);"></div>
                <div class="wire" style="left: 346px; top: 126px; width: 165px; transform: rotate(0deg);"></div>
                <div class="wire" style="left: 512px; top: 126px; width: 160px; transform: rotate(0deg);"></div>
                <div class="wire" style="left: 678px; top: 126px; width: 160px; transform: rotate(0deg);"></div>

                <div class="node live" style="left: 40px; top: 64px;">
                  <div class="k">Scanner</div><div class="v" id="scanner-status">live</div>
                  <div class="s">Discovers pump continuation, reclaim, pivot, and Polymarket signals.</div>
                </div>
                <div class="node warn" style="left: 232px; top: 64px;">
                  <div class="k">Council</div><div class="v" id="council-status">live</div>
                  <div class="s">What-if + antagonist + possibility mining + deadline pressure.</div>
                </div>
                <div class="node live" style="left: 424px; top: 64px;">
                  <div class="k">Executor</div><div class="v" id="executor-status">live</div>
                  <div class="s">Balance-aware, fee-aware, spread-aware live order gate.</div>
                </div>
                <div class="node live" style="left: 616px; top: 64px;">
                  <div class="k">Verifier</div><div class="v">active</div>
                  <div class="s">Tracks fills, PnL, active trades, and midnight reporting.</div>
                </div>
                <div class="node live" style="left: 808px; top: 64px;">
                  <div class="k">Janitor</div><div class="v" id="janitor-status">live</div>
                  <div class="s">Keeps disk, models, and services healthy.</div>
                </div>
              </div>
            </div>
          </div>
          <div class="card">
            <div class="section">
              <h2>Runtime</h2>
              <div class="pill" id="runtime">loading...</div>
              <div class="pill" id="whatif">loading...</div>
            </div>
            <div class="section">
              <h2>Services</h2>
              <pre id="services">loading...</pre>
            </div>
          </div>
        </div>

        <div class="two section">
          <div class="card">
            <h2>Delegation Flow</h2>
            <table>
              <thead><tr><th>Stage</th><th>Owner</th><th>Job</th></tr></thead>
              <tbody>
                <tr><td>Discovery</td><td>Scanner</td><td>Find signals and stage metadata</td></tr>
                <tr><td>Deliberation</td><td>Council</td><td>What-if, evidence, antagonist, deadline</td></tr>
                <tr><td>Execution</td><td>Executor</td><td>Balance, fee, spread, hard gate</td></tr>
                <tr><td>Verification</td><td>Verifier</td><td>PnL, active trades, escalation</td></tr>
                <tr><td>Maintenance</td><td>Janitor</td><td>Disk, models, service health</td></tr>
              </tbody>
            </table>
          </div>
          <div class="card">
            <h2>Active Trade State</h2>
            <pre id="state">Open /api/summary for JSON state</pre>
          </div>
        </div>

        <div class="card section">
          <h2>Agent Ledger</h2>
          <table>
            <thead><tr><th>Actor</th><th>Status</th><th>Evidence</th><th>Notes</th></tr></thead>
            <tbody>
              <tr><td>Scanner</td><td>Live</td><td>Signals + stage metadata</td><td>Indodax / Polymarket / Universal</td></tr>
              <tr><td>Council</td><td>Live</td><td>What-if + antagonist + possibility</td><td>Decision state visible in runtime</td></tr>
              <tr><td>Executor</td><td>Live</td><td>Balance + fee + spread + confidence</td><td>Real money only behind gate</td></tr>
              <tr><td>Verifier</td><td>Live</td><td>PnL + fills + active trades</td><td>Nightly report and escalation</td></tr>
              <tr><td>Janitor</td><td>Live</td><td>Disk + services + models</td><td>Self-healing maintenance loop</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/api/summary")
async def summary() -> JSONResponse:
    data = _build_summary()
    return JSONResponse(data)
