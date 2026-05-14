const AGENT_LABELS = {
  "kibot-scanner": ["SCANNER", "scanner"],
  "kibot-master": ["COUNCIL", "council"],
  "kibot-executor": ["INDO EXEC", "indo"],
  "kibot-executor-polymarket": ["POLY EXEC", "poly"],
  "kibot-janitor": ["JANITOR", "janitor"],
  "ollama": ["OLLAMA", "brain"],
  "redis-server": ["REDIS", "verifier"],
};

function agentClassFromStatus(status) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "active" || normalized === "running") return "active";
  if (normalized === "failed" || normalized === "inactive" || normalized === "error") return "error";
  return "";
}

function setAgentState(agentId, status, metric) {
  const char = document.getElementById(`char-${agentId}`);
  const metricEl = document.getElementById(`metric-${agentId}`);
  if (!char) return;

  if (!char.classList.contains("thinking")) {
    char.className = `agent-char ${agentClassFromStatus(status)}`.trim();
  }
  if (metricEl) {
    metricEl.textContent = metric || "";
  }
}

function renderAgentPills(services) {
  const holder = document.getElementById("agent-pills");
  if (!holder) return;

  holder.innerHTML = Object.entries(AGENT_LABELS).map(([service, config]) => {
    const [label] = config;
    const status = services?.[service] || "unknown";
    const tone = status === "active" ? "active" : status === "unknown" ? "" : "down";
    return `<span class="agent-pill ${tone}">${label}: ${String(status).toUpperCase()}</span>`;
  }).join("");
}

window.KiBotCanvas = {
  render(summary) {
    const services = summary?.services || {};
    const portfolio = summary?.portfolio || {};
    const poly = portfolio.polymarket || {};
    const council = summary?.council || {};
    const system = summary?.system || {};
    const brain = summary?.brain || {};
    const world = summary?.world_model || {};

    setAgentState("scanner", services["kibot-scanner"], "scan live");
    setAgentState("indo", services["kibot-executor"], window.KiBotLive?.fmtRp?.(portfolio.equity_idr || 0) || "Rp --");
    setAgentState("poly", services["kibot-executor-polymarket"], `$${Number(poly.usdc_balance || 0).toFixed(2)}`);
    setAgentState("janitor", services["kibot-janitor"], `disk ${Number(system.disk || 0).toFixed(0)}%`);
    setAgentState("brain", services.ollama, brain.risk || "MIXED");
    setAgentState("verifier", services["redis-server"], `${Object.keys(summary?.active_trades || {}).length} trades`);

    const councilChar = document.getElementById("char-council");
    if (councilChar) {
      const decision = String(council.decision_state || "WAIT").toUpperCase();
      if (decision === "ENTER" || decision === "BUY" || decision === "APPROVE") {
        councilChar.className = "agent-char active";
      } else if (decision === "EXIT" || decision === "REJECTED") {
        councilChar.className = "agent-char error";
      } else {
        councilChar.className = "agent-char thinking";
      }
    }
    const councilMetric = document.getElementById("metric-council");
    if (councilMetric) {
      councilMetric.textContent = `conf ${Number(council.confidence || 0).toFixed(2)}`;
    }

    renderAgentPills(services);

    const worldChip = document.getElementById("world-regime");
    if (worldChip) {
      worldChip.textContent = `${world.market_regime || "NEUTRAL"} · risk ${world.risk_level || "LOW"}`;
    }
  },
};
