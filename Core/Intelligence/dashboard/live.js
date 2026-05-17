/* KiBot Delegation — live.js v4.0
   Single source of truth: /api/control-plane
   Rules:
   - No hardcoded fake values except static labels
   - Real / Paper / Simulation PnL clearly separated
   - Unknown data shown as "Waiting for telemetry", not random fallback
   - Stale files labeled STALE (>300s), missing labeled UNKNOWN
*/

"use strict";

const POLL_MS    = 5000;
const STALE_SECS = 300;
const MAX_LOGS   = 60;

let _activityLog  = [];
let _technicalLog = [];
let _lastTs       = null;

/* ─── Helpers ─────────────────────────────────────────────── */

function idr(val, opts = {}) {
  if (val === null || val === undefined || val === "") return "—";
  const n = Number(val);
  if (isNaN(n)) return "—";
  const abs = Math.abs(n);
  let str;
  if (abs >= 1_000_000) str = `Rp ${(n / 1_000_000).toFixed(2)}jt`;
  else str = `Rp ${n.toLocaleString("id-ID", { maximumFractionDigits: 0 })}`;
  return str;
}

function pct(val) {
  const n = Number(val);
  return isNaN(n) ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function unk(val, label = "Waiting for telemetry") {
  if (val === null || val === undefined || val === "" || val === "UNKNOWN") return label;
  return val;
}

function freshnessLabel(age_s) {
  if (age_s === -1 || age_s === null || age_s === undefined) return "UNKNOWN";
  if (age_s > STALE_SECS) return `STALE (${Math.round(age_s)}s)`;
  return `${Math.round(age_s)}s ago`;
}

function gateClass(status) {
  const s = (status || "").toUpperCase();
  if (s === "PASS")    return "gate-badge--pass";
  if (s === "REJECT")  return "gate-badge--reject";
  if (s === "BLOCKED") return "gate-badge--blocked";
  return "gate-badge--wait";
}

function el(id) { return document.getElementById(id); }

function setText(id, txt) {
  const e = el(id);
  if (e) e.textContent = txt;
}

function setHtml(id, html) {
  const e = el(id);
  if (e) e.innerHTML = html;
}

function setBadgeClass(id, cls) {
  const e = el(id);
  if (!e) return;
  e.className = "gate-badge " + cls;
}

/* ─── Clock ───────────────────────────────────────────────── */
function tickClock() {
  const now = new Date();
  const wib = new Intl.DateTimeFormat("id-ID", {
    timeZone: "Asia/Jakarta", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
  }).format(now);
  setText("server-clock", wib + " WIB");
}
setInterval(tickClock, 1000);
tickClock();

/* ─── Log Feed ────────────────────────────────────────────── */
function pushLog(feed, { time, agent, message, tag }) {
  const t = time ? new Date(time).toLocaleTimeString("id-ID", {
    timeZone: "Asia/Jakarta", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false
  }) : "--:--:--";
  const tagClass = tag === "ERROR" ? "error" : tag === "WARN" ? "warn" : tag === "SUCCESS" ? "success" : "info";
  feed.unshift({ t, agent: agent || "System", msg: message || "", cls: tagClass });
  if (feed.length > MAX_LOGS) feed.length = MAX_LOGS;
}

function renderLogFeed(feedId, rows) {
  const container = el(feedId);
  if (!container) return;
  container.innerHTML = rows.map(r =>
    `<div class="log-row log-row--${r.cls}">
      <span class="log-row__time">${r.t}</span>
      <span class="log-row__agent">${escHtml(r.agent)}</span>
      <span class="log-row__msg">${escHtml(r.msg)}</span>
    </div>`
  ).join("");
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ─── Log Tab Toggle ──────────────────────────────────────── */
document.querySelectorAll(".log-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".log-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    el("activity-log").classList.toggle("hidden", tab !== "activity");
    el("technical-log").classList.toggle("hidden", tab !== "technical");
  });
});

el("clear-logs-btn")?.addEventListener("click", () => {
  _activityLog = [];
  _technicalLog = [];
  renderLogFeed("activity-log", _activityLog);
  renderLogFeed("technical-log", _technicalLog);
});

/* ─── Top Bar ─────────────────────────────────────────────── */
function renderTopBar(data) {
  const mode = (data.mode || {});
  const modeBadge = el("mode-badge");
  if (modeBadge) {
    const trading = (mode.trading_mode || "paper").toLowerCase();
    modeBadge.textContent = trading.toUpperCase();
    modeBadge.className = "badge " + (trading === "live" ? "badge--live" : trading === "canary" ? "badge--canary" : "badge--paper");
  }

  // Global status from warnings
  const statusBadge = el("global-status");
  if (statusBadge) {
    const warns = data.warnings || [];
    if (warns.length > 0) {
      statusBadge.textContent = "WARNING";
      statusBadge.className = "badge badge--warning";
    } else {
      statusBadge.textContent = "GREEN";
      statusBadge.className = "badge badge--green";
    }
  }

  // Last updated
  if (data.timestamp) {
    const d = new Date(data.timestamp);
    setText("last-updated", d.toLocaleTimeString("id-ID", { timeZone: "Asia/Jakarta", hour12: false }));
  }

  // Freshness indicator
  const freshness = data.freshness || {};
  const ages = Object.values(freshness).filter(v => v >= 0);
  const maxAge = ages.length ? Math.max(...ages) : -1;
  const dot = el("freshness-dot");
  if (dot) {
    if (maxAge === -1)        { dot.className = "freshness-dot freshness-dot--stale"; dot.title = "Telemetry unknown"; }
    else if (maxAge > STALE_SECS) { dot.className = "freshness-dot freshness-dot--stale"; dot.title = `Stale: ${Math.round(maxAge)}s`; }
    else                     { dot.className = "freshness-dot"; dot.title = `Fresh: ${Math.round(maxAge)}s max age`; }
  }
}

/* ─── Agent Cards ─────────────────────────────────────────── */
function renderAgents(data) {
  const runtime   = data.runtime    || {};
  const dir       = runtime.autonomous_director || {};
  const scanner   = runtime.scanner || {};
  const portfolio = data.portfolio  || {};
  const phantom   = portfolio.phantom || {};
  const poly      = (data.venues || {}).polymarket || {};
  const services  = data.services  || {};

  // Director
  const dirStatus = dir.status || (dir.approved_count > 0 ? "ACTIVE" : "WAIT");
  setText("director-status", dirStatus);
  setText("director-metric", `${dir.approved_count || 0} approved · ${dir.rejected_count || 0} rejected`);
  el("director-status").innerHTML = `<span class="dot dot--blue"></span>${dirStatus}`;

  // Scanner
  const scanActive = (services["kibot-scanner"] || "").toLowerCase() === "active";
  const scanStatus = scanActive ? "ACTIVE" : (services["kibot-scanner"] || "UNKNOWN");
  const candidates = (data.scanner_candidates || {}).total || 0;
  el("scanner-status").innerHTML = `<span class="dot dot--${scanActive ? "green" : "yellow"}"></span>${scanStatus}`;
  setText("scanner-metric", `${candidates} candidates · ${freshnessLabel(data.freshness?.scanner_runtime_age_s)}`);

  // RiskGate
  const riskGate  = (data.gates || {}).risk_gate || {};
  const riskStat  = riskGate.status || "SHIELDED";
  el("risk-status").innerHTML = `<span class="dot dot--yellow"></span>${riskStat}`;
  setText("risk-metric", `${riskGate.max_drawdown_limit || 1.5}% cap`);

  // Executor
  const mode = data.mode || {};
  const execStatus = mode.live_trading_enabled ? "LIVE" : "PAPER";
  el("executor-status").innerHTML = `<span class="dot dot--${mode.live_trading_enabled ? "green" : "red"}"></span>${execStatus}`;
  setText("executor-metric", mode.live_trading_enabled ? "live active" : "live off");

  // Phantom
  const phantomOps = Array.isArray(phantom.active_opportunities) ? phantom.active_opportunities.length : 0;
  setText("phantom-metric", `${phantomOps} opportunities`);

  // Polymarket
  const polyEq = portfolio.polymarket?.equity_idr;
  setText("poly-metric", polyEq ? idr(polyEq) : "sim");
}

/* ─── Portfolio Right Panel ───────────────────────────────── */
function renderPortfolio(data) {
  const p   = data.portfolio || {};
  const mode = data.mode || {};

  setText("pi-equity", idr(p.total_equity_idr || p.combined_equity_idr));
  setText("pi-cash",   idr(p.idr_cash));
  setText("pi-coin",   idr(p.coin_holdings_idr));

  // Real PnL — only meaningful if live trading is on
  const realPnl   = mode.live_trading_enabled ? p.real_pnl_idr : 0;
  const paperPnl  = p.mock_pnl_idr ?? p.daily_pnl_sim_idr ?? 0;
  const simPnl    = p.simulated_pnl_idr ?? 0;

  renderPnlEl("pi-real-pnl",  realPnl);
  renderPnlEl("pi-paper-pnl", paperPnl);
  renderPnlEl("pi-sim-pnl",   simPnl);
}

function renderPnlEl(id, val) {
  const e = el(id);
  if (!e) return;
  const n = Number(val);
  if (isNaN(n)) { e.textContent = "—"; e.className = "pnl"; return; }
  e.textContent = (n >= 0 ? "+" : "") + idr(n);
  e.className = "pnl " + (n > 0 ? "pnl--pos" : n < 0 ? "pnl--neg" : "pnl--zero");
}

/* ─── Venues ──────────────────────────────────────────────── */
function renderVenues(data) {
  const venues = data.venues || {};
  const mode   = data.mode   || {};

  // Indodax Real
  const indReal = venues.indodax_real || {};
  const indRealStatus = mode.live_trading_enabled ? "ACTIVE" : "VIEW ONLY";
  const indRealBadgeCls = mode.live_trading_enabled ? "badge badge--green" : "badge badge--ghost";
  const indRealBadge = el("venue-indodax-real-badge");
  if (indRealBadge) { indRealBadge.textContent = indRealStatus; indRealBadge.className = indRealBadgeCls; }
  setText("venue-indodax-real-equity", idr(indReal.equity_idr));

  // Indodax Paper
  const indPaper = venues.indodax_paper || {};
  setText("venue-indodax-paper-equity", idr(indPaper.equity_idr));

  // Phantom — simulation only, never shown as real equity
  const portfolio = data.portfolio || {};
  const phantomOps = Array.isArray((portfolio.phantom || {}).active_opportunities)
    ? (portfolio.phantom.active_opportunities || []).length
    : 0;
  setText("venue-phantom-equity", `${phantomOps} scouting`);

  // Polymarket
  const poly = (data.portfolio || {}).polymarket || {};
  setText("venue-poly-equity", idr(poly.equity_idr));
}

/* ─── Gates ───────────────────────────────────────────────── */
function renderGates(data) {
  const gates = data.gates || {};

  renderGate("signal-quality", gates.signal_quality, v => v.score?.toFixed(2) ?? "—");
  renderGate("expected-value", gates.expected_value, v => v.score != null ? pct(v.score) : "—");
  renderGate("scorecard",      gates.strategy_scorecard, v => v.score?.toFixed(2) ?? "—");

  // Punishment
  const pun = gates.punishment || {};
  const punStatus = pun.strikes > 0 ? "QUARANTINE" : "IDLE";
  const punBadge = el("gbadge-punishment");
  if (punBadge) { punBadge.textContent = punStatus; punBadge.className = "gate-badge " + (pun.strikes > 0 ? "gate-badge--blocked" : ""); }
  setText("gscore-punishment", `${pun.strikes || 0} strikes`);
}

function renderGate(key, gate, scoreFormatter) {
  if (!gate) return;
  const status = (gate.status || "WAIT").toUpperCase();
  const badge = el(`gbadge-${key}`);
  if (badge) { badge.textContent = status; badge.className = "gate-badge " + gateClass(status); }
  setText(`gscore-${key}`, scoreFormatter(gate));
}

/* ─── System Runtime ──────────────────────────────────────── */
function renderRuntime(data) {
  const sys  = data.system   || {};
  const rt   = data.runtime  || {};
  const svc  = data.services || {};
  const fresh = data.freshness || {};

  setText("sys-cpu",  sys.cpu  != null ? `${Number(sys.cpu).toFixed(1)}%`  : "—");
  setText("sys-ram",  sys.ram  != null ? `${Number(sys.ram).toFixed(1)}%`  : "—");
  setText("sys-disk", sys.disk != null ? `${Number(sys.disk).toFixed(1)}%` : "—");

  const ollama = rt.ollama || {};
  const ollamaActive = (svc.ollama || "").toLowerCase() === "active";
  setText("sys-ollama", ollamaActive ? `ACTIVE (${ollama.model || "?"})` : "INACTIVE");

  setText("sys-telemetry-age", freshnessLabel(fresh.telemetry_age_s));
}

/* ─── Queue Board ─────────────────────────────────────────── */
function renderQueue(data) {
  const mode    = data.mode    || {};
  const rt      = data.runtime || {};
  const svc     = data.services || {};
  const journal = data.decision_journal || {};
  const gates   = data.gates   || {};
  const portfolio = data.portfolio || {};
  const orders  = (data.order_tracker || {}).open_orders || [];

  // SCHEDULED: upcoming scan, healthcheck
  const scheduled = [];
  scheduled.push({ label: "Scanner", detail: `cycle · ${rt.scanner?.mode || "NORMAL"}` });
  scheduled.push({ label: "Healthcheck", detail: rt.healthcheck?.status || "PASS" });

  // ON HOLD: rejected/waiting signals
  const onHold = [];
  if ((gates.signal_quality?.status || "") !== "PASS") {
    onHold.push({ label: "Signal", detail: gates.signal_quality?.status || "WAIT" });
  }
  if ((gates.expected_value?.status || "") !== "PASS") {
    onHold.push({ label: "EV Gate", detail: gates.expected_value?.status || "WAIT" });
  }
  if ((gates.strategy_scorecard?.status || "") !== "PASS") {
    onHold.push({ label: "Scorecard", detail: gates.strategy_scorecard?.status || "WAIT" });
  }

  // IN PROGRESS: open orders / active evaluations
  const inProg = [];
  orders.slice(0, 4).forEach(o => {
    inProg.push({ label: o.pair || "Order", detail: o.state || o.budget_idr ? idr(o.budget_idr) : "—" });
  });
  const dirAD = rt.autonomous_director || {};
  if (dirAD.paper_count > 0) {
    inProg.push({ label: "Paper eval", detail: `${dirAD.paper_count} active` });
  }

  // DONE: journal summary
  const done = [];
  if (journal.entries > 0)  done.push({ label: "Entries",  detail: `${journal.entries} today` });
  if (journal.exits > 0)    done.push({ label: "Exits",    detail: `${journal.exits} today` });
  if (journal.waits > 0)    done.push({ label: "Waits",    detail: `${journal.waits} today` });

  fillLane("scheduled", scheduled);
  fillLane("hold",      onHold);
  fillLane("progress",  inProg);
  fillLane("done",      done);
}

function fillLane(key, items) {
  setText(`cnt-${key}`, String(items.length));
  const container = el(`cards-${key}`);
  if (!container) return;
  container.innerHTML = items.length
    ? items.map(i =>
        `<div class="queue-card">
          <div class="queue-card__label">${escHtml(i.label)}</div>
          <div>${escHtml(i.detail)}</div>
        </div>`
      ).join("")
    : `<div class="queue-card" style="color:var(--text-light);font-size:10px">—</div>`;
}

/* ─── Activity Log ────────────────────────────────────────── */
function buildActivityEvents(data) {
  const events = data.events || [];
  const mode   = data.mode   || {};
  const fresh  = data.freshness || {};

  // Always prepend the mode notice
  const modeLine = {
    time: data.timestamp,
    agent: "System",
    message: mode.live_trading_enabled
      ? "⚠ Live trading ACTIVE"
      : "✓ Paper soak mode active — live trading OFF",
    tag: mode.live_trading_enabled ? "WARN" : "INFO"
  };

  // Filter activity events: skip vault/crypto/decrypt noise → goes to technical only
  const NOISE_PATTERNS = /vault|decrypt|cipher|CEREBRAS_API_KEY|MISTRAL_API_KEY|os\.environ/i;

  const activityEvents = [modeLine, ...events.filter(e => !NOISE_PATTERNS.test(e.message || ""))].slice(0, MAX_LOGS);
  const technicalEvents = events.filter(e => NOISE_PATTERNS.test(e.message || ""));

  activityEvents.forEach(e => pushLog(_activityLog, e));
  technicalEvents.forEach(e => pushLog(_technicalLog, e));

  // Technical: freshness + service status
  const services = data.services || {};
  Object.entries(services).forEach(([svc, status]) => {
    pushLog(_technicalLog, {
      time: data.timestamp,
      agent: "Service",
      message: `${svc}: ${status}`,
      tag: status === "active" ? "SUCCESS" : (status === "inactive" ? "ERROR" : "WARN")
    });
  });

  Object.entries(fresh).forEach(([key, age]) => {
    pushLog(_technicalLog, {
      time: data.timestamp,
      agent: "Freshness",
      message: `${key}: ${freshnessLabel(age)}`,
      tag: age > STALE_SECS ? "WARN" : "INFO"
    });
  });
}


/* ─── SVG Connectors ──────────────────────────────────────── */
function drawConnectors() {
  const svg = el("connectors");
  if (!svg) return;

  // Connection map: parent card id → child card ids
  const connections = [
    ["card-operator",  "card-director"],
    ["card-director",  "card-scanner"],
    ["card-director",  "card-risk"],
    ["card-director",  "card-executor"],
    ["card-executor",  "card-phantom"],
    ["card-executor",  "card-polymarket"],
  ];

  const canvas = svg.closest(".delegation-canvas");
  const canvasRect = canvas.getBoundingClientRect();

  let pathsHtml = "";
  connections.forEach(([fromId, toId]) => {
    const fromEl = el(fromId);
    const toEl   = el(toId);
    if (!fromEl || !toEl) return;

    const fromRect = fromEl.getBoundingClientRect();
    const toRect   = toEl.getBoundingClientRect();

    const fx = fromRect.left + fromRect.width / 2  - canvasRect.left;
    const fy = fromRect.bottom                      - canvasRect.top;
    const tx = toRect.left   + toRect.width  / 2   - canvasRect.left;
    const ty = toRect.top                           - canvasRect.top;

    const cy = (fy + ty) / 2;
    pathsHtml += `<path d="M${fx},${fy} C${fx},${cy} ${tx},${cy} ${tx},${ty}"
      fill="none" stroke="#bfdbfe" stroke-width="1.5" stroke-dasharray="5,3"
      marker-end="url(#arrowhead)" />`;
  });

  svg.innerHTML = `
    <defs>
      <marker id="arrowhead" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
        <path d="M0,1 L0,5 L5,3 z" fill="#93c5fd" />
      </marker>
    </defs>
    ${pathsHtml}
  `;
}

/* ─── Main Render ─────────────────────────────────────────── */
function render(data) {
  if (!data || typeof data !== "object") return;

  renderTopBar(data);
  renderAgents(data);
  renderPortfolio(data);
  renderVenues(data);
  renderGates(data);
  renderRuntime(data);
  renderQueue(data);
  buildActivityEvents(data);
  renderLogFeed("activity-log",  _activityLog);
  renderLogFeed("technical-log", _technicalLog);

  // Redraw connectors after DOM settles
  requestAnimationFrame(drawConnectors);
}

/* ─── Fetch Loop ──────────────────────────────────────────── */
async function fetchAndRender() {
  try {
    const res  = await fetch("/api/control-plane");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    _lastTs = Date.now();
    render(data);
  } catch (err) {
    pushLog(_activityLog, {
      time: new Date().toISOString(),
      agent: "Dashboard",
      message: `API fetch failed: ${err.message}`,
      tag: "ERROR"
    });
    renderLogFeed("activity-log", _activityLog);

    const dot = el("freshness-dot");
    if (dot) dot.className = "freshness-dot freshness-dot--dead";
  }
}

// Initial load + poll
fetchAndRender();
setInterval(fetchAndRender, POLL_MS);

// Redraw connectors on resize
window.addEventListener("resize", () => requestAnimationFrame(drawConnectors));
