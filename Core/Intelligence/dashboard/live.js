const fmtIdr = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

const LOG_COLORS = {
  Portfolio: "var(--ink-soft)",
  Council: "var(--council)",
  Scanner: "var(--scanner)",
  Executor: "var(--indo)",
  Polymarket: "var(--poly)",
  Janitor: "var(--janitor)",
  Market: "var(--blue)",
  Deadline: "var(--amber)",
  Probability: "var(--green)",
  System: "var(--janitor)",
  Brain: "var(--brain)",
};

let lastSummary = null;
let activityFeed = [];
let technicalFeed = [];
const seenActivityKeys = new Set();
const seenTechnicalKeys = new Set();
let fallbackPollTimer = null;
let streamRetryTimer = null;
let streamInstance = null;

function byId(id) {
  return document.getElementById(id);
}

function fmtRp(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) >= 1_000_000_000) return `Rp ${(amount / 1_000_000_000).toFixed(2)}M`;
  if (Math.abs(amount) >= 1_000_000) return `Rp ${(amount / 1_000_000).toFixed(1)}jt`;
  return fmtIdr.format(amount);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function updateText(id, value, flash = true) {
  const el = byId(id);
  if (!el) return;
  const next = String(value ?? "--");
  if (el.textContent !== next) {
    el.textContent = next;
    if (flash) {
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
  }
}

function renderClock() {
  const now = new Date();
  const wib = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Jakarta" }));
  updateText(
    "clock",
    `${String(wib.getHours()).padStart(2, "0")}:${String(wib.getMinutes()).padStart(2, "0")}:${String(wib.getSeconds()).padStart(2, "0")} WIB`,
    false,
  );

  const midnight = new Date(wib);
  midnight.setHours(24, 0, 0, 0);
  const minutes = Math.max(0, Math.floor((midnight - wib) / 60000));
  const deadline = byId("deadline");
  if (deadline) {
    deadline.textContent = `deadline ${String(Math.floor(minutes / 60)).padStart(2, "0")}h ${String(minutes % 60).padStart(2, "0")}m`;
    deadline.className = minutes < 120 ? "urgent" : "";
  }
}

function renderPositions(positions) {
  if (!positions || !positions.length) {
    return `<div class="empty-row">No active positions</div>`;
  }
  return positions.slice(0, 8).map((pos) => {
    const coin = String(pos.coin || pos.symbol || "coin").toUpperCase();
    const amount = Number(pos.amount || 0);
    const value = Number(pos.value_idr || 0);
    return `
      <div class="position-row">
        <span class="pos-coin">${escapeHtml(coin)}</span>
        <span class="pos-amount">${amount.toFixed(6)}</span>
        <span class="pos-value">${fmtRp(value)}</span>
      </div>
    `;
  }).join("");
}

function renderInventory(matrix) {
  if (!matrix) return;

  const total = Number(matrix.total_slots || 0);
  const used = Number(matrix.used_slots || 0);
  const score = Number.isFinite(Number(matrix.utilization_score))
    ? Number(matrix.utilization_score)
    : (total > 0 ? used / total : 0);
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));

  const scoreEl = byId("inventory-score") || byId("inv-count");
  if (scoreEl) {
    scoreEl.textContent = total > 0 ? `${pct}%` : "--%";
    scoreEl.title = total > 0 ? `${used}/${total} inventory checks active` : "waiting for inventory telemetry";
  }

  const bar = byId("inventory-bar") || byId("inv-bar");
  if (bar) bar.style.width = `${pct}%`;

  const details = byId("inv-details");
  if (details) {
    const caps = matrix.captured_opportunities || 0;
    const rej = matrix.rejected_today || 0;
    details.textContent = `· cap ${caps} · rej ${rej}`;
  }
}

function renderSourceHealth(sources) {
  const container = byId("source-health-list");
  if (!container || !sources) return;

  container.innerHTML = Object.entries(sources).map(([name, data]) => {
    const payload = data && typeof data === "object" ? data : { health: String(data || "unknown") };
    const health = String(payload.health || payload.status || "unknown").toLowerCase();
    const lat = payload.avg_latency ? `${(payload.avg_latency * 1000).toFixed(0)}ms` : "--";
    return `
      <div class="source-tag">
        <div class="source-dot ${health}"></div>
        <span>${escapeHtml(name)} <small>${lat}</small></span>
      </div>
    `;
  }).join("");
}

function renderDrift(drift) {
  const el = byId("drift-status");
  if (!el || !drift) return;

  const status = String(drift.status || "SYNCED").toUpperCase();
  el.textContent = status.replace(/_/g, " ");
  el.className = status;
}

function renderBets(bets) {
  if (!bets || !bets.length) {
    return `<div class="empty-row">No active bets</div>`;
  }
  return bets.slice(0, 5).map((bet) => {
    const name = String(bet.market_id || bet.symbol || bet.title || "market").slice(0, 15);
    const amount = Number(bet.size_usdc || bet.amount || 0);
    return `
      <div class="position-row">
        <span class="pos-coin">${escapeHtml(name)}</span>
        <span class="pos-amount">USDC</span>
        <span class="pos-value">$${amount.toFixed(2)}</span>
      </div>
    `;
  }).join("");
}

function eventKey(event) {
  return [
    event.agent || event.title || "Event",
    event.tag || event.level || "INFO",
    event.message || event.detail || "",
  ].join("::");
}

function rememberEvents(feed, seen, events, limit = 80) {
  events.forEach((event) => {
    const key = eventKey(event);
    if (seen.has(key)) return;
    seen.add(key);
    feed.unshift({
      ...event,
      time: event.time || new Date().toISOString(),
    });
  });
  feed.splice(limit);
}

function buildCandidateEvents(data) {
  const portfolio = data?.portfolio || {};
  const council = data?.council || {};
  const world = data?.world_model || {};
  const system = data?.system || {};
  const brain = data?.brain || {};
  const services = data?.services || {};
  const intel = data?.strategy_intelligence || {};
  const scanner = data?.scanner_candidates || {};
  const journal = data?.decision_journal || {};
  const events = Array.isArray(data?.events) ? data.events.slice(0, 24) : [];

  const generated = [
    {
      agent: "Portfolio",
      tag: "INFO",
      message: `Equity ${fmtRp(portfolio.combined_equity_idr || 0)} | cash ${fmtRp(portfolio.idr_cash || 0)} | coin ${fmtRp(portfolio.coin_holdings_idr || 0)}`,
    },
    {
      agent: "Council",
      tag: council.decision_state === "ENTER" ? "SUCCESS" : "INFO",
      message: `${String(council.decision_state || "WAIT").toUpperCase()} | ${council.ticker || "no ticker"} | conf ${Number(council.confidence || 0).toFixed(2)}`,
    },
    {
      agent: "Deadline",
      tag: ["URGENT", "LOCK_GREEN"].includes(String(intel.deadline_mode || "").toUpperCase()) ? "WARN" : "INFO",
      message: `${intel.deadline_mode || "PATIENT"} | risk ${intel.allowed_risk_mode || "NORMAL"} | gate ${intel.required_trade_quality || "NORMAL"}`,
    },
    {
      agent: "Scanner",
      tag: Number(scanner.total || 0) > 0 ? "SUCCESS" : "INFO",
      message: `${scanner.total || 0} candidates | journal E/W/X ${journal.entries || 0}/${journal.waits || 0}/${journal.exits || 0}`,
    },
    {
      agent: "Probability",
      tag: Number(intel.green_probability_pct || 0) >= 60 ? "SUCCESS" : "INFO",
      message: `green ${intel.green_probability_pct || 0}% | breadth ${intel.market_breadth || "UNKNOWN"}`,
    },
    {
      agent: "Market",
      tag: "INFO",
      message: `${world.market_regime || "NEUTRAL"} | risk ${world.risk_level || "LOW"}`,
    },
    {
      agent: "Brain",
      tag: String(brain.status || "").toLowerCase() === "error" ? "ERROR" : "INFO",
      message: `${String(brain.posture || "NEUTRAL").toUpperCase()} | risk ${brain.risk || "MIXED"}`,
    },
    {
      agent: "Janitor",
      tag: Number(system.disk || 0) > 88 ? "WARN" : "INFO",
      message: `CPU ${Number(system.cpu || 0).toFixed(1)}% | RAM ${Number(system.ram || 0).toFixed(1)}% | Disk ${Number(system.disk || 0).toFixed(1)}%`,
    },
    {
      agent: "System",
      tag: "INFO",
      message: `master:${services["kibot-master"] || "--"} | scanner:${services["kibot-scanner"] || "--"} | executor:${services["kibot-executor"] || "--"}`,
    },
  ];

  return [...generated, ...events].slice(0, 60);
}

function logTime(event) {
  if (event.time) {
    const parsed = new Date(event.time);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleTimeString("id-ID", { hour12: false });
    }
  }
  return new Date().toLocaleTimeString("id-ID", { hour12: false });
}

function renderLogList(targetId, events, technical = false) {
  const list = byId(targetId);
  if (!list) return;
  if (!events.length) {
    list.innerHTML = `<div class="log-empty">NO ${technical ? "TECHNICAL" : "ACTIVITY"} DATA...</div>`;
    return;
  }

  list.innerHTML = events.map((event) => {
    const agent = event.agent || event.title || "Event";
    const tag = String(event.tag || event.level || "INFO").toUpperCase();
    const color = LOG_COLORS[agent] || "var(--ink-soft)";
    return `
      <div class="log-item">
        <span class="log-time">${escapeHtml(logTime(event))}</span>
        <div>
          <div class="log-agent" style="color:${color}">${escapeHtml(agent)}</div>
          <div class="log-message">${escapeHtml(event.message || event.detail || "")}</div>
        </div>
        <span class="log-tag ${escapeHtml(tag)}">${escapeHtml(tag)}</span>
      </div>
    `;
  }).join("");
}

function renderLogs(data) {
  const candidates = buildCandidateEvents(data);
  const technicalCandidates = [
    ...candidates.filter((item) => ["System", "Janitor", "Brain"].includes(item.agent)),
    ...Object.entries(data?.services || {}).map(([service, status]) => ({
      agent: "System",
      tag: status === "active" ? "SUCCESS" : "WARN",
      message: `${service}: ${status}`,
    })),
  ];

  rememberEvents(activityFeed, seenActivityKeys, candidates, 80);
  rememberEvents(technicalFeed, seenTechnicalKeys, technicalCandidates, 80);

  renderLogList("activity-log", activityFeed, false);
  renderLogList("technical-log", technicalFeed, true);
}

function renderWhatif(items) {
  const holder = byId("whatif-list");
  if (!holder) return;
  if (!items || !items.length) {
    holder.innerHTML = "No data yet";
    return;
  }
  holder.innerHTML = items.slice(0, 4).map((item) => {
    if (typeof item === "string") return `<div>${escapeHtml(item)}</div>`;
    const label = item.pair || item.symbol || item.market || item.name || "opportunity";
    const score = item.score || item.ev || item.expected_value || item.confidence || "";
    return `<div>${escapeHtml(label)}${score ? ` · ${escapeHtml(score)}` : ""}</div>`;
  }).join("");
}


/* ── §17.2 Signal Intel Panel ── */
function renderSignalIntel(data) {
  const signal = data?.council?.last_signal || data?.last_signal || {};
  if (!signal || !signal.pair) return;

  const lifecycle = String(signal.lifecycle || "").toUpperCase();
  const grade     = String(signal.trade_grade || "?").toUpperCase();
  const conf      = Number(signal.confidence || 0);
  const pair      = String(signal.pair || signal.symbol || "").toUpperCase();
  const breakdown = signal.confidence_breakdown || {};
  const exitQ     = String(signal.exit_quality || "--");

  // Lifecycle badge
  const lcBadge = byId("si-lifecycle");
  if (lcBadge) {
    lcBadge.textContent = lifecycle || "--";
    lcBadge.className = `lifecycle-badge ${lifecycle}`;
  }

  // Grade badge
  const gBadge = byId("si-grade");
  if (gBadge) {
    gBadge.textContent = grade;
    gBadge.className = `grade-badge ${grade}`;
  }

  updateText("si-pair", pair || "no signal");

  // Confidence bar
  const bar = byId("si-conf-bar");
  if (bar) bar.style.width = `${Math.round(conf * 100)}%`;

  // Breakdown chips
  const bdEl = byId("si-breakdown");
  if (bdEl && typeof breakdown === "object" && Object.keys(breakdown).length) {
    bdEl.innerHTML = Object.entries(breakdown).map(([k, v]) => {
      const val = Number(v);
      const tier = val >= 0.7 ? "high" : val >= 0.4 ? "med" : "low";
      const dot  = val >= 0.7 ? "✓" : val >= 0.4 ? "·" : "✗";
      return `<span class="breakdown-chip ${tier}">${dot} ${escapeHtml(k.replace(/_/g, " "))} ${(val * 100).toFixed(0)}%</span>`;
    }).join("");
  } else if (bdEl) {
    bdEl.innerHTML = "";
  }

  updateText("si-exit-quality", exitQ);
}

/* ── §16.2 Order Tracker Panel ── */
function renderOrderTracker(data) {
  const ot = data?.order_tracker || {};
  const summary = ot.today_summary || {};
  const openOrders = Array.isArray(ot.open_orders) ? ot.open_orders : [];

  updateText("ot-total",       String(summary.total       ?? 0), false);
  updateText("ot-filled",      String(summary.filled      ?? 0), false);
  updateText("ot-reconciled",  String(summary.reconciled  ?? 0), false);

  const staleEl = byId("ot-stale");
  const staleN  = Number(summary.stale ?? 0);
  if (staleEl) {
    staleEl.textContent = String(staleN);
    staleEl.classList.toggle("ot-warn", staleN > 0);
  }

  const pnlEl = byId("ot-pnl");
  const pnl   = Number(summary.pnl_idr ?? 0);
  if (pnlEl) {
    pnlEl.textContent = fmtRp(pnl);
    pnlEl.className   = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral";
  }

  // Open order rows
  const listEl = byId("ot-open-orders");
  if (!listEl) return;
  if (!openOrders.length) {
    listEl.innerHTML = "";
    return;
  }
  listEl.innerHTML = openOrders.slice(0, 5).map((o) => {
    const pair    = String(o.pair || "--").toUpperCase();
    const state   = String(o.state || "").toUpperCase();
    const budget  = Number(o.budget_idr || 0);
    return `
      <div class="ot-order-row">
        <span class="ot-order-pair">${escapeHtml(pair)}</span>
        <span class="ot-order-state ${escapeHtml(state)}">${escapeHtml(state)}</span>
        <span class="ot-order-budget">${fmtRp(budget)}</span>
      </div>
    `;
  }).join("");
}

function renderSummary(data) {
  const snapshot = data || {};
  lastSummary = snapshot;
  const portfolio = snapshot.portfolio || {};
  const poly = portfolio.polymarket || {};
  const strategy = snapshot.strategy || {};
  const indoStrategy = strategy.indodax || {};
  const council = snapshot.council || {};
  const system = snapshot.system || {};
  const services = snapshot.services || {};
  const dailyContext = snapshot.daily_context || {};
  const strategyIntel = snapshot.strategy_intelligence || {};
  const greenProbability = snapshot.green_probability || {};

  const dailyColor = String(portfolio.daily_color || portfolio.daily_state?.color || "FLAT").toUpperCase();
  const badge = byId("state-badge");
  if (badge) badge.className = `state-pill ${dailyColor}`;
  updateText("state-text", dailyColor);
  updateText("combined-equity", fmtRp(portfolio.combined_equity_idr || 0));
  updateText("equity-breakdown", `cash ${fmtRp(portfolio.idr_cash || 0)} · koin ${fmtRp(portfolio.coin_holdings_idr || 0)}`);
  const pnlRealVal = Number(portfolio.daily_pnl_real_idr || 0);
  const pnlSimVal = Number(portfolio.daily_pnl_sim_idr || 0);

  updateText("daily-pnl-real", fmtRp(pnlRealVal));
  updateText("daily-pnl-sim", fmtRp(pnlSimVal));
  updateText("portfolio-source", portfolio.daily_state?.reason || "live portfolio", false);

  const realEl = byId("daily-pnl-real");
  if (realEl) {
    realEl.className = pnlRealVal > 0 ? "positive" : pnlRealVal < 0 ? "negative" : "neutral";
  }
  const simEl = byId("daily-pnl-sim");
  if (simEl) {
    simEl.className = pnlSimVal > 0 ? "positive" : pnlSimVal < 0 ? "negative" : "neutral";
  }

  updateText("indo-total", fmtRp(portfolio.equity_idr || 0));
  updateText("indo-cash", `cash ${fmtRp(portfolio.idr_cash || 0)}`);
  updateText("indo-holdings", `koin ${fmtRp(portfolio.coin_holdings_idr || 0)}`);
  const indoPositions = byId("indo-positions");
  if (indoPositions) indoPositions.innerHTML = renderPositions(portfolio.active_positions || []);

  const mock = portfolio.mock || {};
  updateText("indo-mock-total", fmtRp(mock.equity_idr || 0));
  updateText("indo-mock-cash", `cash ${fmtRp(mock.idr_cash || 0)}`);
  updateText("indo-mock-holdings", `koin ${fmtRp(mock.coin_holdings_idr || 0)}`);
  const indoMockPositions = byId("indo-mock-positions");
  const activeMock = mock.active_positions || [];
  if (indoMockPositions) indoMockPositions.innerHTML = renderPositions(activeMock);
  byId("no-mock-label")?.classList.toggle("visible", !activeMock.length);

  updateText("poly-total", `$${Number(poly.usdc_balance || 0).toFixed(2)} USDC`);
  updateText("poly-idr", `~ ${fmtRp(poly.equity_idr || 0)}`);
  const polyPositions = byId("poly-positions");
  const activeBets = poly.active_bets || [];
  if (polyPositions) polyPositions.innerHTML = renderBets(activeBets);
  byId("no-bets-label")?.classList.toggle("visible", !activeBets.length);

  const phantom = portfolio.phantom || {};
  const phantomOpps = phantom.opportunities || [];
  updateText("phantom-total", `Sim: ${phantomOpps.length || 0} opps`);
  updateText("phantom-subline", `RPC: ${phantom.rpc_latency ? (phantom.rpc_latency * 1000).toFixed(0) + 'ms' : '--'}`);
  const phantomPositions = byId("phantom-positions");
  if (phantomPositions) phantomPositions.innerHTML = renderBets(phantomOpps); // using renderBets for similar struct
  byId("no-phantom-label")?.classList.toggle("visible", !phantomOpps.length);

  updateText("strategy-mode", String(strategy.global_mode || "UNKNOWN").toUpperCase());
  updateText("s-conf", Number(indoStrategy.min_confidence || 0).toFixed(2));
  updateText("s-tp", `${Number(indoStrategy.take_profit_pct || 0).toFixed(2)}%`);
  updateText("s-slots", `${Object.keys(snapshot.active_trades || {}).length}/${indoStrategy.max_slots || 100}`);
  updateText("s-stop", `${Number(indoStrategy.hard_stop_pct ?? -1.5).toFixed(2)}% day`);
  updateText("s-deadline", String(dailyContext.deadline_mode || strategyIntel.deadline_mode || "--").toUpperCase());
  updateText("s-risk-mode", String(dailyContext.allowed_risk_mode || strategyIntel.allowed_risk_mode || "--").toUpperCase());
  updateText("s-quality", String(dailyContext.required_trade_quality || strategyIntel.required_trade_quality || "--").toUpperCase());
  updateText("s-green-prob", `${Number(greenProbability.estimated_green_probability_pct || strategyIntel.green_probability_pct || 0).toFixed(0)}%`);

  const decision = String(council.decision_state || "WAIT").toUpperCase();
  const lens = byId("council-lens");
  if (lens) lens.className = `council-lens ${decision}`;
  updateText("cl-state", decision);
  updateText("cl-detail", `${council.ticker || "no ticker"} · ${council.action || "NONE"} · conf ${Number(council.confidence || 0).toFixed(2)}`);

  renderWhatif(snapshot.whatif?.top || []);
  updateText("sys-cpu", `${Number(system.cpu || 0).toFixed(1)}%`);
  updateText("sys-ram", `${Number(system.ram || 0).toFixed(1)}%`);
  updateText("sys-disk", `${Number(system.disk || 0).toFixed(1)}%`);
  updateText("sys-ollama", services.ollama || "--");
  updateText("sys-redis", services["redis-server"] || "--");

  const critical = ["kibot-master", "kibot-scanner", "kibot-executor", "ollama", "redis-server"];
  const ready = critical.every((service) => services[service] === "active");
  updateText("readiness-pill", ready ? "READY" : "ATTENTION", false);
  byId("readiness-pill")?.classList.toggle("warn", !ready);
  updateText("agency-count", String(Object.keys(window.KiBotCanvas?.AGENTS || {}).length || 7), false);

  renderLogs(snapshot);
  renderSignalIntel(snapshot);
  renderOrderTracker(snapshot);
  renderIntelligenceGates(snapshot);

  const brain = snapshot.system_brain || {};
  renderInventory(brain.inventory_matrix);
  renderSourceHealth(brain.source_health);
  renderDrift(brain.config_drift);

  window.KiBotCanvas?.render(snapshot);
}

function renderIntelligenceGates(snapshot) {
  const director = snapshot.autonomous_director || {};
  const cycleStats = director.cycle_stats || {};
  
  // Update regime and badges
  updateText("ig-regime", `REGIME: ${cycleStats.market_regime || "UNKNOWN"}`);
  
  const liveBadge = byId("ig-live-badge");
  if (liveBadge) {
    if (cycleStats.live_trading_enabled) {
      liveBadge.classList.add("active");
    } else {
      liveBadge.classList.remove("active");
    }
  }

  const canaryBadge = byId("ig-canary-badge");
  if (canaryBadge) {
    if (cycleStats.canary_enabled) {
      canaryBadge.classList.add("active");
    } else {
      canaryBadge.classList.remove("active");
    }
  }

  // Deliberation stats
  updateText("ig-stat-approved", cycleStats.approved_count || 0);
  updateText("ig-stat-paper", cycleStats.paper_count || 0);
  updateText("ig-stat-rejected", cycleStats.rejected_count || 0);

  // Parse candidate list or focus on the latest/active signal candidates
  const evList = snapshot.expected_value || [];
  const sqList = snapshot.signal_quality || [];
  const ssList = snapshot.strategy_scorecard || [];

  // Expected Value Gate
  const evStatus = byId("ev-status");
  if (evStatus) {
    if (evList.length > 0) {
      const latestEv = evList[evList.length - 1];
      const evDecisionStr = latestEv.approved ? "PASS" : "REJECT";
      updateText("ev-projected-profit", `${(latestEv.ev_pct || 0).toFixed(2)}%`);
      updateText("ev-kelly-rec", `${((latestEv.kelly_fraction || 0) * 100).toFixed(1)}%`);
      updateText("ev-decision", evDecisionStr);
      evStatus.innerText = evDecisionStr;
      evStatus.className = `layer-status-pill ${latestEv.approved ? "pass" : "fail"}`;
      byId("gate-layer-ev")?.classList.add("active-signal");
    } else {
      updateText("ev-projected-profit", "--");
      updateText("ev-kelly-rec", "--");
      updateText("ev-decision", "--");
      evStatus.innerText = "WAIT";
      evStatus.className = "layer-status-pill neutral";
      byId("gate-layer-ev")?.classList.remove("active-signal");
    }
  }

  // Signal Quality Gate
  const sqStatus = byId("sq-status");
  if (sqStatus) {
    if (sqList.length > 0) {
      const latestSq = sqList[sqList.length - 1];
      const isSpreadOk = latestSq.spread_ok ? "PASS" : "FAIL";
      const isVolumeOk = latestSq.volume_ok ? "PASS" : "FAIL";
      const isAlignOk = latestSq.leadlag_aligned ? "PASS" : "FAIL";
      updateText("sq-spread", isSpreadOk);
      updateText("sq-volume", isVolumeOk);
      updateText("sq-alignment", isAlignOk);
      
      const isPass = latestSq.grade === "PASS";
      sqStatus.innerText = latestSq.grade || "REJECT";
      sqStatus.className = `layer-status-pill ${isPass ? "pass" : "fail"}`;
      byId("gate-layer-sq")?.classList.add("active-signal");
    } else {
      updateText("sq-spread", "--");
      updateText("sq-volume", "--");
      updateText("sq-alignment", "--");
      sqStatus.innerText = "WAIT";
      sqStatus.className = "layer-status-pill neutral";
      byId("gate-layer-sq")?.classList.remove("active-signal");
    }
  }

  // Strategy Scorecard Gate
  const ssStatus = byId("ss-status");
  if (ssStatus) {
    if (ssList.length > 0) {
      const latestSs = ssList[ssList.length - 1];
      const isPass = latestSs.verdict === "PASS" || latestSs.verdict === "APPROVED";
      updateText("ss-grade", latestSs.composite_score ? latestSs.composite_score.toFixed(3) : "0.000");
      updateText("ss-weight", latestSs.regime_score ? `${(latestSs.regime_score * 100).toFixed(0)}%` : "0%");
      updateText("ss-verdict", latestSs.verdict || "WAIT");
      ssStatus.innerText = latestSs.verdict || "WAIT";
      ssStatus.className = `layer-status-pill ${isPass ? "pass" : "fail"}`;
      byId("gate-layer-ss")?.classList.add("active-signal");
    } else {
      updateText("ss-grade", "--");
      updateText("ss-weight", "--");
      updateText("ss-verdict", "--");
      ssStatus.innerText = "WAIT";
      ssStatus.className = "layer-status-pill neutral";
      byId("gate-layer-ss")?.classList.remove("active-signal");
    }
  }

  // Punishment Engine Gate
  const peStatus = byId("pe-status");
  if (peStatus) {
    const punishment = director.punishment_engine || {};
    const strikes = punishment.strikes || 0;
    const isCooling = punishment.is_cooling_off || false;
    
    updateText("pe-strikes", `${strikes} / 3`);
    updateText("pe-cooloff", isCooling ? "ACTIVE" : "None");
    
    peStatus.innerText = isCooling ? "BLOCKED" : strikes > 0 ? "WARNING" : "PASS";
    peStatus.className = `layer-status-pill ${isCooling ? "fail" : strikes > 0 ? "neutral" : "pass"}`;
  }
}

async function poll() {
  const response = await fetch("/api/summary", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`summary request failed with ${response.status}`);
  }
  renderSummary(await response.json());
}

function startFallbackPolling() {
  if (fallbackPollTimer) return;
  fallbackPollTimer = window.setInterval(() => poll().catch(() => {}), 8000);
}

function startStream() {
  if (!window.EventSource) {
    startFallbackPolling();
    poll().catch(() => {});
    return;
  }

  if (streamInstance) {
    streamInstance.close();
  }

  streamInstance = new EventSource("/api/stream");
  streamInstance.onmessage = (event) => {
    try {
      renderSummary(JSON.parse(event.data));
    } catch (error) {
      console.warn("Dashboard stream parse failed", error);
    }
  };
  streamInstance.onerror = () => {
    streamInstance?.close();
    streamInstance = null;
    if (streamRetryTimer) return;
    streamRetryTimer = window.setTimeout(() => {
      streamRetryTimer = null;
      startFallbackPolling();
      poll().catch(() => {});
    }, 2000);
  };
}

function bindUi() {
  document.querySelectorAll("[data-log-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll("[data-log-tab]").forEach((el) => el.classList.remove("active"));
      document.querySelectorAll(".log-scroll").forEach((el) => el.classList.remove("active"));
      button.classList.add("active");
      byId(`${button.dataset.logTab}-log`)?.classList.add("active");
    });
  });

  byId("clear-local-feed")?.addEventListener("click", () => {
    activityFeed = [];
    technicalFeed = [];
    seenActivityKeys.clear();
    seenTechnicalKeys.clear();
    if (lastSummary) renderLogs(lastSummary);
  });
}

window.KiBotLive = {
  fmtRp,
  renderSummary,
  updateText,
};

renderClock();
setInterval(renderClock, 1000);
bindUi();
poll().catch(() => {});
startStream();
