const escapeHtml = (str) => {
  if (typeof str !== "string") return str;
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
};

const AGENTS = {
  operator: {
    label: "Kiki / Operator",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "The sovereign operator. Sets policy, approves live gate, monitors all agents. Controlled-live mode active on Batam node.",
    metric(summary) {
      return summary?.mode?.live_trading_enabled ? "live active" : "view active";
    }
  },
  council: {
    label: "Sovereign Council",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "High-level deliberation chamber. Aggregates and debates predictions, scanner data, and sentiment before approving order execution.",
    metric(summary) {
      const c = summary?.council || {};
      return `conf ${Number(c.confidence || 0).toFixed(2)}`;
    }
  },
  director: {
    label: "Autonomous Director",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "Core state orchestrator. Reads signal qualities and EV gates. Issues WAIT, APPROVE, or REJECT decisions based on rules.",
    metric(summary) {
      const d = summary?.autonomous_director || {};
      return d.status || "WAIT";
    }
  },
  risk: {
    label: "RiskGate Shield",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "Safety gate enforcing 1.5% maximum daily drawdown. Blocks all downstream order execution if drawdown is breached.",
    metric(summary) {
      const rg = summary?.gates?.risk_gate || {};
      return `${rg.max_drawdown_limit || 1.5}% cap`;
    }
  },
  scanner: {
    label: "Scanner",
    service: "kibot-scanner",
    runtime: "systemd: kibot-scanner",
    copy: "Scans Indodax orderbooks and tickers for momentum and cross-asset lead-lag anomalies. Sends candidates to LeadLag engine.",
    metric(summary) {
      const candidates = Number(summary?.scanner_candidates?.total || 0);
      if (candidates > 0) return `${candidates} candidates`;
      const count = Number(summary?.whatif?.count || 0);
      return count > 0 ? `${count} signals` : "scan live";
    }
  },
  leadlag: {
    label: "LeadLag Alpha",
    service: "kibot-scanner",
    runtime: "systemd: kibot-scanner",
    copy: "Computes high-speed lead-lag correlations between major assets (BTC/ETH) and altcoins to detect leading momentum.",
    metric(summary) {
      const sq = summary?.gates?.signal_quality || {};
      return sq.score != null ? `score: ${Number(sq.score).toFixed(2)}` : "active";
    }
  },
  ev: {
    label: "Expected Value Gate",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "Evaluates candidate trades based on expected value (EV) after fees. Blocks execution if EV is negative or below threshold.",
    metric(summary) {
      const ev = summary?.gates?.expected_value || {};
      return ev.score != null ? `${Number(ev.score).toFixed(2)} EV` : "wait";
    }
  },
  scorecard: {
    label: "Strategy Scorecard",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "Grades strategies against current market regimes and recent trade outcomes. Submits composite scorecard to Council.",
    metric(summary) {
      const g = summary?.gates?.strategy_scorecard || {};
      return g.score != null ? `score: ${Number(g.score).toFixed(2)}` : "idle";
    }
  },
  indodax_real: {
    label: "Indodax Spot",
    service: "kibot-executor",
    runtime: "systemd: kibot-executor",
    copy: "Controlled-live exchange order placement with RiskGate and Capital Governor enforcement.",
    metric(summary) {
      return summary?.mode?.live_trading_enabled ? "live active" : "live off";
    }
  },
  indodax_shadow: {
    label: "Indodax Shadow",
    service: "kibot-executor",
    runtime: "systemd: kibot-executor",
    copy: "Shadow accounting for internal analysis only.",
    metric(summary) {
      return "active";
    }
  },
  phantom: {
    label: "Phantom Treasury",
    service: "kibot-scanner",
    runtime: "systemd: kibot-scanner",
    copy: "Treasury and route visibility for Phantom multichain capital.",
    metric(summary) {
      return "live route";
    }
  },
  polymarket: {
    label: "Polymarket",
    service: "kibot-executor-polymarket",
    runtime: "systemd: kibot-executor-polymarket",
    copy: "Prediction market control with guarded settlement-aware lifecycle.",
    metric(summary) {
      const poly = summary?.venues?.polymarket || {};
      return poly.usdc_balance != null ? `$${Number(poly.usdc_balance).toFixed(2)}` : "live route";
    }
  },
  pnl_feedback: {
    label: "PnL Feedback",
    service: "kibot-janitor",
    runtime: "systemd: kibot-janitor",
    copy: "Post-trade feedback analyzer. Reviews execution quality and adjusts expected value coefficients.",
    metric(summary) {
      return "tracking";
    }
  },
  cashwait: {
    label: "Cash Wait Reserve",
    service: "kibot-janitor",
    runtime: "systemd: kibot-janitor",
    copy: "Liquidity reservoir tracking idle assets waiting for high-conviction opportunities. Prevents over-trading.",
    metric(summary) {
      const cw = summary?.portfolio?.cash_wait || {};
      return cw.equity_idr ? `Rp ${(cw.equity_idr / 1e6).toFixed(1)}M` : "Rp 0.0M";
    }
  },
  punishment: {
    label: "Punishment Gate",
    service: "kibot-janitor",
    runtime: "systemd: kibot-janitor",
    copy: "Monitors execution failures and consecutive losses. Imposes cooling-off periods and quarantines underperforming pathways.",
    metric(summary) {
      const p = summary?.gates?.punishment || {};
      return `${p.strikes || 0} STRIKES`;
    }
  }
};

let selectedAgent = "council";
let latestSummary = null;

const mapId = (id) => id.replace(/_/g, "-");

function normalizedStatus(status) {
  const value = String(status || "unknown").toLowerCase();
  if (value === "active" || value === "running" || value === "pass") return "active";
  if (value === "failed" || value === "inactive" || value === "error" || value === "reject") return "error";
  return "idle";
}

function statusLabel(status) {
  const normalized = normalizedStatus(status);
  if (normalized === "active") return "ACTIVE";
  if (normalized === "error") return "DOWN";
  return "IDLE";
}

function setAgentClass(id, status, summary) {
  const cardId = `card-${mapId(id)}`;
  const el = document.getElementById(cardId);
  if (!el) return;

  const normalized = normalizedStatus(status);
  
  // Safely toggle selected class
  el.classList.toggle("selected", id === selectedAgent);

  let active = false;
  let error = false;
  let thinking = false;

  if (id === "council") {
    const decision = String(summary?.council?.decision_state || "WAIT").toUpperCase();
    if (decision === "ENTER" || decision === "BUY" || decision === "APPROVE") active = true;
    else if (decision === "EXIT" || decision === "REJECTED") error = true;
    else thinking = true;
  } else if (normalized === "active") {
    active = true;
  } else if (normalized === "error") {
    error = true;
  }

  el.classList.toggle("active", active);
  el.classList.toggle("error", error);
  el.classList.toggle("thinking", thinking);

  // Update card status element if present
  const statusEl = document.getElementById(`${mapId(id)}-status`);
  if (statusEl) {
    statusEl.textContent = statusLabel(status);
  }
}

function updateMetric(id, summary) {
  const metricId = `${mapId(id)}-metric`;
  const el = document.getElementById(metricId);
  if (!el) return;
  el.textContent = AGENTS[id].metric(summary);
}

function renderSelectedAgent(summary) {
  const agent = AGENTS[selectedAgent] || AGENTS.scanner;
  const serviceStatus = summary?.services?.[agent.service] || "unknown";
  const metric = agent.metric(summary);

  const setElText = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  setElText("selected-agent-title", agent.label);
  setElText("selected-agent-copy", agent.copy);
  setElText("selected-agent-status", statusLabel(serviceStatus));
  setElText("selected-agent-metric", metric);
  setElText("selected-agent-runtime", agent.runtime);
}

function renderAgentPills(services) {
  const holder = document.getElementById("agent-pills");
  if (!holder) return;
  holder.innerHTML = Object.entries(AGENTS).map(([id, agent]) => {
    const status = services?.[agent.service] || "unknown";
    const tone = normalizedStatus(status) === "active" ? "active" : normalizedStatus(status) === "error" ? "down" : "";
    return `<button type="button" class="agent-pill ${tone}" data-agent-select="${id}">
      ${escapeHtml(agent.label)}: ${escapeHtml(statusLabel(status))}
    </button>`;
  }).join("");
}

function taskCard(title, detail, tone = "") {
  return `<button type="button" class="task-card ${tone}" data-task="${escapeHtml(title)}">
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(detail)}</span>
  </button>`;
}

function renderLane(id, countId, tasks) {
  const holder = document.getElementById(id);
  const count = document.getElementById(countId);
  if (!holder) return;
  if (count) count.textContent = String(tasks.length);
  holder.innerHTML = tasks.length ? tasks.join("") : `<div class="task-card"><strong>EMPTY</strong><span>waiting</span></div>`;
}

function renderWorkflow(summary) {
  const services    = summary?.services    || {};
  const portfolio   = summary?.portfolio   || {};
  const council     = summary?.council     || {};
  const strategy    = summary?.strategy    || {};
  const signal      = summary?.last_signal || summary?.council?.last_signal || {};
  const scanner     = summary?.scanner_candidates || {};
  const dailyCtx    = summary?.daily_context || {};
  const probability = summary?.green_probability || {};
  const journal     = summary?.decision_journal || {};
  const ot          = summary?.order_tracker || {};
  const openOrders  = Array.isArray(ot.open_orders) ? ot.open_orders : [];
  const otSummary   = ot.today_summary || {};

  const activeTrades = Object.keys(summary?.active_trades || {}).length;
  const decision     = String(council.decision_state || "WAIT").toUpperCase();
  
  const commander   = summary?.commander || {};
  const drift       = String(commander.drift || "UNKNOWN").toUpperCase();
  const providers   = commander.providers || {};
  const totalProviders = Object.keys(providers).length;
  let activeProviders = 0;
  const nowSec = Date.now() / 1000;
  for (const p of Object.values(providers)) {
      if (!p.cooldown_until || p.cooldown_until < nowSec) activeProviders++;
  }

  // ── SCHEDULED: scanner candidates + world scout ──
  const scheduledCards = [
    taskCard(
      "World Scout",
      `${statusLabel(services["kibot-ai-scout"])} · ${summary?.world_model?.market_regime || "NEUTRAL"}`,
      normalizedStatus(services["kibot-ai-scout"]) === "active" ? "live" : ""
    ),
    taskCard("What-If Batch", `${summary?.whatif?.count || 0} pairs scanned`),
    taskCard("Scanner Slate", `${scanner.total || 0} live candidates`, Number(scanner.total || 0) ? "live" : ""),
    taskCard("Deadline Brain", `${dailyCtx.deadline_mode || "PATIENT"} · ${dailyCtx.allowed_risk_mode || "NORMAL"}`),
  ];
  if (signal?.pair) {
    const lifecycle = String(signal.lifecycle || "--").toUpperCase();
    const grade     = String(signal.trade_grade || "?");
    const conf      = Number(signal.confidence || 0);
    scheduledCards.push(
      taskCard(
        `🎯 ${String(signal.pair || "").toUpperCase()}`,
        `${lifecycle} · grade ${grade} · conf ${(conf * 100).toFixed(0)}%`,
        grade === "A" || grade === "B" ? "live" : ""
      )
    );
  }
  renderLane("cards-scheduled", "cnt-scheduled", scheduledCards);

  // ── ON HOLD: council waiting ──
  renderLane("cards-hold", "cnt-hold", decision === "WAIT"
    ? [
        taskCard("Council Holding", `conf ${Number(council.confidence || 0).toFixed(2)} below gate`),
        taskCard("Green Probability", `${Number(probability.estimated_green_probability_pct || 0).toFixed(0)}% · ${probability.confidence_quality || "WEAK"}`),
      ]
    : []);

  // ── IN PROGRESS: scanner + deliberation + open orders ──
  const progressCards = [
    taskCard("Scanner Stream", statusLabel(services["kibot-scanner"]), "live"),
    taskCard("Council Deliberation", `${decision} · ${council.ticker || "no ticker"}`, "live"),
    taskCard("Execution Watch", `${activeTrades} active trades`, activeTrades ? "live" : ""),
    taskCard("Decision Journal", `E/W/X ${journal.entries || 0}/${journal.waits || 0}/${journal.exits || 0}`, "live"),
  ];
  openOrders.slice(0, 3).forEach((o) => {
    const pair  = String(o.pair || "--").toUpperCase();
    const state = String(o.state || "").toUpperCase();
    const budget = Number(o.budget_idr || 0);
    progressCards.push(
      taskCard(
        `📦 ${pair}`,
        `${state} · ${window.KiBotLive?.fmtRp?.(budget) || "Rp --"}`,
        state === "FILLED" ? "live" : state === "STALE" ? "" : "live"
      )
    );
  });
  renderLane("cards-progress", "cnt-progress", progressCards);

  // ── DONE: ledger + reconciled trades ──
  const doneCards = [
    taskCard("System Commander", `Drift: ${drift} · ${activeProviders}/${totalProviders} AI Active`, drift === "SYNCED" ? "done" : (drift === "UNKNOWN" ? "" : "error")),
    taskCard("Ledger Snapshot", window.KiBotLive?.fmtRp?.(portfolio.combined_equity_idr || 0) || "portfolio", "done"),
    taskCard("Risk Contract", strategy.global_mode || "strategy loaded", "done"),
  ];
  const reconciled = Number(otSummary.reconciled || 0);
  const pnl        = Number(otSummary.pnl_idr || 0);
  if (reconciled > 0) {
    doneCards.push(
      taskCard(
        `✅ ${reconciled} reconciled`,
        `PnL ${window.KiBotLive?.fmtRp?.(pnl) || "Rp --"}`,
        "done"
      )
    );
  }
  renderLane("cards-done", "cnt-done", doneCards);
}

function bindCanvasInteractions() {
  const layer = document.getElementById("delegation-layer");
  if (layer) {
    layer.addEventListener("click", (event) => {
      const card = event.target.closest("[data-agent-id]");
      if (!card) return;
      if (window.KiBotLive && typeof window.KiBotLive.isDragging === "function" && window.KiBotLive.isDragging()) return;
      selectedAgent = card.dataset.agentId;
      window.KiBotCanvas.render(latestSummary || {});
    });
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-agent-select]");
    if (!button) return;
    selectedAgent = button.dataset.agentSelect;
    window.KiBotCanvas.render(latestSummary || {});
  });
}

window.KiBotCanvas = {
  AGENTS,
  init: bindCanvasInteractions,
  render(summary) {
    latestSummary = summary || {};
    const services = latestSummary.services || {};
    Object.entries(AGENTS).forEach(([id, agent]) => {
      setAgentClass(id, services[agent.service], latestSummary);
      updateMetric(id, latestSummary);
    });
    renderSelectedAgent(latestSummary);
    renderAgentPills(services);
    renderWorkflow(latestSummary);
  },
};

document.addEventListener("DOMContentLoaded", () => {
  window.KiBotCanvas.init();
});
