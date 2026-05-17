/* KiBot Delegation live.js — v5.0 */
"use strict";

const POLL_MS    = 8000;
const STALE_SECS = 300;
const MAX_LOGS   = 80;
const NOISE_RE   = /vault|decrypt|cipher|CEREBRAS_API_KEY|MISTRAL_API_KEY|os\.environ/i;

const idr = v => `Rp ${(+v||0).toLocaleString('id-ID')}`;
const pct = v => `${v>=0?'+':''}${(+v||0).toFixed(2)}%`;
const esc = s => String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
const el  = id => document.getElementById(id);
const setT = (id, v) => { const e = el(id); if (e) e.textContent = v; };

/* ─── Clock ──────────────────────────────────────────────── */
function tickClock() {
  const now = new Date();
  const t = now.toLocaleTimeString('id-ID', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  setT('server-clock', t + ' WIB');
}
setInterval(tickClock, 1000); tickClock();

/* ─── Canvas pan / zoom ──────────────────────────────────── */
const cs = { scale:1, x:0, y:0, dragging:false, lx:0, ly:0 };
const SCALE_MIN=0.4, SCALE_MAX=2.5, SCALE_STEP=0.12;

function applyTransform(smooth=false) {
  const layer = el('delegation-layer');
  if (!layer) return;
  layer.style.transition = smooth ? 'transform .35s cubic-bezier(.25,.8,.25,1)' : 'none';
  layer.style.transform  = `translate(${cs.x}px,${cs.y}px) scale(${cs.scale})`;
}

function fitCanvas() {
  cs.scale=1; cs.x=0; cs.y=0;
  applyTransform(true);
}

function initCanvas() {
  const canvas = el('delegation-canvas');
  if (!canvas) return;

  canvas.addEventListener('pointerdown', e => {
    if (e.target.closest('.agent-card')) return;
    cs.dragging=true; cs.lx=e.clientX; cs.ly=e.clientY;
    canvas.classList.add('is-dragging');
    canvas.setPointerCapture(e.pointerId);
  });

  canvas.addEventListener('pointermove', e => {
    if (!cs.dragging) return;
    cs.x += e.clientX - cs.lx;
    cs.y += e.clientY - cs.ly;
    cs.lx=e.clientX; cs.ly=e.clientY;
    applyTransform();
  });

  const stopDrag = () => { cs.dragging=false; canvas.classList.remove('is-dragging'); };
  canvas.addEventListener('pointerup', stopDrag);
  canvas.addEventListener('pointercancel', stopDrag);

  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    const dir = e.deltaY < 0 ? 1 : -1;
    cs.scale = Math.min(SCALE_MAX, Math.max(SCALE_MIN, cs.scale + dir * SCALE_STEP));
    applyTransform();
  }, {passive:false});

  canvas.addEventListener('dblclick', e => {
    if (e.target.closest('.agent-card')) return;
    fitCanvas();
  });

  el('btn-zoom-in').onclick  = () => { cs.scale = Math.min(SCALE_MAX, cs.scale+SCALE_STEP); applyTransform(true); };
  el('btn-zoom-out').onclick = () => { cs.scale = Math.max(SCALE_MIN, cs.scale-SCALE_STEP); applyTransform(true); };
  el('btn-fit').onclick      = fitCanvas;
}

/* ─── SVG Connectors ─────────────────────────────────────── */
function drawConnectors() {
  const svg = el('connectors');
  if (!svg) return;
  svg.innerHTML = '';

  const EDGES = [
    {from:'card-operator',  to:'card-director',  style:'solid',  color:'#3b82f6'},
    {from:'card-director',  to:'card-scanner',   style:'solid',  color:'#3b82f6'},
    {from:'card-director',  to:'card-risk',      style:'solid',  color:'#3b82f6'},
    {from:'card-director',  to:'card-executor',  style:'solid',  color:'#3b82f6'},
    {from:'card-scanner',   to:'card-leadlag',   style:'dotted', color:'#22c55e'},
    {from:'card-risk',      to:'card-ev',        style:'dotted', color:'#f59e0b'},
    {from:'card-executor',  to:'card-paperpnl',  style:'dotted', color:'#ef4444'},
    {from:'card-leadlag',   to:'card-phantom',   style:'dashed', color:'#a855f7'},
    {from:'card-ev',        to:'card-polymarket',style:'dashed', color:'#f97316'},
    {from:'card-paperpnl',  to:'card-cashwait',  style:'dashed', color:'#64748b'},
  ];

  const layer = el('delegation-layer');
  const layerRect = layer.getBoundingClientRect();

  function midBottom(cardEl) {
    const r = cardEl.getBoundingClientRect();
    return {
      x: r.left + r.width/2  - layerRect.left,
      y: r.bottom            - layerRect.top
    };
  }
  function midTop(cardEl) {
    const r = cardEl.getBoundingClientRect();
    return {
      x: r.left + r.width/2  - layerRect.left,
      y: r.top               - layerRect.top
    };
  }

  EDGES.forEach(({from, to, style, color}) => {
    const a = el(from), b = el(to);
    if (!a || !b) return;
    const p1 = midBottom(a), p2 = midTop(b);
    const my = (p1.y + p2.y) / 2;
    const d  = `M${p1.x},${p1.y} C${p1.x},${my} ${p2.x},${my} ${p2.x},${p2.y}`;
    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d', d);
    path.setAttribute('stroke', color);
    path.setAttribute('stroke-width', '1.5');
    path.setAttribute('fill', 'none');
    path.setAttribute('opacity', '0.55');
    if (style === 'dotted') path.setAttribute('stroke-dasharray','3 4');
    if (style === 'dashed') path.setAttribute('stroke-dasharray','6 5');
    svg.appendChild(path);
  });
}

/* ─── Agent Modal ────────────────────────────────────────── */
const AGENT_META = {
  operator:   { letter:'K', color:'blue',   name:'Kiki / Operator',       role:'Human In The Loop',     desc:'The sovereign operator. Sets policy, approves live gate, monitors all agents. Cannot trade directly.',    inputs:[], outputs:[], stateFile:null },
  director:   { letter:'D', color:'blue',   name:'Autonomous Director',   role:'Lead Agent',            desc:'Orchestrates all subagents. Reads all gate outputs. Issues WAIT, APPROVE, or REJECT decisions. Cannot place orders directly.',  inputs:['signal_quality.json','expected_value.json','strategy_scorecard.json','punishment.json'], outputs:['autonomous_director.json'], stateFile:'autonomous_director.json' },
  scanner:    { letter:'S', color:'green',  name:'Scanner',               role:'Signal Discovery',      desc:'Scans Indodax tickers for momentum, volume anomalies, and cross-asset lead-lag signals. Feeds signal candidates to Director.', inputs:['market_cache.json'], outputs:['scanner_runtime.json'], stateFile:'scanner_runtime.json' },
  leadlag:    { letter:'L', color:'green',  name:'LeadLag Alpha',         role:'Signal Engine',         desc:'Computes lead-lag correlations between BTC/ETH and altcoin pairs to detect early momentum shifts.', inputs:['scanner_runtime.json'], outputs:['signal_quality.json'], stateFile:'signal_quality.json' },
  risk:       { letter:'R', color:'yellow', name:'RiskGate',              role:'Risk Shield',           desc:'Hard enforces 1.5% max daily drawdown. Blocks any order that would breach the daily loss limit.', inputs:['portfolio_summary.json'], outputs:[], stateFile:null },
  ev:         { letter:'V', color:'yellow', name:'Expected Value Gate',   role:'EV Filter',             desc:'Evaluates expected value of each signal. Rejects trades with negative or near-zero EV after fees.', inputs:['signal_quality.json'], outputs:['expected_value.json'], stateFile:'expected_value.json' },
  executor:   { letter:'E', color:'red',    name:'Executor',              role:'Order Placement',       desc:'Places orders on Indodax. Currently PAPER mode — all orders are simulated. Real orders only when live_trading_enabled=true AND canary gate is open.', inputs:['autonomous_director.json','risk_gate.json'], outputs:['paper_trades.json'], stateFile:null },
  paperpnl:   { letter:'P', color:'red',    name:'Paper PnL Tracker',     role:'PnL Accounting',        desc:'Tracks all paper/simulated orders and computes unrealized + realized PnL. Separated from real PnL.', inputs:['paper_trades.json'], outputs:['portfolio_summary.json'], stateFile:'portfolio_summary.json' },
  phantom:    { letter:'Φ', color:'purple', name:'Phantom Scout',         role:'Solana Scout',          desc:'Scouts Solana microstructure opportunities. Simulation only — no real SOL funds connected.', inputs:[], outputs:['phantom_scout.json'], stateFile:'phantom_scout.json' },
  polymarket: { letter:'M', color:'orange', name:'Polymarket Agent',      role:'Prediction Markets',    desc:'Monitors Polymarket prediction markets for arbitrage. Paper mode — no real USDC wallet connected.', inputs:[], outputs:[], stateFile:null },
  cashwait:   { letter:'C', color:'gray',   name:'Cash Wait Reserve',     role:'Idle Capital',          desc:'Tracks cash held idle. Acts as the fallback when all gates reject. Prevents forced trades.', inputs:[], outputs:[], stateFile:null },
};

let _lastData = null;

function openModal(agentId) {
  const meta = AGENT_META[agentId];
  if (!meta) return;
  const modal = el('agent-modal');
  const data  = _lastData || {};
  const fresh = data.freshness || {};
  const gates = data.gates    || {};
  const runtime = data.runtime || {};

  // Resolve live status
  let status = '—', metric = '', decision = meta.desc, stale = false;

  if (agentId === 'director') {
    const d = data.autonomous_director || runtime.autonomous_director || {};
    status = d.status || 'WAIT';
    metric = `${d.approved||0} approved · ${d.rejected||0} rejected`;
    const age = fresh.autonomous_director_age_s;
    if (age > STALE_SECS) stale = true;
    if (d.last_reason) decision = d.last_reason;
  } else if (agentId === 'scanner') {
    const d = runtime.scanner || {};
    status = d.status || '—';
    const age = fresh.scanner_runtime_age_s;
    if (age > STALE_SECS) stale = true;
  } else if (agentId === 'leadlag' || agentId === 'ev') {
    const key = agentId === 'ev' ? 'expected_value' : 'signal_quality';
    const g = gates[key] || {};
    status = g.status || 'WAIT';
    metric = g.score != null ? `score: ${g.score}` : '';
    const age = agentId === 'ev' ? fresh.expected_value_age_s : fresh.signal_quality_age_s;
    if (age > STALE_SECS) stale = true;
    if (g.reason) decision = g.reason;
  } else if (agentId === 'risk') {
    const g = gates.risk_gate || {};
    status = g.status || 'SHIELDED';
    metric = '1.5% daily cap';
    if (g.reason) decision = g.reason;
  } else if (agentId === 'executor') {
    const m = data.mode || {};
    status = m.live_trading_enabled ? 'LIVE' : 'PAPER';
    decision = m.live_trading_enabled
      ? '⚠ Live trading ACTIVE — real orders enabled.'
      : 'Paper mode. All orders simulated. live_trading_enabled=false.';
  }

  const staleHtml = stale
    ? `<div class="modal-stale-notice">⚠ STALE — telemetry older than ${STALE_SECS}s</div>`
    : '';

  const inputsHtml = meta.inputs.length
    ? `<ul class="modal-file-list">${meta.inputs.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>`
    : '<span style="color:#94a3b8;font-size:11px">none</span>';

  const outputsHtml = meta.outputs.length
    ? `<ul class="modal-file-list">${meta.outputs.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>`
    : '<span style="color:#94a3b8;font-size:11px">none</span>';

  el('modal-content').innerHTML = `
    <div class="modal-header">
      <div class="modal-avatar av--${esc(meta.color)}">${esc(meta.letter)}</div>
      <div class="modal-title-block">
        <div class="modal-agent-name">${esc(meta.name)}</div>
        <div class="modal-agent-role">${esc(meta.role)}</div>
      </div>
    </div>
    <div class="modal-body">
      ${staleHtml}
      <div class="modal-section">
        <div class="modal-section-label">Status</div>
        <div class="modal-kv"><span class="k">Status</span><strong>${esc(status)}</strong></div>
        <div class="modal-kv"><span class="k">Mode</span><strong>${esc((data.mode||{}).trading_mode||'PAPER')}</strong></div>
        ${metric ? `<div class="modal-kv"><span class="k">Metric</span><span>${esc(metric)}</span></div>` : ''}
      </div>
      <div class="modal-section">
        <div class="modal-section-label">Latest Decision</div>
        <div class="modal-decision">${esc(decision)}</div>
      </div>
      <div class="modal-section">
        <div class="modal-section-label">Input State Files</div>
        ${inputsHtml}
      </div>
      <div class="modal-section">
        <div class="modal-section-label">Output State Files</div>
        ${outputsHtml}
      </div>
    </div>`;

  modal.classList.remove('hidden');
}

function closeModal() {
  el('agent-modal').classList.add('hidden');
}

function initModal() {
  el('modal-close').onclick    = closeModal;
  el('modal-backdrop').onclick = closeModal;
  document.addEventListener('keydown', e => { if (e.key==='Escape') closeModal(); });
  document.querySelectorAll('.agent-card').forEach(card => {
    card.addEventListener('click', e => {
      if (cs.dragging) return;
      const id = card.dataset.agentId;
      if (id) openModal(id);
    });
  });
}

/* ─── Log feeds ──────────────────────────────────────────── */
let _actLog = [], _techLog = [];

function pushLog(arr, domId, entry) {
  const time  = new Date().toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const tag   = entry.tag || 'INFO';
  const tagCl = {INFO:'info',WARN:'warn',ERROR:'error',SUCCESS:'success'}[tag]||'info';
  const div   = document.createElement('div');
  div.className = 'log-entry';
  div.innerHTML = `<span class="log-time">${time}</span><span class="log-tag log-tag--${tagCl}">${esc(tag)}</span><span class="log-msg">${esc(entry.message||'')}</span>`;
  arr.unshift(div);
  if (arr.length > MAX_LOGS) arr.pop();
  const feed = el(domId);
  if (feed) { feed.innerHTML=''; arr.forEach(d=>feed.appendChild(d)); }
}

function initTabs() {
  document.querySelectorAll('.log-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.log-tab').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.tab;
      el('activity-log').classList.toggle('hidden', tab!=='activity');
      el('technical-log').classList.toggle('hidden', tab!=='technical');
    });
  });
  el('clear-logs-btn').onclick = () => {
    _actLog=[]; _techLog=[];
    el('activity-log').innerHTML='';
    el('technical-log').innerHTML='';
  };
}

/* ─── Queue board ────────────────────────────────────────── */
function renderQueue(data) {
  const mode    = data.mode || {};
  const gates   = data.gates || {};
  const runtime = data.runtime || {};

  const scheduled = [
    {label:'SCANNER', sub:`cycle · ${runtime.scanner?.last_cycle||'NORMAL'}`},
    {label:'HEALTHCHECK', sub:'PASS'},
  ];
  const hold = [];
  ['signal_quality','expected_value','strategy_scorecard'].forEach(k => {
    const g = gates[k] || {};
    if (g.status && g.status!=='PASS') hold.push({label:k.replace('_',' ').toUpperCase(), sub:g.status});
  });
  const progress = [];
  const done = [];
  const dir = data.autonomous_director || {};
  const waits = dir.total_waits ?? (data.recent_decisions||[]).filter(d=>d.decision==='WAIT').length;
  if (waits) done.push({label:'WAITS', sub:`${waits} today`});

  function fillLane(laneId, cntId, items) {
    const lane = el(laneId); const cnt = el(cntId);
    if (!lane) return;
    lane.innerHTML = items.map(i=>`<div class="lane-card"><div class="lane-card-label">${esc(i.label)}</div><div class="lane-card-sub">${esc(i.sub)}</div></div>`).join('');
    if (cnt) cnt.textContent = items.length || '';
  }
  fillLane('cards-scheduled','cnt-scheduled',scheduled);
  fillLane('cards-hold','cnt-hold',hold);
  fillLane('cards-progress','cnt-progress',progress);
  fillLane('cards-done','cnt-done',done);
}

/* ─── PnL helpers ────────────────────────────────────────── */
function setPnl(elId, val) {
  const e = el(elId); if (!e) return;
  const n = +val || 0;
  e.textContent = `${n>=0?'+':''}${idr(Math.abs(n))}`;
  e.className = 'pnl ' + (n>0?'pnl-pos':n<0?'pnl-neg':'');
}

function freshnessLabel(age) {
  if (age == null) return 'WAITING FOR TELEMETRY';
  if (age > STALE_SECS) return `STALE (${Math.round(age)}s)`;
  return `fresh (${Math.round(age)}s)`;
}

/* ─── Render from API data ───────────────────────────────── */
function render(data) {
  _lastData = data;
  const mode  = data.mode  || {};
  const port  = data.portfolio || {};
  const gates = data.gates || {};
  const venues= data.venues || {};
  const fresh = data.freshness || {};
  const rt    = data.runtime || {};
  const dir   = data.autonomous_director || {};

  // Top bar badges
  const modeBadge = el('mode-badge');
  if (modeBadge) {
    modeBadge.textContent = (mode.trading_mode||'PAPER').toUpperCase();
    modeBadge.className = mode.live_trading_enabled ? 'badge badge--red' : 'badge badge--paper';
  }

  const warn = data.warnings||[];
  const gsBadge = el('global-status');
  if (gsBadge) {
    gsBadge.textContent = warn.length ? 'WARNING' : 'GREEN';
    gsBadge.className   = warn.length ? 'badge badge--yellow' : 'badge badge--green';
  }

  // Freshness dot
  const allAges = Object.values(fresh);
  const maxAge  = allAges.length ? Math.max(...allAges) : 0;
  const fdot    = el('freshness-dot');
  if (fdot) fdot.className = 'freshness-dot' + (maxAge>STALE_SECS?' stale':'');

  // Director card
  const dStatus = dir.status || rt.autonomous_director?.status || 'WAIT';
  setT('director-status', dStatus);
  const dApproved = dir.approved ?? 0, dRejected = dir.rejected ?? 1;
  setT('director-metric', `${dApproved} approved · ${dRejected} rejected`);

  // Scanner card
  const sc = rt.scanner || {};
  const scStatus = sc.status || 'ACTIVE';
  const scAge    = fresh.scanner_runtime_age_s;
  setT('scanner-status', scStatus + (scAge>STALE_SECS ? ' ·STALE' : ''));
  setT('scanner-metric', `${sc.candidates||0} candidates`);
  el('card-scanner')?.classList.toggle('is-stale', scAge>STALE_SECS);

  // RiskGate card
  const rg = gates.risk_gate || {};
  setT('risk-status', rg.status||'SHIELDED');
  setT('risk-metric', `${rg.max_drawdown_limit||1.5}% cap`);

  // Executor card
  setT('executor-status', mode.live_trading_enabled ? 'LIVE' : 'PAPER');
  setT('executor-metric', mode.live_trading_enabled ? '⚠ LIVE' : 'live off');

  // LeadLag
  const sq = gates.signal_quality || {};
  const sqAge = fresh.signal_quality_age_s;
  setT('leadlag-status', sq.status||'WAIT');
  el('card-leadlag')?.classList.toggle('is-stale', sqAge>STALE_SECS);

  // EV gate
  const ev = gates.expected_value || {};
  const evAge = fresh.expected_value_age_s;
  setT('ev-status', ev.status||'WAIT');
  el('card-ev')?.classList.toggle('is-stale', evAge>STALE_SECS);

  // Paper PnL
  const mockPnl = port.mock_pnl_idr || 0;
  setT('paperpnl-status', `+Rp ${Math.abs(mockPnl).toLocaleString('id-ID')}`);

  // Phantom
  const ph = venues.phantom || {};
  setT('phantom-metric', `${ph.opportunities||0} opportunities`);

  // Polymarket
  const poly = venues.polymarket || {};
  setT('poly-metric', poly.equity_idr ? idr(poly.equity_idr) : 'sim');

  // Right panel — Portfolio
  setT('pi-equity', idr(port.combined_equity_idr || port.equity_idr || 0));
  setT('pi-cash',   idr(port.idr_cash || 0));
  setT('pi-coin',   idr(port.coin_holdings_idr || 0));
  setPnl('pi-real-pnl',  port.real_pnl_idr   || port.daily_pnl_real_idr || 0);
  setPnl('pi-paper-pnl', port.mock_pnl_idr   || port.daily_pnl_sim_idr  || 0);
  setPnl('pi-sim-pnl',   port.simulated_pnl_idr || 0);

  // Venue equities
  setT('eq-indodax-real',  idr(venues.indodax_real?.equity_idr  || 0));
  setT('eq-indodax-paper', idr(venues.indodax_paper?.equity_idr || 0));
  setT('eq-polymarket',    idr(venues.polymarket?.equity_idr    || 0));

  // Gate stack
  function setGate(key, badgeId, scoreId) {
    const g = gates[key] || {};
    const badge = el(badgeId);
    if (!badge) return;
    badge.textContent = g.status || 'WAIT';
    badge.className   = 'gate-badge' + (g.status==='PASS'?' gate-badge--pass':g.status==='REJECT'?' gate-badge--reject':g.status==='IDLE'?' gate-badge--idle':'');
    if (scoreId) setT(scoreId, g.score!=null ? g.score.toFixed(2) : '—');
  }
  setGate('signal_quality',    'gbadge-signal-quality',  'gscore-signal-quality');
  setGate('expected_value',    'gbadge-expected-value',  'gscore-expected-value');
  setGate('strategy_scorecard','gbadge-scorecard',       'gscore-scorecard');
  setGate('punishment',        'gbadge-punishment',      'gscore-punishment');

  // Runtime section
  const cpu = data.system?.cpu_pct;
  const ram = data.system?.ram_pct;
  setT('sys-cpu', cpu!=null ? `${cpu.toFixed(1)}%` : '—');
  setT('sys-ram', ram!=null ? `${ram.toFixed(1)}%` : '—');
  setT('sys-ollama', rt.ollama?.status || '—');
  setT('sys-tel-age', freshnessLabel(fresh.telemetry_age_s));

  // Last updated
  const ts = new Date(data.timestamp||Date.now());
  setT('last-updated', ts.toLocaleTimeString('id-ID'));

  // Logs — activity
  const events = (data.events || []).filter(e => !NOISE_RE.test(e.message||''));
  if (events.length) {
    events.slice(0,5).reverse().forEach(e => pushLog(_actLog,'activity-log',{message:e.message,tag:e.level==='ERROR'?'ERROR':e.level==='WARNING'?'WARN':'INFO'}));
  } else {
    pushLog(_actLog,'activity-log',{
      message: mode.live_trading_enabled ? '⚠ Live trading ACTIVE' : '✓ Paper soak mode active — live trading OFF',
      tag: mode.live_trading_enabled ? 'WARN' : 'INFO'
    });
  }

  // Logs — technical
  Object.entries(fresh).slice(0,4).forEach(([k,age]) => {
    pushLog(_techLog,'technical-log',{message:`${k}: ${freshnessLabel(age)}`, tag:age>STALE_SECS?'WARN':'INFO'});
  });

  // Queue
  renderQueue(data);

  // Redraw connectors after render
  requestAnimationFrame(drawConnectors);
}

/* ─── Poll loop ──────────────────────────────────────────── */
async function poll() {
  try {
    const r = await fetch('/api/control-plane');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    render(await r.json());
  } catch(err) {
    pushLog(_techLog,'technical-log',{message:`API error: ${err.message}`, tag:'ERROR'});
  }
}

/* ─── Init ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  initCanvas();
  initModal();
  initTabs();
  poll();
  setInterval(poll, POLL_MS);
  window.addEventListener('resize', drawConnectors);
});
