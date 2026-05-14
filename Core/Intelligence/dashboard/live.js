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

  const dailyColor = String(portfolio.daily_color || portfolio.daily_state?.color || "FLAT").toUpperCase();
  const badge = byId("state-badge");
  if (badge) badge.className = `state-pill ${dailyColor}`;
  updateText("state-text", dailyColor);
  updateText("combined-equity", fmtRp(portfolio.combined_equity_idr || 0));
  updateText("equity-breakdown", `cash ${fmtRp(portfolio.idr_cash || 0)} · koin ${fmtRp(portfolio.coin_holdings_idr || 0)}`);
  updateText("daily-pnl", fmtRp(portfolio.daily_pnl_idr || 0));
  updateText("portfolio-source", portfolio.daily_state?.reason || "live portfolio", false);

  const pnlEl = byId("daily-pnl");
  if (pnlEl) {
    const pnl = Number(portfolio.daily_pnl_idr || 0);
    pnlEl.className = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral";
  }

  updateText("indo-total", fmtRp(portfolio.equity_idr || 0));
  updateText("indo-cash", `cash ${fmtRp(portfolio.idr_cash || 0)}`);
  updateText("indo-holdings", `koin ${fmtRp(portfolio.coin_holdings_idr || 0)}`);
  const indoPositions = byId("indo-positions");
  if (indoPositions) indoPositions.innerHTML = renderPositions(portfolio.active_positions || []);

  updateText("poly-total", `$${Number(poly.usdc_balance || 0).toFixed(2)} USDC`);
  updateText("poly-idr", `~ ${fmtRp(poly.equity_idr || 0)}`);
  const polyPositions = byId("poly-positions");
  const activeBets = poly.active_bets || [];
  if (polyPositions) polyPositions.innerHTML = renderBets(activeBets);
  byId("no-bets-label")?.classList.toggle("visible", !activeBets.length);

  updateText("strategy-mode", String(strategy.global_mode || "UNKNOWN").toUpperCase());
  updateText("s-conf", Number(indoStrategy.min_confidence || 0).toFixed(2));
  updateText("s-tp", `${Number(indoStrategy.take_profit_pct || 0).toFixed(2)}%`);
  updateText("s-slots", `${Object.keys(snapshot.active_trades || {}).length}/${indoStrategy.max_slots || 100}`);
  updateText("s-stop", `${Number(indoStrategy.hard_stop_pct ?? -1.5).toFixed(2)}% day`);

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
  window.KiBotCanvas?.render(snapshot);
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
