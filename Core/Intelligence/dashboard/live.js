/* KiBot Delegation live.js — v5.0 */
"use strict";

const POLL_MS    = 8000;
const STALE_SECS = 300;
const MAX_LOGS   = 80;
const NOISE_RE   = /vault|decrypt|cipher|CEREBRAS_API_KEY|MISTRAL_API_KEY|os\.environ/i;

const idr = v => `Rp ${(+v||0).toLocaleString('id-ID')}`;
const pct = v => `${v>=0?'+':''}${(+v||0).toFixed(2)}%`;
const esc = s => String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
const shortAddr = addr => {
  const s = String(addr ?? '').trim();
  if (!s) return '—';
  return s.length > 12 ? `${s.slice(0, 6)}…${s.slice(-4)}` : s;
};
const el  = id => document.getElementById(id);
const setT = (id, v) => { const e = el(id); if (e) e.textContent = v; };
const getCount = (val) => Array.isArray(val) ? val.length : (typeof val === 'object' && val !== null ? Object.keys(val).length : (val ?? 0));

/* ─── Clock ──────────────────────────────────────────────── */
function tickClock() {
  const now = new Date();
  const t = now.toLocaleTimeString('id-ID', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  setT('server-clock', t + ' WIB');
}
setInterval(tickClock, 1000); tickClock();

/* ─── Canvas pan / zoom ──────────────────────────────────── */
const cs = { scale:1, x:0, y:0, dragging:false, lx:0, ly:0 };
window.KiBotLive = {
  cs,
  fmtRp: idr,
  isDragging() { return cs.dragging; }
};
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
    cs.x += (e.clientX - cs.lx) * 0.55;
    cs.y += (e.clientY - cs.ly) * 0.55;
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
    {from:'card-scanner',   to:'card-leadlag',   style:'dotted', color:'#22c55e'},
    {from:'card-leadlag',   to:'card-ev',        style:'dotted', color:'#22c55e'},
    {from:'card-ev',        to:'card-scorecard', style:'dotted', color:'#eab308'},
    {from:'card-scorecard', to:'card-council',   style:'dashed', color:'#a855f7', dir:'upstream-right'},
    {from:'card-operator',  to:'card-director',  style:'solid',  color:'#3b82f6'},
    {from:'card-council',   to:'card-director',  style:'solid',  color:'#a855f7'},
    {from:'card-director',  to:'card-risk',      style:'solid',  color:'#3b82f6'},
    {from:'card-director',  to:'card-indodax-real',  style:'solid',  color:'#ef4444'},
    {from:'card-director',  to:'card-indodax-shadow', style:'solid',  color:'#64748b'},
    {from:'card-risk',      to:'card-phantom',   style:'dashed', color:'#a855f7'},
    {from:'card-risk',      to:'card-polymarket',style:'dashed', color:'#f97316'},
    {from:'card-indodax-real', to:'card-pnl-feedback', style:'dotted', color:'#ef4444'},
    {from:'card-indodax-shadow',to:'card-pnl-feedback', style:'dotted', color:'#64748b'},
    {from:'card-phantom',    to:'card-cashwait',  style:'dashed', color:'#a855f7'},
    {from:'card-polymarket', to:'card-cashwait',  style:'dashed', color:'#f97316'},
    {from:'card-pnl-feedback', to:'card-punishment', style:'dotted', color:'#22c55e'},
    {from:'card-punishment', to:'card-risk',      style:'dashed', color:'#ef4444', dir:'upstream-right'},
  ];

  const layer = el('delegation-layer');
  const layerRect = layer.getBoundingClientRect();

  function getPorts(cardEl) {
    const r = cardEl.getBoundingClientRect();
    const x = (r.left - layerRect.left) / cs.scale;
    const y = (r.top - layerRect.top) / cs.scale;
    const w = r.width / cs.scale;
    const h = r.height / cs.scale;
    return {
      midLeft:   { x: x,         y: y + h/2 },
      midRight:  { x: x + w,     y: y + h/2 },
      midTop:    { x: x + w/2,   y: y },
      midBottom: { x: x + w/2,   y: y + h }
    };
  }

  EDGES.forEach(({from, to, style, color, dir}) => {
    const a = el(from), b = el(to);
    if (!a || !b) return;

    const portsA = getPorts(a);
    const portsB = getPorts(b);

    const rA = a.getBoundingClientRect();
    const rB = b.getBoundingClientRect();

    let p1, p2, d;

    const yDiff = rB.top - rA.top;
    const isSameRow = Math.abs(yDiff) < 50;

    if (dir === 'upstream-right') {
      p1 = portsA.midRight;
      p2 = portsB.midRight;
      const offset = (from === 'card-punishment') ? 140 : 80;
      d = `M${p1.x},${p1.y} C${p1.x + offset},${p1.y - offset/2} ${p2.x + offset},${p2.y + offset/2} ${p2.x},${p2.y}`;
    } else if (isSameRow) {
      if (rA.left < rB.left) {
        p1 = portsA.midRight;
        p2 = portsB.midLeft;
      } else {
        p1 = portsA.midLeft;
        p2 = portsB.midRight;
      }
      const mx = (p1.x + p2.x) / 2;
      d = `M${p1.x},${p1.y} C${mx},${p1.y} ${mx},${p2.y} ${p2.x},${p2.y}`;
    } else {
      if (rA.top < rB.top) {
        p1 = portsA.midBottom;
        p2 = portsB.midTop;
      } else {
        p1 = portsA.midTop;
        p2 = portsB.midBottom;
      }
      const my = (p1.y + p2.y) / 2;
      d = `M${p1.x},${p1.y} C${p1.x},${my} ${p2.x},${my} ${p2.x},${p2.y}`;
    }

    const path = document.createElementNS('http://www.w3.org/2000/svg','path');
    path.setAttribute('d', d);
    path.setAttribute('stroke', color);
    path.setAttribute('stroke-width', '2');
    path.setAttribute('fill', 'none');
    path.setAttribute('opacity', '0.75');
    if (style === 'dotted') path.setAttribute('stroke-dasharray','3 4');
    if (style === 'dashed') path.setAttribute('stroke-dasharray','6 5');
    svg.appendChild(path);
  });
}

/* ─── Agent Modal ────────────────────────────────────────── */
const AGENT_META = {
  operator:   { letter:'K', color:'blue',   name:'Kiki / Operator',       role:'Human In The Loop',     row: 1, isSm: false, desc:'The sovereign operator. Sets policy, approves live gate, monitors all agents. Controlled-live mode active on Batam node.', inputs:[], outputs:[], stateFile:null },
  council:    { letter:'Ω', color:'purple', name:'Sovereign Council',     role:'Governance Gate',       row: 1, isSm: false, desc:'High-level deliberation chamber. Aggregates and debates predictions, scanner data, and sentiment before approving order execution.', inputs:['strategy_scorecard.json', 'expected_value.json'], outputs:['council_decisions.jsonl'], stateFile:'council_decisions.jsonl' },
  director:   { letter:'D', color:'blue',   name:'Autonomous Director',   role:'Lead Coordinator',      row: 2, isSm: false, desc:'Core state orchestrator. Reads signal qualities and EV gates. Issues WAIT, APPROVE, or REJECT decisions based on rules.',  inputs:['signal_quality.json','expected_value.json','strategy_scorecard.json','punishment_state.json'], outputs:['autonomous_director.json'], stateFile:'autonomous_director.json' },
  risk:       { letter:'R', color:'red',    name:'RiskGate Shield',       role:'Drawdown Shield',       row: 2, isSm: false, desc:'Safety gate enforcing 1.5% maximum daily drawdown. Blocks all downstream order execution if drawdown is breached.', inputs:['portfolio_summary.json'], outputs:[], stateFile:'portfolio_summary.json' },
  scanner:    { letter:'S', color:'green',  name:'Scanner',               role:'Signal Discovery',      row: 3, isSm: true,  desc:'Scans Indodax orderbooks and tickers for momentum and cross-asset lead-lag anomalies. Sends candidates to LeadLag engine.', inputs:['market_cache.json'], outputs:['scanner_runtime.json'], stateFile:'scanner_runtime.json' },
  leadlag:    { letter:'L', color:'green',  name:'LeadLag Alpha',         role:'Correlation Engine',    row: 3, isSm: true,  desc:'Computes high-speed lead-lag correlations between major assets (BTC/ETH) and altcoins to detect leading momentum.', inputs:['scanner_runtime.json'], outputs:['leadlag_alpha.json', 'signal_quality.json'], stateFile:'signal_quality.json' },
  ev:         { letter:'V', color:'yellow', name:'Expected Value Gate',   role:'EV Threshold Gate',     row: 3, isSm: true,  desc:'Evaluates candidate trades based on expected value (EV) after fees. Blocks execution if EV is negative or below threshold.', inputs:['signal_quality.json'], outputs:['expected_value.json'], stateFile:'expected_value.json' },
  scorecard:  { letter:'C', color:'purple', name:'Strategy Scorecard',     role:'Deliberation Score',    row: 3, isSm: true,  desc:'Grades strategies against current market regimes and recent trade outcomes. Submits composite scorecard to Council.', inputs:['signal_quality.json', 'expected_value.json'], outputs:['strategy_scorecard.json'], stateFile:'strategy_scorecard.json' },
  indodax_real: { letter:'IR', color:'red',  name:'Indodax Spot',         role:'Live Spot Venue',       row: 4, isSm: true,  desc:'Controlled-live exchange order placement with RiskGate and Capital Governor enforcement.', inputs:['autonomous_director.json'], outputs:['live_trades.json'], stateFile:null },
  indodax_shadow: { letter:'IS', color:'gray', name:'Indodax Shadow',       role:'Shadow Ledger',         row: 4, isSm: true,  desc:'Shadow accounting for internal analysis only.', inputs:['autonomous_director.json'], outputs:['shadow_trades.json'], stateFile:'portfolio_summary.json' },
  phantom:    { letter:'Φ', color:'purple', name:'Phantom Treasury',      role:'Solana / Web3 Capital',  row: 4, isSm: true,  desc:'Treasury and route visibility for Phantom multichain capital.', inputs:[], outputs:['phantom_scout.json'], stateFile:'phantom_scout.json' },
  polymarket: { letter:'M', color:'orange', name:'Polymarket',           role:'Prediction Market',     row: 4, isSm: true,  desc:'Prediction market control with guarded settlement-aware lifecycle.', inputs:[], outputs:['polymarket_state.json'], stateFile:'polymarket_state.json' },
  pnl_feedback: { letter:'F', color:'green', name:'PnL Feedback',          role:'Adaptive Learning',     row: 5, isSm: true,  desc:'Post-trade feedback analyzer. Reviews execution quality and adjusts expected value coefficients.', inputs:['shadow_trades.json', 'live_trades.json'], outputs:['pnl_feedback.json'], stateFile:null },
  cashwait:   { letter:'W', color:'gray',   name:'Cash Wait Reserve',     role:'Idle Capital',          row: 5, isSm: true,  desc:'Liquidity reservoir tracking idle assets waiting for high-conviction opportunities. Prevents over-trading.', inputs:[], outputs:[], stateFile:'market_rotation.json' },
  punishment: { letter:'P', color:'red',    name:'Punishment Gate',       role:'Strike Guard',          row: 5, isSm: true,  desc:'Monitors execution failures and consecutive losses. Imposes cooling-off periods and quarantines underperforming pathways.', inputs:['pnl_feedback.json'], outputs:['punishment_state.json'], stateFile:'punishment_state.json' },
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

  if (agentId === 'operator') {
    status = data.mode?.live_trading_enabled ? 'CONTROLLED-LIVE' : 'BLOCKED';
    metric = data.mode?.live_trading_enabled ? 'live active' : 'orders blocked';
  } else if (agentId === 'council') {
    const c = data.council || {};
    status = c.decision_state || 'IDLE';
    metric = c.confidence != null ? `conf ${c.confidence}` : 'conf 0.00';
    if (c.last_decision) decision = `Last Governance Proposal: ${c.last_decision}`;
  } else if (agentId === 'director') {
    const d = data.autonomous_director || runtime.autonomous_director || {};
    status = d.status || 'WAIT';
    const rtD = data.runtime?.autonomous_director || {};
    const dApproved = rtD.approved_count ?? getCount(d.approved);
    const dRejected = rtD.rejected_count ?? getCount(d.rejected);
    metric = `${dApproved} approved · ${dRejected} rejected`;
    const age = fresh.autonomous_director_age_s;
    if (age > STALE_SECS) stale = true;
    if (d.last_reason) decision = d.last_reason;
  } else if (agentId === 'scanner') {
    const d = runtime.scanner || {};
    status = d.status || 'ACTIVE';
    metric = `${d.candidates || 0} candidates`;
    const age = fresh.scanner_runtime_age_s;
    if (age > STALE_SECS) stale = true;
  } else if (agentId === 'leadlag') {
    const g = gates.signal_quality || {};
    status = g.status || 'ACTIVE';
    metric = g.score != null ? `score: ${g.score}` : '';
    const age = fresh.signal_quality_age_s;
    if (age > STALE_SECS) stale = true;
    if (g.reason) decision = g.reason;
  } else if (agentId === 'ev') {
    const g = gates.expected_value || {};
    status = g.status || 'WAIT';
    metric = g.score != null ? `${g.score} EV` : '';
    const age = fresh.expected_value_age_s;
    if (age > STALE_SECS) stale = true;
    if (g.reason) decision = g.reason;
  } else if (agentId === 'scorecard') {
    const g = gates.strategy_scorecard || {};
    status = g.status || 'IDLE';
    metric = g.score != null ? `score: ${g.score}` : '';
    const age = fresh.strategy_scorecard_age_s;
    if (age > STALE_SECS) stale = true;
    if (g.reason) decision = g.reason;
  } else if (agentId === 'risk') {
    const g = gates.risk_gate || {};
    status = g.status || 'SHIELDED';
    metric = '1.5% daily cap';
    if (g.reason) decision = g.reason;
  } else if (agentId === 'indodax_real') {
    status = data.mode?.live_trading_enabled ? 'LIVE' : 'MUTED';
    metric = data.mode?.live_trading_enabled ? 'live active' : 'live off';
    decision = data.mode?.live_trading_enabled
      ? '⚠ Live trading ACTIVE — real orders enabled.'
      : 'Real exchange orders muted. live_trading_enabled=false.';
  } else if (agentId === 'indodax_shadow') {
    status = 'SHADOW';
    metric = 'active';
    decision = 'Shadow ledger only. Production route text intentionally hidden from the live dashboard.';
  } else if (agentId === 'phantom') {
    const d = runtime.phantom_scout || {};
    status = d.status || 'SCOUTING_ONLY';
    metric = 'live route';
    const age = fresh.phantom_scout_age_s;
    if (age > STALE_SECS) stale = true;
  } else if (agentId === 'polymarket') {
    const d = runtime.polymarket_state || {};
    status = d.status || 'SCOUTING_ONLY';
    metric = 'live route';
    const age = fresh.polymarket_state_age_s;
    if (age > STALE_SECS) stale = true;
  } else if (agentId === 'pnl_feedback') {
    status = 'TRACKING';
    metric = 'active';
  } else if (agentId === 'cashwait') {
    status = 'ACTIVE';
    metric = 'Rp ' + ((data.portfolio?.cash_wait?.equity_idr || 0) / 1e6).toFixed(1) + 'M';
  } else if (agentId === 'punishment') {
    const g = gates.punishment || {};
    status = `${g.strikes || 0} STRIKES`;
    metric = g.cooloff || 'active';
    if (g.reason) decision = g.reason;
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
        <div class="modal-kv"><span class="k">Mode</span><strong>${esc((data.mode||{}).trading_mode||'CONTROLLED-LIVE')}</strong></div>
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

  const layer = el('delegation-layer');
  if (layer) {
    layer.addEventListener('click', e => {
      if (cs.dragging) return;
      const card = e.target.closest('.agent-card');
      if (!card) return;
      const id = card.dataset.agentId;
      if (id) openModal(id);
    });
  }
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

function setPct(elId, val) {
  const e = el(elId); if (!e) return;
  const n = +val || 0;
  e.textContent = `${n>=0?'+':''}${n.toFixed(2)}%`;
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
  const ai = data.ai || {};
  const sizing = data.autonomous_sizing || {};
  const brain = data.autonomous_trading_brain || {};
  const indoBrain = data.indodax_live_brain || {};
  const phBrain = data.phantom_live_brain || {};

  // Top bar badges
  const modeBadge = el('mode-badge');
  if (modeBadge) {
    modeBadge.textContent = (mode.trading_mode||'controlled-live').toUpperCase();
    modeBadge.className = mode.live_trading_enabled ? 'badge badge--green' : 'badge badge--red';
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
  const dApproved = getCount(dir.approved);
  const dRejected = getCount(dir.rejected);
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

  // Indodax Executor card
  setT('indodax-status', indoBrain.status || (mode.live_trading_enabled ? 'LIVE' : 'BLOCKED'));
  setT('indodax-metric', indoBrain.decision || (mode.live_trading_enabled ? '⚠ LIVE' : 'orders blocked'));
  if (indoBrain.recovery_mode) {
    setT('indodax-metric', `${indoBrain.decision || 'SCAN_NEXT'} · RECOVERY`);
    const indodaxStatus = el('indodax-status');
    if (indodaxStatus) indodaxStatus.textContent = `${indoBrain.status || 'ACTIVE'} · RECOVERY`;
  }

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

  // Risk remaining
  const riskRemaining = data.capital?.risk_remaining_idr || 0;
  setT('risk-remaining-status', `Rp ${Math.abs(riskRemaining).toLocaleString('id-ID')}`);

  // Phantom
  const ph = venues.phantom || {};
  setT('phantom-metric', phBrain.decision || `${ph.opportunities||0} opportunities`);
  if (phBrain.recovery_mode) {
    setT('phantom-metric', `${phBrain.decision || 'SCAN_NEXT'} · RECOVERY`);
    const phantomStatus = el('phantom-status');
    if (phantomStatus) phantomStatus.textContent = `${phBrain.status || 'ACTIVE'} · RECOVERY`;
  }

  // Polymarket
  const poly = venues.polymarket || {};
  setT('poly-metric', poly.equity_idr ? idr(poly.equity_idr) : 'live route');

  // Safety Gates Badges (Dynamic)
  const liveEnabled = Boolean(mode.live_trading_enabled ?? data.mode?.live_trading_enabled ?? rt.mode?.live_trading_enabled ?? false);
  const gateLive = el('gate-live-trading');
  if (gateLive) {
    gateLive.textContent = liveEnabled ? 'ON' : 'OFF';
    gateLive.className = 'badge ' + (liveEnabled ? 'badge--red' : 'badge--ghost');
  }
  const gateBridge = el('gate-bridge');
  if (gateBridge) {
    gateBridge.textContent = Boolean(mode.real_bridge_enabled ?? data.mode?.real_bridge_enabled ?? false) ? 'ON' : 'OFF';
    gateBridge.className = 'badge ' + (Boolean(mode.real_bridge_enabled ?? data.mode?.real_bridge_enabled ?? false) ? 'badge--red' : 'badge--ghost');
  }
  const gateSwap = el('gate-swap');
  if (gateSwap) {
    gateSwap.textContent = Boolean(mode.real_swap_enabled ?? data.mode?.real_swap_enabled ?? false) ? 'ON' : 'OFF';
    gateSwap.className = 'badge ' + (Boolean(mode.real_swap_enabled ?? data.mode?.real_swap_enabled ?? false) ? 'badge--red' : 'badge--ghost');
  }
  const gateWithdrawal = el('gate-withdrawal');
  if (gateWithdrawal) {
    gateWithdrawal.textContent = Boolean(mode.real_withdrawal_enabled ?? data.mode?.real_withdrawal_enabled ?? false) ? 'ON' : 'OFF';
    gateWithdrawal.className = 'badge ' + (Boolean(mode.real_withdrawal_enabled ?? data.mode?.real_withdrawal_enabled ?? false) ? 'badge--red' : 'badge--ghost');
  }
  const allowNew = mode.allow_new_live_orders;
  const allowBadge = el('gate-allow-new-orders');
  if (allowBadge) {
    allowBadge.textContent = allowNew ? 'YES' : 'NO';
    allowBadge.className = 'badge ' + (allowNew ? 'badge--green' : 'badge--red');
    allowBadge.title = mode.allow_new_live_orders_reason || '';
  }

  // Right panel — Portfolio
  setT('pi-equity', idr(port.combined_equity_idr || port.equity_idr || 0));
  setT('pi-start-equity', idr(data.capital?.starting_equity_today_idr || data.capital?.start_total_equity_idr || data.capital?.starting_equity_idr || 0));
  setT('pi-cash',   idr(port.idr_cash || 0));
  setT('pi-coin',   idr(port.coin_holdings_idr || 0));
  setPnl('pi-real-pnl',  port.real_pnl_idr   || port.daily_pnl_real_idr || 0);
  setPct('pi-real-pnl-pct',  port.daily_pnl_pct || data.capital?.daily_pnl_pct || 0);
  setPnl('pi-risk-remaining', data.capital?.risk_remaining_idr || 0);
  setT('pi-allow-orders', allowNew ? 'YES' : 'NO');
  setT('pi-current-entry', data.current_entry_approved ? 'YES' : 'NO');
  setT('pi-blocked-reason', mode.allow_new_live_orders_reason || '—');

  // Venue equities
  setT('eq-indodax-real',  idr(venues.indodax_real?.equity_idr  || 0));
  setT('eq-indodax-live', idr(venues.indodax_live?.equity_idr || 0));
  setT('eq-polymarket',    idr(venues.polymarket?.equity_idr    || 0));
  
  // Phantom Scout details
  setT('eq-phantom', idr(ph.total_value_idr || 0));
  setT('phantom-sol', (ph.sol_balance || 0).toFixed(4) + ' SOL');
  setT('phantom-usdc', (ph.usdc_balance || 0).toFixed(2) + ' USDC');
  setT('phantom-base-idrx', idr(ph.base_idrx_balance || 0));
  setT('phantom-base-address', shortAddr(ph.chains?.base?.evm_address || ph.evm_address || ''));
  setT('phantom-base-block', ph.chains?.base?.latest_block ? `#${ph.chains.base.latest_block}` : '—');
  setT('phantom-base-status', ph.status || '—');
  setT('phantom-recon', ph.reconciliation?.matches_user_wallet ? 'MATCH' : 'MISMATCH');
  setT('phantom-bucket-swap', idr(ph.buckets?.swap_idr || 0));
  setT('phantom-bucket-polymarket', idr(ph.buckets?.polymarket_idr || 0));
  setT('phantom-bucket-reserve', idr(ph.buckets?.reserve_idr || 0));
  setT('phantom-bucket-future-web3', idr(ph.buckets?.future_web3_idr || 0));

  const web3 = data.web3 || {};
  const routes = web3.routes || {};
  setT('eq-web3', `${Object.keys(routes).length || 0} routes`);
  setT('web3-solanastatus', routes.solana?.status || '—');
  setT('web3-basestatus', routes.base?.status || '—');
  setT('web3-polystatus', routes.polymarket?.status || '—');
  setT('web3-futurestatus', routes.future_web3?.status || '—');
  const bestOpp = (web3.opportunities?.best_opportunities || [])[0];
  setT('web3-bestopp', bestOpp ? `${bestOpp.route}:${bestOpp.asset}` : '—');
  const rej = (web3.opportunities?.rejected || [])[0];
  setT('web3-rejected', rej ? String(rej.reason || '—').slice(0, 36) : '—');
  const memeHunter = web3.meme_hunter || {};
  const memeBest = memeHunter.best_candidate || web3.solana_trending?.best_candidate || {};
  setT('meme-best-candidate', memeBest?.symbol ? `${memeBest.symbol} ${memeBest.change_24h_pct != null ? pct(memeBest.change_24h_pct) : ''}`.trim() : '—');
  setT('meme-reason', memeBest?.reason || (memeHunter.enabled ? `${memeHunter.candidates_found || 0} scanned` : 'disabled'));
  const pumpfun = web3.pumpfun || {};
  const pumpfunRoute = web3.pumpfun_route || {};
  const pumpfunNative = web3.pumpfun_native || {};
  const pumpfunBest = pumpfun.best_candidate || {};
  setT('pumpfun-route-type', pumpfun.route_type || pumpfunRoute.route_type || '—');
  setT('pumpfun-buy-sell', `${pumpfun.can_buy ? 'BUY' : 'NO BUY'} / ${pumpfun.can_sell ? 'SELL' : 'NO SELL'}`);
  setT('pumpfun-reason', pumpfun.reason || pumpfunRoute.reason || '—');
  setT('pumpfun-best-candidate', pumpfunBest?.symbol ? `${pumpfunBest.symbol} ${pumpfunBest.route_type ? `(${pumpfunBest.route_type})` : ''}`.trim() : '—');
  setT('pumpfun-native-status', pumpfunNative.status ? `${pumpfunNative.status}${pumpfunNative.reason ? ` · ${pumpfunNative.reason}` : ''}` : '—');
  const lat = pumpfun.latency || {};
  setT('pumpfun-latency', lat.hot_path_total_ms != null ? `${lat.hot_path_total_ms}ms` : '—');
  const pumpfunPos = Array.isArray(pumpfun.positions) ? pumpfun.positions[0] : null;
  setT('pumpfun-position', pumpfunPos ? `${pumpfunPos.symbol || pumpfunPos.asset || 'pos'} · ${pumpfunPos.status || 'OPEN'}` : '—');
  const pumpfunExitState = pumpfun.exit_state || {};
  setT('pumpfun-exit-state', pumpfunExitState.status ? `${pumpfunExitState.status}${pumpfunExitState.latest_exit_reason ? ` · ${pumpfunExitState.latest_exit_reason}` : ''}` : '—');
  setT('web3-openpos', Array.isArray(web3.positions) ? String(web3.positions.length) : '0');
  const exitState = web3.exit || {};
  setT('web3-exit-status', exitState.status || '—');
  setT('web3-exit-reason', exitState.latest_exit_reason || '—');
  setT('web3-exit-updated', exitState.last_updated ? new Date(exitState.last_updated).toLocaleTimeString('en-GB', {hour12:false, timeZone:'Asia/Jakarta'}) + ' WIB' : '—');

  const scannerContract = data.scanner_executor_contract || data.scanner_coverage || {};
  const scannerContractRoutes = scannerContract.routes || scannerContract.coverage || scannerContract;
  const routeKeys = Array.isArray(scannerContractRoutes)
    ? scannerContractRoutes
    : Object.keys(scannerContractRoutes || {}).filter(k => !['updated_at', 'status', 'reason', 'blocker', 'source_proof_count'].includes(k));
  const contractStatus = scannerContract.status || scannerContract.coverage_status || scannerContract.runtime_status || 'UNKNOWN';
  const contractReason = scannerContract.reason || scannerContract.blocker || scannerContract.latest_blocker || '—';
  const sourceProofCount = scannerContract.source_proof_count != null
    ? scannerContract.source_proof_count
    : (scannerContract.source_proof_ok_count != null ? scannerContract.source_proof_ok_count : '—');
  setT('scanner-contract-status', contractStatus);
  setT('scanner-coverage-count', routeKeys.length ? String(routeKeys.length) : '—');
  setT('scanner-coverage-proof', sourceProofCount !== '—' ? `${sourceProofCount} proven` : '—');
  setT('scanner-coverage-blocker', contractReason);
  const latestRoute = scannerContract.latest_route || scannerContract.route || scannerContract.last_route || routeKeys[0] || '—';
  setT('scanner-coverage-route', latestRoute);

  const engine = data.engine_independence || {};
  const indodaxEngine = engine.indodax_engine || {};
  const phantomEngine = engine.phantom_engine || {};
  const engineIndo = el('engine-indodax');
  if (engineIndo) {
    engineIndo.textContent = indoBrain.status || indodaxEngine.status || '—';
    engineIndo.className = 'badge ' + ((indodaxEngine.allow_orders ?? true) ? 'badge--green' : 'badge--red');
  }
  const enginePh = el('engine-phantom');
  if (enginePh) {
    enginePh.textContent = phBrain.status || phantomEngine.status || '—';
    enginePh.className = 'badge ' + ((phantomEngine.allow_orders ?? true) ? 'badge--green' : 'badge--red');
  }
  setT('engine-bridge', engine.bridge || 'OFF');
  setT('engine-withdrawal', engine.withdrawal || 'OFF');

  const deadline = data.deadline_pressure || {};
  setT('deadline-minutes', deadline.minutes_to_midnight != null ? String(deadline.minutes_to_midnight) : '—');
  const deadlineStage = el('deadline-stage');
  if (deadlineStage) deadlineStage.textContent = deadline.stage || deadline.pressure_level || '—';
  const deadlineRecovery = el('deadline-recovery-mode');
  if (deadlineRecovery) {
    const recovery = deadline.stage === 'RECOVERY' || deadline.stage === 'PRESSURE';
    deadlineRecovery.textContent = recovery ? 'ON' : 'OFF';
    deadlineRecovery.className = 'badge ' + (recovery ? 'badge--yellow' : 'badge--ghost');
  }
  const deadlineIndo = el('deadline-indodax-pressure');
  if (deadlineIndo) deadlineIndo.textContent = deadline.indodax_pressure || deadline.pressure_level || '—';
  const deadlinePh = el('deadline-phantom-pressure');
  if (deadlinePh) deadlinePh.textContent = deadline.phantom_pressure || deadline.pressure_level || '—';
  setT('deadline-required-action', deadline.required_action || deadline.reason || '—');

  const systemTruth = data.system_truth || {};
  setT('sys-batam-online', systemTruth.batam_server_online ? 'ONLINE' : 'OFFLINE');
  setT('sys-git-commit', systemTruth.git_commit || '—');
  const serviceHealth = systemTruth.service_health || {};
  const stateFreshness = systemTruth.state_freshness || {};
  const servicesOnline = Object.entries(serviceHealth).filter(([, v]) => v && (v.active === 'active' || v === 'active')).length;
  setT('sys-service-health', servicesOnline ? `${servicesOnline} active` : '0 active');
  setT('sys-state-freshness', Object.keys(stateFreshness).length ? `${Object.values(stateFreshness).filter(v => v && v.fresh !== false).length}/${Object.keys(stateFreshness).length} fresh` : '—');

  function renderTopTargets(nodeId, emptyId, payload) {
    const node = el(nodeId);
    const empty = el(emptyId);
    if (!node) return;
    const targets = Array.isArray(payload?.top_targets) ? payload.top_targets : [];
    if (!targets.length) {
      node.innerHTML = '';
      if (empty) empty.textContent = payload?.why_empty || payload?.source_status || '—';
      return;
    }
    if (empty) empty.textContent = payload?.why_empty || '—';
    node.innerHTML = targets.map(t => {
      const score = t.entry_score ?? t.wave_score ?? 0;
      const exitScore = t.exit_score ?? 0;
      const action = t.recommended_action || 'WATCH';
      const routeStatus = t.route_status || t.executor_status || '—';
      const reason = t.reason || '—';
      const label = t.symbol || t.route || 'unknown';
      const secondary = t.pair || t.chain || t.mint_or_market || '';
      const metric = t.volume_24h_idr ?? t.volume_or_liquidity ?? 0;
      const change = t.change_24h_pct ?? t.change_pct ?? 0;
      const actionCls = action === 'ENTER' ? 'badge badge--green' : (action === 'WATCH' ? 'badge badge--yellow' : (action === 'REJECT' ? 'badge badge--red' : 'badge badge--ghost'));
      return `<div style="margin-bottom:6px"><strong>#${t.rank}</strong> ${label} ${secondary ? `· ${secondary}` : ''} <span class="${actionCls}" style="margin-left:6px">${action}</span> <span class="badge badge--ghost" style="margin-left:4px">${esc(routeStatus)}</span><br/><span class="text-muted">${pct(change)} | ${idr(metric)} | entry ${Number(score).toFixed(1)} | exit ${Number(exitScore).toFixed(1)} | ${reason}</span></div>`;
    }).join('');
  }
  renderTopTargets('indodax-top-targets', 'indodax-top-empty', data.indodax_top_targets?.data || data.top_targets?.indodax?.data || data.indodax_top_targets || data.top_targets?.indodax || {});
  renderTopTargets('phantom-top-targets', 'phantom-top-empty', data.phantom_top_targets?.data || data.top_targets?.phantom?.data || data.phantom_top_targets || data.top_targets?.phantom || {});

  const phantomBoard = data.phantom_top_targets?.data || data.top_targets?.phantom?.data || data.phantom_top_targets || data.top_targets?.phantom || {};
  const phantomBreakdown = el('phantom-source-breakdown');
  if (phantomBreakdown) {
    const breakdown = phantomBoard.source_breakdown || {};
    const rows = Object.entries(breakdown).map(([name, info]) => {
      const count = info?.count ?? 0;
      const status = info?.status || '—';
      const reason = info?.reason || '';
      return `<div><strong>${esc(name)}</strong> · ${esc(String(count))} · ${esc(status)}${reason ? ` · ${esc(reason)}` : ''}</div>`;
    });
    const cap = phantomBoard.route_capability_summary || {};
    const capRows = phantomBoard.route_capabilities
      ? Object.entries(phantomBoard.route_capabilities).map(([name, info]) => `<div><strong>${esc(name)}</strong> · ${esc(info.status || '—')} · exec:${info.can_execute ? 'Y' : 'N'} · exit:${info.can_exit ? 'Y' : 'N'}</div>`)
      : [];
    const capHeader = `<div style="margin-top:6px;color:#64748b">Route capabilities · total:${esc(String(cap.routes_total ?? 0))} ready:${esc(String(cap.routes_ready ?? 0))} blocked:${esc(String(cap.routes_blocked ?? 0))}</div>`;
    phantomBreakdown.innerHTML = `${rows.length ? rows.join('') : `<div>${esc(phantomBoard.why_empty || '—')}</div>`}${capHeader}${capRows.length ? capRows.join('') : ''}`;
  }
  const phantomTopEmpty = el('phantom-top-empty');
  if (phantomTopEmpty && phBrain.recovery_mode) {
    phantomTopEmpty.textContent = `RECOVERY · ${phantomBoard.why_empty || phantomBoard.source_status || 'active search'}`;
  }

  setT('ai-objective', ai.objective || '—');
  setT('ai-best-action', brain.current_best_action || ai.best_action || '—');
  setT('ai-confidence', ai.confidence != null ? Number(ai.confidence).toFixed(2) : '—');
  setT('ai-venue', ai.venue || '—');
  const brainSize = brain.sizing || sizing || {};
  setT('autonomous-size', brainSize.size_idr != null ? idr(brainSize.size_idr) : '—');
  setT('autonomous-size-reason', brain.reason || sizing.reason || '—');
  setT('autonomous-guard-action', sizing.guard_action || '—');
  setT('autonomous-max-loss', brainSize.max_loss_if_stop_hit_idr != null ? idr(brainSize.max_loss_if_stop_hit_idr) : (sizing.max_loss_if_stop_hit_idr != null ? idr(sizing.max_loss_if_stop_hit_idr) : '—'));
  setT('ai-reason', ai.reason || '—');
  setT('ai-next-check', ai.next_check_seconds != null ? `${ai.next_check_seconds}s` : '—');

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
  const telemetry = data.server_telemetry?.data || data.server_truth || {};
  const cpu = telemetry.cpu?.percent ?? telemetry.cpu_pct ?? data.system?.cpu_pct;
  const ram = telemetry.ram?.percent ?? telemetry.ram_pct ?? data.system?.ram_pct;
  const disk = telemetry.disk?.percent ?? data.system?.disk_pct;
  const uptime = telemetry.uptime_seconds;
  setT('sys-cpu', cpu!=null ? `${Number(cpu).toFixed(1)}%` : 'MISSING_WITH_REASON');
  setT('sys-ram', ram!=null ? `${Number(ram).toFixed(1)}%` : 'MISSING_WITH_REASON');
  const diskEl = el('sys-disk');
  if (diskEl) diskEl.textContent = disk!=null ? `${Number(disk).toFixed(1)}%` : 'MISSING_WITH_REASON';
  const upEl = el('sys-uptime');
  if (upEl) upEl.textContent = uptime!=null ? `${Math.floor(Number(uptime))}s` : 'MISSING_WITH_REASON';
  setT('sys-ollama', rt.ollama?.status || '—');
  setT('sys-tel-age', data.server_telemetry?.age_s != null ? freshnessLabel(data.server_telemetry.age_s) : '—');

  // Last updated
  const ts = new Date(data.timestamp||Date.now());
  setT('last-updated', ts.toLocaleTimeString('id-ID'));

  // Logs — activity
  const events = (data.events || []).filter(e => !NOISE_RE.test(e.message||''));
  if (events.length) {
    events.slice(0,5).reverse().forEach(e => pushLog(_actLog,'activity-log',{message:e.message,tag:e.level==='ERROR'?'ERROR':e.level==='WARNING'?'WARN':'INFO'}));
  } else {
    pushLog(_actLog,'activity-log',{
      message: mode.live_trading_enabled ? '⚠ Live trading ACTIVE' : '✓ Controlled-live mode active — live trading OFF',
      tag: mode.live_trading_enabled ? 'WARN' : 'INFO'
    });
  }

  // Logs — technical
  Object.entries(fresh).slice(0,4).forEach(([k,age]) => {
    pushLog(_techLog,'technical-log',{message:`${k}: ${freshnessLabel(age)}`, tag:age>STALE_SECS?'WARN':'INFO'});
  });

  // Queue
  renderQueue(data);

  // Connect both engines by rendering visual status and selected agent boxes in canvas.js
  if (window.KiBotCanvas && typeof window.KiBotCanvas.render === 'function') {
    window.KiBotCanvas.render(data);
  }

  // Redraw connectors after render
  requestAnimationFrame(drawConnectors);
}

/* ─── Dynamic Card Engine ───────────────────────────────── */
function ensureAgentCardsCreated() {
  const layer = el('delegation-layer');
  if (!layer) return;

  // Prevent duplicate card injection
  if (document.querySelector('.agent-card')) return;

  Object.entries(AGENT_META).forEach(([agentId, meta]) => {
    const rowEl = el(`row-${meta.row}`);
    if (!rowEl) return;

    const mappedId = agentId.replace(/_/g, '-');
    const card = document.createElement('div');
    card.className = `agent-card agent-card--${meta.color} ${meta.isSm ? 'agent-card--sm' : ''}`;
    card.id = `card-${mappedId}`;
    card.dataset.agentId = agentId;

    let statusHtml = `<span id="${mappedId}-status">WAIT</span>`;
    let metricHtml = `<span id="${mappedId}-metric">—</span>`;

    // Special dual-support mappings to prevent any script breakage
    if (agentId === 'indodax_real') {
      statusHtml = `
        <span id="indodax-real-status">WAIT</span>
        <span id="indodax-status" style="display:none"></span>
      `;
      metricHtml = `
        <span id="indodax-real-metric">—</span>
        <span id="indodax-metric" style="display:none"></span>
      `;
    } else if (agentId === 'indodax_shadow') {
      statusHtml = `
        <span id="indodax-shadow-status">WAIT</span>
        <span id="risk-remaining-status" style="display:none"></span>
      `;
  } else if (agentId === 'polymarket') {
    metricHtml = `
        <span id="polymarket-metric">—</span>
        <span id="poly-metric" style="display:none"></span>
      `;
  } else if (agentId === 'phantom') {
    metricHtml = `
        <span id="phantom-metric">—</span>
        <span id="phantom-route-metric" style="display:none"></span>
      `;
  }

    card.innerHTML = `
      <div class="agent-avatar av--${meta.color}">${meta.letter}</div>
      <div class="agent-body">
        <div class="agent-name">${meta.name}</div>
        <div class="agent-role">${meta.role}</div>
        <div class="agent-status">
          <span class="dot dot--${meta.color}" id="${mappedId}-dot"></span>
          ${statusHtml}
        </div>
        <div class="agent-metric">
          ${metricHtml}
        </div>
      </div>
    `;

    rowEl.appendChild(card);
  });
}

/* ─── Poll loop ──────────────────────────────────────────── */
async function poll() {
  try {
    const r = await fetch('/api/control-plane', { cache: 'no-store' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    render(await r.json());
  } catch(err) {
    const gateLive = el('gate-live-trading');
    if (gateLive && gateLive.textContent === 'OFF') {
      gateLive.textContent = 'SYNCING';
      gateLive.className = 'badge badge--ghost';
    }
    pushLog(_techLog,'technical-log',{message:`API error: ${err.message}`, tag:'ERROR'});
  }
}

/* ─── Init ───────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  const syncBadge = (id) => {
    const node = el(id);
    if (node && (node.textContent === 'OFF' || node.textContent === 'ON' || node.textContent === '—')) {
      node.textContent = 'SYNCING';
      node.className = 'badge badge--ghost';
    }
  };
  syncBadge('gate-live-trading');
  syncBadge('gate-bridge');
  syncBadge('gate-swap');
  syncBadge('gate-withdrawal');
  syncBadge('gate-allow-new-orders');
  ensureAgentCardsCreated();
  initCanvas();
  initModal();
  initTabs();
  poll();
  setInterval(poll, POLL_MS);
  window.addEventListener('resize', drawConnectors);
});
