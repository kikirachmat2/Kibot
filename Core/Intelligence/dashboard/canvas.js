const AGENTS = {
  scanner: {
    label: "Scanner",
    service: "kibot-scanner",
    runtime: "systemd: kibot-scanner",
    copy: "Membaca pergerakan market, volume, pump candidate, dan mengirim sinyal mentah ke Council.",
    metric(summary) {
      const count = Number(summary?.whatif?.count || 0);
      return count > 0 ? `${count} sims` : "scan live";
    },
  },
  brain: {
    label: "AI Brain",
    service: "ollama",
    runtime: "ollama local inference",
    copy: "Otak lokal untuk deliberation, critic, what-if, dan reasoning saat sinyal perlu validasi lebih dalam.",
    metric(summary) {
      return summary?.brain?.risk || "MIXED";
    },
  },
  council: {
    label: "Council",
    service: "kibot-master",
    runtime: "systemd: kibot-master",
    copy: "Tempat sinyal diperdebatkan. Council menggabungkan scanner, world model, risk gate, dan what-if sebelum mandate.",
    metric(summary) {
      return `conf ${Number(summary?.council?.confidence || 0).toFixed(2)}`;
    },
  },
  indodax: {
    label: "Indodax Executor",
    service: "kibot-executor",
    runtime: "systemd: kibot-executor",
    copy: "Eksekutor order IDR. Memegang saldo, posisi koin, sizing, entry, exit, dan hard stop Indodax.",
    metric(summary) {
      return window.KiBotLive?.fmtRp?.(summary?.portfolio?.equity_idr || 0) || "Rp --";
    },
  },
  polymarket: {
    label: "Polymarket Executor",
    service: "kibot-executor-polymarket",
    runtime: "systemd: kibot-executor-polymarket",
    copy: "Eksekutor market prediction via wallet Polygon/Phantom. Membaca saldo USDC dan state posisi Polymarket.",
    metric(summary) {
      return `$${Number(summary?.portfolio?.polymarket?.usdc_balance || 0).toFixed(2)}`;
    },
  },
  verifier: {
    label: "Verifier",
    service: "redis-server",
    runtime: "redis + state files",
    copy: "Mengecek hasil eksekusi, active trades, state Redis, dan bukti sistem benar-benar bergerak.",
    metric(summary) {
      return `${Object.keys(summary?.active_trades || {}).length} trades`;
    },
  },
  janitor: {
    label: "Janitor",
    service: "kibot-janitor",
    runtime: "systemd: kibot-janitor",
    copy: "Penjaga server: disk, log, proses, dan recovery supaya sistem tidak mati karena resource.",
    metric(summary) {
      return `disk ${Number(summary?.system?.disk || 0).toFixed(0)}%`;
    },
  },
};

let selectedAgent = "council";
let stageScale = 1;
let latestSummary = null;

const AGENT_ID_MAP = {
  indodax: "indo",
  polymarket: "poly",
};

function normalizedStatus(status) {
  const value = String(status || "unknown").toLowerCase();
  if (value === "active" || value === "running") return "active";
  if (value === "failed" || value === "inactive" || value === "error") return "error";
  return "idle";
}

function statusLabel(status) {
  const normalized = normalizedStatus(status);
  if (normalized === "active") return "ACTIVE";
  if (normalized === "error") return "DOWN";
  return "IDLE";
}

function setAgentClass(id, status, summary) {
  const el = document.getElementById(`char-${AGENT_ID_MAP[id] || id}`);
  if (!el) return;

  const normalized = normalizedStatus(status);
  const visualClass = AGENT_ID_MAP[id] || id;
  const classes = ["flow-node", visualClass];
  if (id === selectedAgent) classes.push("selected");

  if (id === "council") {
    const decision = String(summary?.council?.decision_state || "WAIT").toUpperCase();
    if (decision === "ENTER" || decision === "BUY" || decision === "APPROVE") classes.push("active");
    else if (decision === "EXIT" || decision === "REJECTED") classes.push("error");
    else classes.push("thinking");
  } else if (normalized === "active") {
    classes.push("active");
  } else if (normalized === "error") {
    classes.push("error");
  }

  el.className = classes.join(" ");
}

function updateMetric(id, summary) {
  const metricId = `metric-${AGENT_ID_MAP[id] || id}`;
  const el = document.getElementById(metricId);
  if (!el) return;
  el.textContent = AGENTS[id].metric(summary);
}

function renderSelectedAgent(summary) {
  const agent = AGENTS[selectedAgent] || AGENTS.scanner;
  const serviceStatus = summary?.services?.[agent.service] || "unknown";
  const metric = agent.metric(summary);

  window.KiBotLive?.updateText?.("selected-agent-title", agent.label, false);
  window.KiBotLive?.updateText?.("selected-agent-copy", agent.copy, false);
  window.KiBotLive?.updateText?.("selected-agent-status", statusLabel(serviceStatus), false);
  window.KiBotLive?.updateText?.("selected-agent-metric", metric, false);
  window.KiBotLive?.updateText?.("selected-agent-runtime", agent.runtime, false);
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
  const services = summary?.services || {};
  const portfolio = summary?.portfolio || {};
  const council = summary?.council || {};
  const strategy = summary?.strategy || {};
  const activeTrades = Object.keys(summary?.active_trades || {}).length;
  const decision = String(council.decision_state || "WAIT").toUpperCase();

  renderLane("lane-scheduled", "scheduled-count", [
    taskCard("World Scout", `${statusLabel(services["kibot-ai-scout"])} · ${summary?.world_model?.market_regime || "NEUTRAL"}`, normalizedStatus(services["kibot-ai-scout"]) === "active" ? "live" : ""),
    taskCard("What-If Batch", `${summary?.whatif?.count || 0} pairs simulated`),
  ]);

  renderLane("lane-hold", "hold-count", decision === "WAIT"
    ? [taskCard("Council Holding", `conf ${Number(council.confidence || 0).toFixed(2)} below gate`)]
    : []);

  renderLane("lane-progress", "progress-count", [
    taskCard("Scanner Stream", statusLabel(services["kibot-scanner"]), "live"),
    taskCard("Council Deliberation", `${decision} · ${council.ticker || "no ticker"}`, "live"),
    taskCard("Execution Watch", `${activeTrades} active trades`, activeTrades ? "live" : ""),
  ]);

  renderLane("lane-done", "done-count", [
    taskCard("Ledger Snapshot", window.KiBotLive?.fmtRp?.(portfolio.combined_equity_idr || 0) || "portfolio", "done"),
    taskCard("Risk Contract", strategy.global_mode || "strategy loaded", "done"),
  ]);
}

function bindCanvasInteractions() {
  document.querySelectorAll("[data-agent]").forEach((el) => {
    el.addEventListener("click", () => {
      selectedAgent = el.dataset.agent;
      window.KiBotCanvas.render(latestSummary || {});
    });
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-agent-select]");
    if (!button) return;
    selectedAgent = button.dataset.agentSelect;
    window.KiBotCanvas.render(latestSummary || {});
  });

  const drawer = document.getElementById("director-drawer");
  document.getElementById("open-director")?.addEventListener("click", () => drawer?.classList.add("open"));
  document.getElementById("drawer-close")?.addEventListener("click", () => drawer?.classList.remove("open"));
  drawer?.addEventListener("click", (event) => {
    if (event.target === drawer) drawer.classList.remove("open");
  });

  const stage = document.getElementById("office-stage");
  const applyScale = () => {
    if (stage) stage.style.transform = `scale(${stageScale})`;
  };
  document.getElementById("stage-zoom-in")?.addEventListener("click", () => {
    stageScale = Math.min(1.28, stageScale + 0.08);
    applyScale();
  });
  document.getElementById("stage-zoom-out")?.addEventListener("click", () => {
    stageScale = Math.max(0.76, stageScale - 0.08);
    applyScale();
  });
  document.getElementById("stage-reset")?.addEventListener("click", () => {
    stageScale = 1;
    applyScale();
  });
  document.getElementById("focus-stage")?.addEventListener("click", () => {
    document.getElementById("stage-shell")?.classList.toggle("focused");
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
