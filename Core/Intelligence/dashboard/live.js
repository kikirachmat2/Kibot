/* KiBot Delegation live.js — v5.0 */
"use strict";

const POLL_MS    = 8000;
const STALE_SECS = 90;
const MAX_LOGS   = 80;
const NOISE_RE   = /vault|decrypt|cipher|CEREBRAS_API_KEY|MISTRAL_API_KEY|os\.environ/i;

const idr = v => `Rp ${Math.round(+v||0).toLocaleString('id-ID')}`;
const pct = v => `${v>=0?'+':''}${(+v||0).toFixed(2)}%`;
const pickFinite = (...vals) => {
  for (const v of vals) {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return 0;
};
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

  const zoomIn = el('btn-zoom-in');
  const zoomOut = el('btn-zoom-out');
  const fit = el('btn-fit');
  if (zoomIn) zoomIn.onclick  = () => { cs.scale = Math.min(SCALE_MAX, cs.scale+SCALE_STEP); applyTransform(true); };
  if (zoomOut) zoomOut.onclick = () => { cs.scale = Math.max(SCALE_MIN, cs.scale-SCALE_STEP); applyTransform(true); };
  if (fit) fit.onclick = fitCanvas;
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
    {from:'card-director',  to:'card-indodax-balance', style:'solid',  color:'#64748b'},
    {from:'card-indodax-real', to:'card-pnl-feedback', style:'dotted', color:'#ef4444'},
    {from:'card-indodax-balance',to:'card-pnl-feedback', style:'dotted', color:'#64748b'},
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
  operator:   { letter:'K', color:'blue',   name:'Kiki / Operator',       role:'Human In The Loop',     row: 1, isSm: false, desc:'The sovereign operator. Sets policy, approves live gate, monitors all agents. LIVE_ONLY mode active on Batam node.', inputs:[], outputs:[], stateFile:null },
  council:    { letter:'Ω', color:'purple', name:'Sovereign Council',     role:'Governance Gate',       row: 1, isSm: false, desc:'High-level deliberation chamber. Aggregates and debates predictions, scanner data, and sentiment before approving order execution.', inputs:['strategy_scorecard.json', 'expected_value.json'], outputs:['council_decisions.jsonl'], stateFile:'council_decisions.jsonl' },
  director:   { letter:'D', color:'blue',   name:'Autonomous Director',   role:'Lead Coordinator',      row: 2, isSm: false, desc:'Core state orchestrator. Reads signal qualities and EV gates. Issues WAIT, APPROVE, or REJECT decisions based on rules.',  inputs:['signal_quality.json','expected_value.json','strategy_scorecard.json','punishment_state.json'], outputs:['autonomous_director.json'], stateFile:'autonomous_director.json' },
  risk:       { letter:'R', color:'red',    name:'RiskGate Shield',       role:'Drawdown Shield',       row: 2, isSm: false, desc:'Safety gate enforcing 1.5% maximum daily drawdown. Blocks all downstream order execution if drawdown is breached.', inputs:['portfolio_summary.json'], outputs:[], stateFile:'portfolio_summary.json' },
  scanner:    { letter:'S', color:'green',  name:'Scanner',               role:'Signal Discovery',      row: 3, isSm: true,  desc:'Scans Indodax orderbooks and tickers for momentum and cross-asset lead-lag anomalies. Sends candidates to LeadLag engine.', inputs:['market_cache.json'], outputs:['scanner_runtime.json'], stateFile:'scanner_runtime.json' },
  leadlag:    { letter:'L', color:'green',  name:'LeadLag Alpha',         role:'Correlation Engine',    row: 3, isSm: true,  desc:'Computes high-speed lead-lag correlations between major assets (BTC/ETH) and altcoins to detect leading momentum.', inputs:['scanner_runtime.json'], outputs:['leadlag_alpha.json', 'signal_quality.json'], stateFile:'signal_quality.json' },
  ev:         { letter:'V', color:'yellow', name:'Expected Value Gate',   role:'EV Threshold Gate',     row: 3, isSm: true,  desc:'Evaluates candidate trades based on expected value (EV) after fees. Blocks execution if EV is negative or below threshold.', inputs:['signal_quality.json'], outputs:['expected_value.json'], stateFile:'expected_value.json' },
  scorecard:  { letter:'C', color:'purple', name:'Strategy Scorecard',     role:'Deliberation Score',    row: 3, isSm: true,  desc:'Grades strategies against current market regimes and recent trade outcomes. Submits composite scorecard to Council.', inputs:['signal_quality.json', 'expected_value.json'], outputs:['strategy_scorecard.json'], stateFile:'strategy_scorecard.json' },
  indodax_real: { letter:'IR', color:'red',  name:'Indodax Spot',         role:'Live Spot Venue',       row: 4, isSm: true,  desc:'LIVE_ONLY exchange order placement with RiskGate and Capital Governor enforcement.', inputs:['autonomous_director.json'], outputs:['live_trades.json'], stateFile:null },
  indodax_balance: { letter:'IB', color:'gray', name:'Indodax Balance',      role:'Balance Ledger',        row: 4, isSm: true,  desc:'Balance accounting for internal analysis only.', inputs:['autonomous_director.json'], outputs:['balance_trades.json'], stateFile:'portfolio_summary.json' },
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
    status = data.mode?.live_trading_enabled ? 'LIVE_ONLY' : 'BLOCKED';
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
  } else if (agentId === 'indodax_balance') {
    status = 'BALANCE';
    metric = 'active';
    decision = 'Balance ledger only. Production route text intentionally hidden from the live dashboard.';
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

  const content = el('modal-content');
  if (!modal || !content) return;

  content.innerHTML = `
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
        <div class="modal-kv"><span class="k">Mode</span><strong>${esc((data.mode||{}).trading_mode||'LIVE_ONLY')}</strong></div>
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
  const modal = el('agent-modal');
  if (modal) modal.classList.add('hidden');
}

function initModal() {
  const closeButton = el('modal-close');
  const backdrop = el('modal-backdrop');
  if (closeButton) closeButton.onclick = closeModal;
  if (backdrop) backdrop.onclick = closeModal;
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
let _actKeys = new Set(), _techKeys = new Set();

function pushLog(arr, domId, entry) {
  const time  = new Date().toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const tag   = String(entry.tag || 'SYSTEM EVENT').toUpperCase();
  const key   = `${tag}::${String(entry.message || '').trim()}`;
  const keyStore = domId === 'activity-log' ? _actKeys : _techKeys;
  if (keyStore.has(key)) return;
  keyStore.add(key);
  if (keyStore.size > MAX_LOGS * 2) {
    keyStore.clear();
  }
  const tagCl = {
    INFO:'info', WARN:'warn', ERROR:'error', SUCCESS:'success',
    BUY:'buy', 'SELL PROFIT':'sell-profit', 'SELL LOSS':'sell-loss',
    'BUY PENDING':'warn', 'SELL PENDING':'warn',
    'BUY REJECTED':'error', 'SELL REJECTED':'error',
    STALE:'warn',
    'COUNCIL REPORT':'council', 'SYSTEM EVENT':'system'
  }[tag] || 'info';
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
    _actKeys.clear(); _techKeys.clear();
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

function badgeClassForStatus(status) {
  const s = String(status || 'UNKNOWN').toUpperCase();
  if (['OK', 'PASS', 'READY', 'LIVE_ONLY', 'ACTIVE', 'APPROVED', 'RECONCILED'].includes(s)) return 'badge badge--green';
  if (['WAIT', 'CAUTION', 'LOCKED', 'BLOCKED', 'REJECT', 'DEGRADED', 'MUTED'].includes(s)) return 'badge badge--yellow';
  if (['FAILED', 'ERROR', 'EMERGENCY', 'OFFLINE'].includes(s)) return 'badge badge--red';
  return 'badge badge--ghost';
}

function renderKeyValue(label, value, cls = '') {
  return `<div class="panel-kv"><span>${esc(label)}</span><strong class="${esc(cls)}">${esc(value)}</strong></div>`;
}

function renderListPanel(items, empty = '—') {
  return items.length ? `<div class="panel-list">${items.join('')}</div>` : `<div class="panel-empty">${esc(empty)}</div>`;
}

function renderMetricCard(label, value, sub = '') {
  return `
    <div class="metric-card gradient-border">
      <div class="metric-card__label">${esc(label)}</div>
      <div class="metric-card__value">${esc(value)}</div>
      <div class="metric-card__sub">${esc(sub)}</div>
    </div>`;
}

/* ─── Render from API data ───────────────────────────────── */
function render(data) {
  _lastData = data;
  const mode  = data.mode  || {};
  const port  = data.portfolio_v6 || data.portfolio || {};
  const gates = data.gates || {};
  const venues= data.venues || {};
  const fresh = data.freshness || {};
  const rt    = data.runtime || {};
  const dir   = data.autonomous_director || {};
  const ai = data.ai || {};
  const sizing = data.autonomous_sizing || {};
  const brain = data.autonomous_trading_brain || {};
  const indoBrain = data.indodax_live_brain || {};

  // Top bar badges
  const modeBadge = el('mode-badge');
  if (modeBadge) {
    modeBadge.textContent = (mode.trading_mode||'LIVE_ONLY').toUpperCase();
    modeBadge.className = mode.live_trading_enabled ? 'badge badge--green' : 'badge badge--red';
  }

  const warn = data.warnings||[];
  const gsBadge = el('global-status');
  if (gsBadge) {
    gsBadge.textContent = warn.length ? 'WARNING' : 'OK';
    gsBadge.className   = warn.length ? 'badge badge--yellow' : 'badge badge--green';
  }
  const warningBadge = el('warning-badge');
  if (warningBadge) {
    if (warn.length) {
      warningBadge.classList.remove('hidden');
      const warningText = String(warn[0]?.reason || warn[0]?.message || warn[0] || 'warning');
      warningBadge.textContent = `⚠ ${warningText}`;
      warningBadge.title = warningText;
    } else {
      warningBadge.classList.add('hidden');
      warningBadge.textContent = '⚠ NO WARNING';
      warningBadge.title = '';
    }
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
  const riskRemaining = data.capital?.risk_remaining_idr || port.risk_remaining_idr || 0;
  setT('risk-remaining-status', `Rp ${Math.abs(riskRemaining).toLocaleString('id-ID')}`);

  // Safety Gates Badges (Dynamic)
  const liveEnabled = Boolean(mode.live_trading_enabled ?? data.mode?.live_trading_enabled ?? rt.mode?.live_trading_enabled ?? false);
  const gateLive = el('gate-live-trading');
  if (gateLive) {
    gateLive.textContent = liveEnabled ? 'ON' : 'OFF';
    gateLive.className = 'badge ' + (liveEnabled ? 'badge--red' : 'badge--ghost');
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
  const truth = data.accounting_truth || port.accounting_truth || data.capital?.accounting_truth || {};
  const equityNow = pickFinite(truth.current_total_equity_idr, truth.total_balance_idr, data.capital?.total_balance_idr, data.capital?.current_total_equity_idr, data.capital?.live_current_total_equity_idr, port.total_balance_idr, port.combined_equity_idr, port.equity_idr);
  const equityStart = pickFinite(truth.reset_total_balance_idr, truth.start_total_equity_idr, data.capital?.reset_total_balance_idr, data.capital?.start_total_equity_idr, data.capital?.starting_equity_today_idr, data.capital?.starting_equity_idr);
  setT('pi-equity', idr(equityNow));
  setT('pi-start-equity', idr(equityStart));
  const realizedPnL = port.realized_pnl_idr ?? port.real_pnl_idr ?? port.daily_pnl_real_idr ?? 0;
  const pnlSource = port.daily_pnl_source || data.capital?.daily_pnl_source || 'live_portfolio';
  const dailyPnL = pickFinite(truth.daily_pnl_idr, truth.combined_pnl_idr, data.capital?.daily_return_idr, data.capital?.combined_pnl_idr, data.capital?.daily_pnl_idr, data.capital?.live_daily_pnl_idr, port.daily_return_idr, port.combined_pnl_idr, port.daily_pnl_idr);
  const dailyPct = pickFinite(truth.daily_pnl_pct, truth.daily_return_pct, data.capital?.daily_return_pct, data.capital?.daily_pnl_pct, data.capital?.live_daily_pnl_pct, port.daily_return_pct, port.daily_pnl_pct);
  const realizedPct = (Array.isArray(port.open_position_pnl) && port.open_position_pnl.length) ? 0 : dailyPct;
  setPnl('pi-real-pnl',  dailyPnL);
  setPct('pi-real-pnl-pct',  dailyPct);
  setPnl('pi-risk-remaining', data.capital?.risk_remaining_idr || 0);
  setT('pi-allow-orders', allowNew ? 'YES' : 'NO');
  setT('pi-current-entry', data.current_entry_approved ? 'YES' : 'NO');
  const openOrders = Array.isArray(data.order_tracker?.open_orders) ? data.order_tracker.open_orders : [];
  const openOrderCount = data.capital?.pending_orders_count != null ? Number(data.capital.pending_orders_count) : openOrders.length;
  const openOrderPairs = openOrders.map(o => String(o?.pair || o?.symbol || '').trim()).filter(Boolean);
  const pendingOrdersBadge = el('pi-pending-orders');
  if (pendingOrdersBadge) {
    pendingOrdersBadge.textContent = openOrderCount ? `${openOrderCount} OPEN` : '0';
    pendingOrdersBadge.className = 'badge ' + (openOrderCount ? 'badge--yellow' : 'badge--ghost');
    pendingOrdersBadge.title = openOrderPairs.length ? openOrderPairs.join(', ') : '';
  }
  const openPnLCount = Array.isArray(port.open_position_pnl) ? port.open_position_pnl.length : 0;
  const venueAllowances = mode.venue_allowances || {};
  const readyVenues = Object.entries(venueAllowances).filter(([, allowed]) => allowed).map(([name]) => name);
  const blockedVenues = Object.entries(venueAllowances).filter(([, allowed]) => !allowed).map(([name]) => name);
  const explicitBlockReason = String(data.capital?.allow_new_orders_reason || mode.allow_new_live_orders_reason || '').trim();
  const genericBlockedVenues = /^blocked venues?:/i.test(explicitBlockReason);
  if (allowNew) {
    setT('pi-blocked-reason', readyVenues.length ? `venue-scoped ready: ${readyVenues.join(', ')}` : 'venue-scoped allowance active');
  } else {
    setT(
      'pi-blocked-reason',
      (!genericBlockedVenues && explicitBlockReason)
        ? explicitBlockReason
        : (openOrderCount ? `${openOrderCount} pending order(s)` : (openPnLCount ? `${openPnLCount} open position(s)` : (explicitBlockReason || '—')))
    );
  }

  // Venue equities
  setT('eq-indodax-real',  idr(venues.indodax_real?.equity_idr  || 0));
  setT('eq-indodax-live', idr(venues.indodax_live?.equity_idr || 0));

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
  const engineIndo = el('engine-indodax');
  if (engineIndo) {
    engineIndo.textContent = indoBrain.status || indodaxEngine.status || '—';
    engineIndo.className = 'badge ' + ((indodaxEngine.allow_orders ?? true) ? 'badge--green' : 'badge--red');
  }
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
  setT('deadline-required-action', deadline.required_action || deadline.reason || '—');

  const dailyReset = data.daily_reset?.data || data.daily_reset || {};
  const dailyResetStatus = el('daily-reset-status');
  if (dailyResetStatus) {
    const status = String(dailyReset.status || '—').toUpperCase();
    dailyResetStatus.textContent = status;
    dailyResetStatus.className = 'badge ' + (status === 'RESET_DONE' ? 'badge--green' : (status === 'PENDING_RESET' || status === 'EXITING' || status === 'PRE_CLOSE' ? 'badge--yellow' : (status === 'BLOCKED_WITH_REASON' ? 'badge--red' : 'badge--ghost')));
  }
  setT('daily-reset-minutes', dailyReset.minutes_to_midnight != null ? `${dailyReset.minutes_to_midnight}m` : '—');
  setT('daily-reset-inventory', dailyReset.inventory_open_count != null ? String(dailyReset.inventory_open_count) : '—');
  setT('daily-reset-governor-date', dailyReset.governor_date || dailyReset.wib_date || '—');
  setT('daily-reset-next-action', dailyReset.next_action || '—');
  setT('daily-reset-reason', dailyReset.reason || '—');

  const systemTruth = data.system_truth || {};
  setT('sys-batam-online', systemTruth.batam_server_online ? 'ONLINE' : 'OFFLINE');
  setT('sys-git-commit', systemTruth.git_commit || '—');
  const serviceHealth = systemTruth.service_health || {};
  const stateFreshness = systemTruth.state_freshness || {};
  const servicesOnline = Object.entries(serviceHealth).filter(([, v]) => v && (v.active === 'active' || v === 'active')).length;
  setT('sys-service-health', servicesOnline ? `${servicesOnline} active` : '0 active');
  setT('sys-state-freshness', Object.keys(stateFreshness).length ? `${Object.values(stateFreshness).filter(v => v && v.fresh !== false).length}/${Object.keys(stateFreshness).length} fresh` : '—');

  const aiSystem = data.ai_system || {};
  const aiData = aiSystem.data || {};
  const aiSummary = aiData.summary || {};
  const aiStatusBadge = el('ai-system-status');
  if (aiStatusBadge) {
    aiStatusBadge.textContent = aiSystem.status || (aiSystem.fresh ? 'OK' : 'DEGRADED');
    aiStatusBadge.className = 'badge ' + ((aiSystem.status || '').toUpperCase() === 'OK' ? 'badge--green' : 'badge--yellow');
  }
  setT('ai-system-active', aiSystem.active_components != null ? String(aiSystem.active_components) : String(aiSummary.active_components ?? '—'));
  setT('ai-system-locked', aiSystem.locked_or_conditional_components != null ? String(aiSystem.locked_or_conditional_components) : String(aiSummary.locked_or_conditional_components ?? '—'));
  const aiOrder = el('ai-system-order-permission');
  if (aiOrder) {
    aiOrder.textContent = aiSystem.order_permission || 'DENIED';
    aiOrder.className = 'badge badge--red';
  }
  const aiOverride = el('ai-system-override-permission');
  if (aiOverride) {
    aiOverride.textContent = aiSystem.override_permission || 'DENIED';
    aiOverride.className = 'badge badge--red';
  }
  setT('ai-system-last-check', aiSystem.last_check_at || aiData.updated_at || '—');

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

  // KPI strip
  setT('kpi-total-equity', idr(port.total_equity_idr ?? port.total_balance_idr ?? port.combined_equity_idr ?? 0));
  setT('kpi-total-equity-sub', freshnessLabel(data.live_truth?.age_s));
  setT('kpi-net-pnl', idr(port.net_pnl_today_idr ?? port.daily_pnl_idr ?? 0));
  setT('kpi-net-pnl-sub', pct(port.daily_pnl_pct ?? 0));
  setT('kpi-risk-remaining', idr(port.risk_remaining_idr ?? data.capital?.risk_remaining_idr ?? 0));
  setT('kpi-risk-remaining-sub', `cap ${port.daily_loss_cap_pct ?? data.capital?.max_daily_loss_pct ?? 1.5}%`);
  setT('kpi-open-positions', String(getCount((data.live_truth?.data || {}).open_positions ?? port.open_positions ?? port.active_positions ?? [])));
  setT('kpi-open-positions-sub', port.realized_pnl_today_idr != null ? `realized ${idr(port.realized_pnl_today_idr)}` : 'live');
  setT('kpi-indodax', `${esc(venues.indodax_real?.status || '—')} · ${idr(venues.indodax_real?.equity_idr || 0)}`);
  setT('kpi-indodax-sub', venues.indodax_real?.allow_orders ? 'orders on' : 'orders off');
  setT('kpi-cash-reserve', idr(port.cash_idr ?? port.idr_cash ?? 0));
  setT('kpi-cash-reserve-sub', 'Indodax-only');

  // Logs — activity
  const events = (data.events || []).filter(e => !NOISE_RE.test(e.message||''));
  const allowTags = new Set(['BUY','BUY PENDING','SELL PENDING','BUY REJECTED','SELL REJECTED','SELL PROFIT','SELL LOSS','STALE','COUNCIL REPORT']);
  const activityEvents = events.filter(e => allowTags.has(String(e.tag || '').toUpperCase()));
  if (activityEvents.length) {
    activityEvents.slice(0,5).reverse().forEach(e => pushLog(_actLog,'activity-log',{message:e.message,tag:String(e.tag || 'SYSTEM EVENT').toUpperCase()}));
  }

  // Logs — technical
  Object.entries(fresh).slice(0,4).forEach(([k,age]) => {
    pushLog(_techLog,'technical-log',{message:`${k}: ${freshnessLabel(age)}`, tag:age>STALE_SECS?'WARN':'INFO'});
  });

  // Queue
  renderQueue(data);

  // V6 panels
  renderDashboardPanels(data);

  // Connect both engines by rendering visual status and selected agent boxes in canvas.js
  if (window.KiBotCanvas && typeof window.KiBotCanvas.render === 'function') {
    window.KiBotCanvas.render(data);
  }

  // Redraw connectors after render
  requestAnimationFrame(drawConnectors);
}

function renderDashboardPanels(data) {
  const runtime = data.runtime || {};
  const portfolio = data.portfolio_v6 || {};
  const decision = data.decision || {};
  const venues = data.venues || {};
  const workflow = Array.isArray(data.workflow?.steps) ? data.workflow.steps : [];
  const funnel = data.opportunity_funnel || {};
  const ai = data.ai_system || {};
  const orders = data.orders || {};
  const logs = data.logs || {};
  const debug = data.debug || {};
  const liveTruth = data.live_truth?.data || data.live_truth || {};
  const allowOrders = Boolean(data.mode?.allow_new_live_orders);
  const whyWait = String(decision.current_reason || (allowOrders ? 'No blocker' : 'WAIT')).trim() || 'No blocker';
  const nextAction = String(decision.current_action || workflow[0]?.name || 'SCAN').trim() || 'SCAN';
  const nextActionDetail = String(decision.last_gate_failed || workflow[0]?.reason || decision.current_reason || 'Proceed to next deterministic step').trim();
  const banner = el('status-banner');
  if (banner) {
    const state = String(runtime.state || liveTruth.risk_state || 'OK').toUpperCase();
    banner.className = `status-banner ${state === 'LOCKED' || state === 'EMERGENCY' ? 'status-banner--lock' : state === 'WARNING' ? 'status-banner--warn' : ''}`;
    banner.innerHTML = `
      <div class="status-banner__title">Current Action: ${esc(nextAction)}</div>
      <div class="status-banner__reason">Reason: ${esc(whyWait)}</div>
      <div class="status-banner__next">Next: ${esc(nextActionDetail)}</div>
    `;
  }
  const freshnessPill = el('freshness-pill');
  if (freshnessPill) freshnessPill.textContent = `LIVE ${freshnessLabel(runtime.freshness_s ?? 0)}`;

  const panelOverview = el('panel-overview');
  if (panelOverview) {
    panelOverview.innerHTML = `
      <div class="content-grid content-grid--3">
        ${renderMetricCard('Total Equity', idr(portfolio.total_equity_idr || 0), `Start ${idr(portfolio.starting_equity_idr || portfolio.start_total_equity_idr || 0)}`)}
        ${renderMetricCard('Net PnL Today', idr(portfolio.net_pnl_today_idr || 0), `${pct(portfolio.net_pnl_today_pct || portfolio.daily_pnl_pct || 0)}`)}
        ${renderMetricCard('Risk Remaining', idr(portfolio.risk_remaining_idr || 0), `Daily cap ${portfolio.daily_loss_cap_pct || 1.5}%`)}
      </div>
      <div class="content-grid content-grid--sidebar" style="margin-top:14px;">
        <div class="card">
          <div class="panel-card__title">Decision Now</div>
          ${renderKeyValue('Current Action', nextAction, badgeClassForStatus(nextAction))}
          ${renderKeyValue('Why WAIT?', whyWait, 'mono')}
          ${renderKeyValue('Next Autonomous Action', nextActionDetail, 'mono')}
          ${renderKeyValue('Last Gate', decision.last_gate_passed || '—', 'mono')}
          ${renderKeyValue('Last Rejection', (decision.last_rejection || {}).reason || decision.last_gate_failed || '—', 'mono')}
        </div>
        <div class="card">
          <div class="panel-card__title">System Freshness</div>
          ${renderKeyValue('Runtime', freshnessLabel(runtime.freshness_s ?? 0))}
          ${renderKeyValue('Live Truth', freshnessLabel(data.live_truth?.age_s ?? 0))}
          ${renderKeyValue('Server Telemetry', freshnessLabel(data.server_telemetry?.age_s ?? 0))}
          ${renderKeyValue('Target Board', freshnessLabel(data.target_board_runtime?.age_s ?? 0))}
        </div>
        <div class="card">
          <div class="panel-card__title">Risk Contract</div>
          ${renderKeyValue('Allow Orders', allowOrders ? 'YES' : 'NO', badgeClassForStatus(allowOrders ? 'PASS' : 'REJECT'))}
          ${renderKeyValue('Risk State', liveTruth.risk_state || '—', badgeClassForStatus(liveTruth.risk_state))}
          ${renderKeyValue('Open Positions', String(getCount(liveTruth.open_positions || [])))}
          ${renderKeyValue('Dust Positions', String(getCount(liveTruth.dust_positions || [])))}
        </div>
      </div>
      <div class="content-grid content-grid--2" style="margin-top:14px;">
        <div class="card">
          <div class="panel-card__title">Opportunity Funnel</div>
          ${renderKeyValue('Scanned', String(funnel.scanned ?? 0))}
          ${renderKeyValue('Candidates', String(funnel.candidates ?? 0))}
          ${renderKeyValue('Approved', String(funnel.approved ?? 0))}
          ${renderKeyValue('Executed', String(funnel.executed ?? 0))}
        </div>
        <div class="card">
          <div class="panel-card__title">PnL Breakdown</div>
          ${renderKeyValue('Realized', idr(portfolio.realized_pnl_today_idr || 0))}
          ${renderKeyValue('Unrealized', idr(portfolio.unrealized_pnl_idr || 0))}
          ${renderKeyValue('Fees', idr(portfolio.fees_today_idr || 0))}
          ${renderKeyValue('Net', idr(portfolio.net_pnl_today_idr || 0))}
        </div>
      </div>`;
  }

  const panelWorkflow = el('panel-workflow');
  if (panelWorkflow) {
    const steps = workflow.map(step => `
      <div class="panel-step">
        <div>
          <strong>${esc(step.name || step.label || 'STEP')}</strong>
          <div class="panel-sub">${esc(step.reason || '—')}</div>
        </div>
        <div class="panel-step__meta">
          <span class="${badgeClassForStatus(step.status)}">${esc(step.status || 'WAIT')}</span>
          <small>${esc(freshnessLabel(step.freshness_s ?? 0))}</small>
        </div>
      </div>
    `);
    panelWorkflow.innerHTML = `
      <div class="panel-grid panel-grid--2">
        <div class="panel-card">
          <div class="panel-card__title">Workflow Steps</div>
          ${renderListPanel(steps, 'No workflow steps available')}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Opportunity Funnel</div>
          ${renderKeyValue('Scanned', String(funnel.scanned ?? 0))}
          ${renderKeyValue('Candidates', String(funnel.candidates ?? 0))}
          ${renderKeyValue('Approved', String(funnel.approved ?? 0))}
          ${renderKeyValue('Executed', String(funnel.executed ?? 0))}
        </div>
      </div>`;
  }

  const panelVenues = el('panel-venues');
  if (panelVenues) {
    const row = (name, item) => `
      <div class="panel-step">
        <div>
          <strong>${esc(name)}</strong>
          <div class="panel-sub">${esc(item.reason || item.status_detail || '—')}</div>
        </div>
        <div class="panel-step__meta">
          <span class="${badgeClassForStatus(item.status || item.mode)}">${esc(item.status || item.mode || '—')}</span>
          <small>${esc(item.allow_orders ? 'allow_orders=YES' : 'allow_orders=NO')}</small>
        </div>
      </div>`;
    panelVenues.innerHTML = `
      <div class="panel-grid panel-grid--2">
        <div class="panel-card">
          <div class="panel-card__title">Venue Status</div>
          ${row('Indodax', venues.indodax_real || {})}
          ${row('Cash Wait', venues.cash_wait || {})}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Indodax Money Truth</div>
          ${renderKeyValue('Cash', idr(portfolio.cash_idr || portfolio.idr_cash || 0))}
          ${renderKeyValue('Held Coin Value', idr(portfolio.held_coin_value_idr || portfolio.coin_holdings_idr || 0))}
          ${renderKeyValue('Total Equity', idr(portfolio.total_equity_idr || 0))}
          ${renderKeyValue('Venue Lock', (venues.indodax_real || {}).reason || '—', 'mono')}
        </div>
      </div>`;
  }

  const panelAI = el('panel-ai');
  if (panelAI) {
    panelAI.innerHTML = `
      <div class="panel-grid panel-grid--2">
        <div class="panel-card">
          <div class="panel-card__title">AI System</div>
          ${renderKeyValue('Status', ai.status || 'DEGRADED', badgeClassForStatus(ai.status))}
          ${renderKeyValue('Active Components', String(ai.active_components ?? '—'))}
          ${renderKeyValue('Locked/Conditional', String(ai.locked_or_conditional_components ?? '—'))}
          ${renderKeyValue('Order Permission', ai.order_permission || 'DENIED', badgeClassForStatus(ai.order_permission))}
          ${renderKeyValue('Override Permission', ai.override_permission || 'DENIED', badgeClassForStatus(ai.override_permission))}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">AI Trace</div>
          ${renderKeyValue('Objective', data.ai?.objective || '—', 'mono')}
          ${renderKeyValue('Best Action', data.ai?.best_action || '—', 'mono')}
          ${renderKeyValue('Venue', data.ai?.venue || '—', 'mono')}
          ${renderKeyValue('Reason', data.ai?.reason || '—', 'mono')}
        </div>
      </div>`;
  }

  const panelOrders = el('panel-orders');
  if (panelOrders) {
    const openOrders = Array.isArray(orders.open_orders) ? orders.open_orders : [];
    const closedTrades = Array.isArray(orders.closed_trades) ? orders.closed_trades : [];
    const rejected = Array.isArray(orders.rejected_candidates) ? orders.rejected_candidates : [];
    const dust = Array.isArray(orders.dust_positions) ? orders.dust_positions : [];
    panelOrders.innerHTML = `
      <div class="panel-grid panel-grid--2">
        <div class="panel-card">
          <div class="panel-card__title">Open Orders</div>
          ${renderListPanel(openOrders.map(o => `<div class="panel-step"><div><strong>${esc(o.pair || o.symbol || '—')}</strong><div class="panel-sub">${esc(o.state || o.status || 'OPEN')}</div></div><div class="panel-step__meta"><small>${esc(idr(o.budget_idr || o.cost_idr || 0))}</small></div></div>`), 'No open orders')}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Closed Trades / Rejections / Dust</div>
          ${renderKeyValue('Closed Trades', String(closedTrades.length))}
          ${renderKeyValue('Rejected Candidates', String(rejected.length))}
          ${renderKeyValue('Dust Positions', String(dust.length))}
          ${renderKeyValue('Pending Orders', String(orders.pending_orders ?? 0))}
        </div>
      </div>`;
  }

  const panelLogs = el('panel-logs');
  if (panelLogs) {
    const activity = Array.isArray(logs.operator_activity) ? logs.operator_activity : [];
    const tradeEvents = Array.isArray(logs.trade_events) ? logs.trade_events : [];
    const exceptions = Array.isArray(logs.exceptions) ? logs.exceptions : (logs.exceptions ? [logs.exceptions] : []);
    const technical = logs.technical || {};
    panelLogs.innerHTML = `
      <div class="panel-grid panel-grid--2">
        <div class="panel-card">
          <div class="panel-card__title">Operator Activity</div>
          ${renderListPanel(activity.slice(0, 8).map(e => `<div class="panel-step"><div><strong>${esc(e.tag || 'EVENT')}</strong><div class="panel-sub">${esc(e.message || '—')}</div></div><div class="panel-step__meta"><small>${esc(e.time || '')}</small></div></div>`), 'No operator activity')}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Trade Events</div>
          ${renderListPanel(tradeEvents.slice(0, 8).map(e => `<div class="panel-step"><div><strong>${esc(e.tag || 'TRADE')}</strong><div class="panel-sub">${esc(e.message || '—')}</div></div><div class="panel-step__meta"><small>${esc(e.time || '')}</small></div></div>`), 'No trade events')}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Exceptions</div>
          ${renderListPanel(exceptions.slice(0, 5).map(e => `<div class="panel-step"><div><strong>${esc(e.event_type || e.type || 'EXCEPTION')}</strong><div class="panel-sub">${esc(e.message || e.reason || '—')}</div></div></div>`), 'No exceptions')}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Technical</div>
          ${renderKeyValue('Warnings', String((technical.warnings || []).length))}
          ${renderKeyValue('Stale States', String((technical.stale_states || []).length))}
          ${renderKeyValue('Missing States', String((technical.missing_states || []).length))}
        </div>
      </div>`;
  }

  const panelDebug = el('panel-debug');
  if (panelDebug) {
    const legacy = debug.legacy_debug || {};
    panelDebug.innerHTML = `
      <div class="panel-grid panel-grid--2">
        <div class="panel-card">
          <div class="panel-card__title">Debug Snapshot</div>
          ${renderKeyValue('Runtime Freshness', freshnessLabel(runtime.freshness_s ?? 0))}
          ${renderKeyValue('Live Truth Freshness', freshnessLabel(data.live_truth?.age_s ?? 0))}
          ${renderKeyValue('Target Board Freshness', freshnessLabel(data.target_board_runtime?.age_s ?? 0))}
          ${renderKeyValue('Server Telemetry Freshness', freshnessLabel(data.server_telemetry?.age_s ?? 0))}
        </div>
        <div class="panel-card">
          <div class="panel-card__title">Legacy Debug (hidden source)</div>
          ${renderKeyValue('Shadow Keys', String(Object.keys(legacy.shadow || {}).length))}
          ${renderKeyValue('Paper Keys', String(Object.keys(legacy.paper || {}).length))}
          ${renderKeyValue('Mock Keys', String(Object.keys(legacy.mock || {}).length))}
          ${renderKeyValue('Canary Keys', String(Object.keys(legacy.canary || {}).length))}
        </div>
      </div>`;
  }
}

function initDashboardTabs() {
  const tabButtons = Array.from(document.querySelectorAll('.dash-tab, .section-nav__item'));
  const panels = {
    overview: el('panel-overview'),
    workflow: el('panel-workflow'),
    venues: el('panel-venues'),
    ai: el('panel-ai'),
    orders: el('panel-orders'),
    logs: el('panel-logs'),
    debug: el('panel-debug'),
  };
  const activate = (name) => {
    tabButtons.forEach(btn => btn.classList.toggle('active', btn.dataset.panel === name));
    Object.entries(panels).forEach(([key, node]) => {
      if (!node) return;
      node.classList.toggle('hidden', key !== name);
      node.classList.toggle('panel--active', key === name);
    });
  };
  tabButtons.forEach(btn => btn.addEventListener('click', () => activate(btn.dataset.panel || 'overview')));
  activate('overview');
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
    } else if (agentId === 'indodax_balance') {
      statusHtml = `
        <span id="indodax-balance-status">WAIT</span>
        <span id="risk-remaining-status" style="display:none"></span>
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
let _booted = false;
function bootDashboard() {
  if (_booted) return;
  _booted = true;
  const syncBadge = (id) => {
    const node = el(id);
    if (node && (node.textContent === 'OFF' || node.textContent === 'ON' || node.textContent === '—')) {
      node.textContent = 'SYNCING';
      node.className = 'badge badge--ghost';
    }
  };
  syncBadge('gate-live-trading');
  syncBadge('gate-withdrawal');
  syncBadge('gate-allow-new-orders');
  ensureAgentCardsCreated();
  initCanvas();
  initModal();
  initTabs();
  initDashboardTabs();
  poll();
  setInterval(poll, POLL_MS);
  window.addEventListener('resize', drawConnectors);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bootDashboard, { once: true });
  // The script is loaded at the end of <body>, so a body-ready fallback prevents
  // an external resource from leaving the command center blank indefinitely.
  setTimeout(() => { if (document.body) bootDashboard(); }, 0);
} else {
  bootDashboard();
}
