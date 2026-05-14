const fmtIdr = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

const fmtPct = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

const state = {
  lastSummary: null,
  lastCanvas: null,
  lastEvents: [],
  stream: null,
  fallbackTimer: null,
  connected: false,
};

function byId(id) {
  return document.getElementById(id);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatIDR(value) {
  const num = Number(value ?? 0);
  return fmtIdr.format(Number.isFinite(num) ? num : 0);
}

function formatUSDC(value) {
  const num = Number(value ?? 0);
  return `${Number.isFinite(num) ? num.toFixed(4) : "0.0000"} USDC`;
}

function formatPct(value) {
  const num = Number(value ?? 0);
  const safe = Number.isFinite(num) ? num : 0;
  return `${safe >= 0 ? "+" : ""}${fmtPct.format(safe)}%`;
}

function formatTime(value) {
  if (!value) return "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString("id-ID", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString("id-ID", {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

function toneClass(tone) {
  switch ((tone || "").toLowerCase()) {
    case "success":
      return "success";
    case "thinking":
      return "thinking";
    case "warn":
      return "warn";
    case "error":
    case "danger":
      return "danger";
    default:
      return "info";
  }
}

function nodeToneClass(status) {
  switch ((status || "").toLowerCase()) {
    case "active":
    case "running":
    case "live":
    case "ok":
      return "active";
    case "thinking":
    case "deliberating":
    case "evaluating":
      return "thinking";
    case "warning":
    case "warn":
    case "degraded":
      return "warn";
    case "error":
    case "failed":
    case "inactive":
      return "error";
    default:
      return "idle";
  }
}

function updateText(id, value, { flash = true } = {}) {
  const el = byId(id);
  if (!el) return;
  const next = value ?? "—";
  if (el.textContent !== next) {
    el.textContent = next;
    if (flash) {
      el.classList.remove("value-flash");
      void el.offsetWidth;
      el.classList.add("value-flash");
    }
  }
}

function updateHtml(id, html) {
  const el = byId(id);
  if (!el) return;
  if (el.innerHTML !== html) {
    el.innerHTML = html;
  }
}

function setStateChip(el, stateName) {
  if (!el) return;
  el.classList.remove("state-chip--green", "state-chip--recovery", "state-chip--flat");
  const tone = (stateName || "FLAT").toUpperCase();
  if (tone === "GREEN") el.classList.add("state-chip--green");
  else if (tone === "RECOVERY") el.classList.add("state-chip--recovery");
  else el.classList.add("state-chip--flat");
  el.textContent = tone;
}

function setPulseByTone(el, tone) {
  if (!el) return;
  el.classList.remove("pulse", "pulse--thinking", "pulse--warn");
  if (tone === "success") el.classList.add("pulse");
  if (tone === "thinking") el.classList.add("pulse", "pulse--thinking");
  if (tone === "warn") el.classList.add("pulse", "pulse--warn");
}

function setToneClass(id, tone) {
  const el = byId(id);
  if (!el) return;
  el.classList.remove("tone-good", "tone-warn", "tone-danger", "tone-info");
  if (tone === "good") el.classList.add("tone-good");
  else if (tone === "warn") el.classList.add("tone-warn");
  else if (tone === "danger") el.classList.add("tone-danger");
  else el.classList.add("tone-info");
}

function renderSummary(summary) {
  if (!summary) return;
  state.lastSummary = summary;

  const portfolio = summary.portfolio || {};
  const dailyState = portfolio.daily_state || {};
  const council = summary.council || {};
  const strategy = summary.strategy || {};
  const brain = summary.brain || {};
  const systemStats = summary.system_stats || {};
  const batam = (systemStats.BATAM_MASTER || {});
  const providerHealth = summary.provider_health || {};
  const services = summary.services || {};

  setStateChip(byId("header-state-chip"), dailyState.color || "FLAT");
  updateText("header-clock", summary.market_clock?.wib || "WIB");
  updateText("header-countdown", `deadline ${summary.market_clock?.label || "--"}`);
  updateText("header-combined-equity", formatIDR(portfolio.combined_equity_idr));
  updateText("header-daily-pnl", formatIDR(portfolio.daily_pnl_idr));
  updateText("header-updated", `updated ${formatDateTime(summary.generated_at)}`);
  updateText("canvas-posture", `${dailyState.color || "FLAT"} / ${summary.market_clock?.pressure || "LOW"}`);
  updateText("canvas-pulse", `heartbeat ${summary.heartbeat || "UNKNOWN"} · ${summary.service_counts?.active || 0}/${summary.service_counts?.total || 0} services`);
  updateText("header-live-gate", `live ${strategy.global_mode || "unknown"}`);

  updateText("portfolio-daily-state", `${dailyState.color || "FLAT"} · ${dailyState.reason || "state"}`);
  updateText("portfolio-daily-state-badge", `${summary.market_clock?.pressure || "LOW"} pressure`);
  updateText("portfolio-combined", formatIDR(portfolio.combined_equity_idr));
  updateText("portfolio-indodax-balance", formatIDR(portfolio.indodax?.cash_idr));
  updateText("portfolio-poly-balance", formatUSDC(portfolio.polymarket?.usdc_balance));

  updateText("portfolio-indodax-equity", formatIDR(portfolio.indodax?.equity_idr));
  updateText("portfolio-indodax-pnl", `Daily PnL: ${formatIDR(portfolio.indodax?.pnl_idr)} · ${formatPct(portfolio.indodax?.pnl_pct)}`);
  updateText("portfolio-indodax-positions", `${portfolio.indodax?.active_positions_count || 0} positions · cash aware`);
  updateText("portfolio-poly-equity", formatIDR(portfolio.polymarket?.equity_idr));
  updateText("portfolio-poly-pnl", `Daily PnL: ${formatIDR(portfolio.polymarket?.pnl_idr)}`);
  updateText("portfolio-poly-bets", `${portfolio.polymarket?.active_bets_count || 0} active bets`);

  updateText("council-decision", council.decision_state || "WAIT");
  updateText("council-confidence", fmtPct.format(Number(council.confidence || 0)));
  updateText("council-scores", `${fmtPct.format(Number(council.enter_score || 0))} / ${fmtPct.format(Number(council.wait_score || 0))} / ${fmtPct.format(Number(council.exit_score || 0))}`);
  updateText("council-deadline", council.deadline_pressure || "LOW");
  updateText("council-whatif", `${council.whatif_state || "UNKNOWN"} · ${fmtPct.format(Number(council.whatif_confidence || 0))}`);
  updateText("council-mandate", council.mandate || council.reason || "Council is observing the tape.");

  updateText("strategy-mode", strategy.global_mode || "UNKNOWN");
  updateText("strategy-confidence", `floor ${fmtPct.format(Number(strategy?.indodax?.min_confidence || 0))}`);
  updateText("strategy-slots", `${portfolio.indodax?.active_positions_count || 0} / ${strategy?.indodax?.max_slots ?? "∞"}`);
  updateText("strategy-risk", `${formatPct(strategy?.indodax?.take_profit_pct || 0)} / ${formatPct(strategy?.indodax?.hard_stop_pct || 0)}`);

  updateText("brain-sentiment", brain.sentiment || "UNKNOWN");
  updateText("brain-risk", brain.risk_level || "UNKNOWN");
  updateText("brain-posture", brain.suggested_posture || "UNKNOWN");
  updateText("service-summary", `${summary.service_counts?.active || 0} active / ${summary.service_counts?.total || 0} total`);
  updateText("provider-summary", `${providerHealth.active || 0} active · ${providerHealth.cooling || 0} cooling`);
  updateText("feed-updated", summary.market_clock?.pressure || "LIVE");
  updateText("snapshot-age", formatDateTime(summary.generated_at));
  updateText("snapshot-telemetry", summary.snapshots?.telemetry_snapshot || "missing");
  updateText("snapshot-runtime", summary.snapshots?.runtime_note || "missing");
  updateText("snapshot-whatif", summary.snapshots?.whatif_results || "missing");
  updateText("snapshot-world", summary.snapshots?.world_model || "missing");

  updateText("provider-healthy-count", `${providerHealth.active || 0} healthy / ${providerHealth.total || 0}`);
  setToneClass("portfolio-daily-state-badge", dailyState.color === "GREEN" ? "good" : dailyState.color === "RECOVERY" ? "warn" : "info");
  setToneClass("header-live-gate", strategy.global_mode === "EXIT_ALL" ? "danger" : strategy.global_mode === "FULL_ATTACK" ? "warn" : strategy.global_mode === "CONTROLLED_AGGRESSIVE" ? "good" : "info");
  const maxSlots = Number(strategy?.indodax?.max_slots ?? 0);
  const activeSlots = Number(portfolio.indodax?.active_positions_count || 0);
  setToneClass("strategy-slots", maxSlots > 0 && activeSlots > maxSlots ? "warn" : "good");
  setToneClass("council-decision", ["ENTER", "BUY", "APPROVE", "EXECUTING"].includes(String(council.decision_state || "").toUpperCase()) ? "good" : String(council.decision_state || "").toUpperCase() === "REJECTED" ? "danger" : "info");
  setToneClass("portfolio-indodax-pnl", Number(portfolio.indodax?.pnl_pct || 0) >= 0 ? "good" : "warn");
  setToneClass("portfolio-poly-pnl", Number(portfolio.polymarket?.pnl_idr || 0) >= 0 ? "good" : "warn");

  const activeLegs = [
    ...(portfolio.indodax?.active_positions || []).map((item) => ({
      source: "INDODAX",
      symbol: item.symbol || item.coin || "unknown",
      amount: item.amount,
      entry: item.entry,
      pnl: item.pnl_pct,
      tone: Number(item.pnl_pct || 0) > 0 ? "positive" : Number(item.pnl_pct || 0) < 0 ? "negative" : "neutral",
    })),
    ...(portfolio.polymarket?.active_bets || []).map((item) => ({
      source: "POLY",
      symbol: item.symbol || item.market_id || "unknown",
      amount: item.amount || item.size_usdc,
      entry: item.entry,
      pnl: item.pnl_pct,
      tone: Number(item.pnl_pct || 0) > 0 ? "positive" : Number(item.pnl_pct || 0) < 0 ? "negative" : "neutral",
    })),
  ];
  updateText("active-leg-count", `${activeLegs.length}`);
  updateText("active-leg-note", activeLegs.length ? "live legs" : "idle");
  updateHtml("active-leg-list", activeLegs.length ? activeLegs.slice(0, 8).map((item) => {
    const entryValue = item.entry != null ? `entry ${item.entry}` : "no entry";
    const pnlValue = item.pnl != null ? formatPct(item.pnl) : "n/a";
    const amountValue = item.source === "INDODAX"
      ? (String(item.symbol || "").toLowerCase() === "idr"
        ? formatIDR(item.amount)
        : `${item.amount ?? "—"} ${String(item.symbol || "").toUpperCase()}`)
      : (item.source === "POLY" ? formatUSDC(item.amount) : String(item.amount ?? "—"));
    return `
      <div class="active-leg-row active-leg-row--${item.tone}">
        <div class="active-leg-row__left">
          <div class="active-leg-row__symbol">${escapeHtml(item.symbol)}</div>
          <div class="active-leg-row__meta">${escapeHtml(item.source)} · ${escapeHtml(entryValue)}</div>
        </div>
        <div class="active-leg-row__right">
          <div class="active-leg-row__value">${escapeHtml(amountValue)}</div>
          <div class="active-leg-row__tag">${escapeHtml(pnlValue)}</div>
        </div>
      </div>
    `;
  }).join("") : `
    <div class="active-leg-row active-leg-row--neutral">
      <div class="active-leg-row__left">
        <div class="active-leg-row__symbol">No active legs</div>
        <div class="active-leg-row__meta">Both books are currently flat.</div>
      </div>
      <div class="active-leg-row__right">
        <div class="active-leg-row__value">0</div>
        <div class="active-leg-row__tag">idle</div>
      </div>
    </div>
  `);

  const btcHeadlines = brain.headlines || [];
  const headlineHtml = btcHeadlines.length
    ? btcHeadlines.slice(0, 5).map((line) => `<div class="headline-item"><span class="headline-item__bullet"></span><div class="headline-item__text">${escapeHtml(line)}</div></div>`).join("")
    : `<div class="headline-item"><span class="headline-item__bullet"></span><div class="headline-item__text">No headlines available right now.</div></div>`;
  updateHtml("brain-headlines", headlineHtml);

  const serviceNames = [
    "kibot-master",
    "kibot-scanner",
    "kibot-executor",
    "kibot-executor-polymarket",
    "kibot-ai-scout",
    "kibot-janitor",
    "kibot-dashboard",
    "ollama",
    "redis-server",
  ];
  const serviceGrid = serviceNames.map((name) => {
    const svc = services[name] || {};
    const tone = toneClass(svc.tone || nodeToneClass(svc.status));
    return `
      <div class="service-pill service-pill--${tone}">
        <div class="service-pill__name">${escapeHtml(name)}</div>
        <div class="service-pill__status">${escapeHtml((svc.status || "unknown").toUpperCase())}</div>
      </div>
    `;
  }).join("");
  updateHtml("service-grid", serviceGrid);

  const providerRows = (providerHealth.details || []).slice(0, 8).map((provider) => {
    const tone = nodeToneClass(provider.status);
    return `
      <div class="provider-row provider-row--${tone}">
        <div class="provider-row__name">${escapeHtml(provider.name)}</div>
        <div class="provider-row__status">${escapeHtml(provider.status || "unknown")}</div>
      </div>
    `;
  }).join("");
  updateHtml("provider-list", providerRows || `
    <div class="provider-row provider-row--idle">
      <div class="provider-row__name">No provider data</div>
      <div class="provider-row__status">UNKNOWN</div>
    </div>
  `);

  const tradeCount = (portfolio.indodax?.active_positions_count || 0) + (portfolio.polymarket?.active_bets_count || 0);
  const liveGate = strategy?.global_mode === "EXIT_ALL"
    ? "exit gate"
    : strategy?.global_mode === "FULL_ATTACK"
      ? "aggressive"
      : strategy?.global_mode === "CONTROLLED_AGGRESSIVE"
        ? "controlled aggressive"
        : "live ready";
  updateText("header-live-gate", `${liveGate} · ${tradeCount} live legs`);

  const wm = summary.world_model || {};
  const wmInt = wm.intelligence || {};
  const mood = wmInt.market_sentiment || brain.sentiment || "UNKNOWN";
  document.documentElement.dataset.dailyState = dailyState.color || "FLAT";
  document.documentElement.dataset.marketMood = mood;
  document.documentElement.dataset.deadline = summary.market_clock?.pressure || "LOW";

  setPulseByTone(byId("header-state-chip"), toneClass(dailyState.color === "GREEN" ? "success" : dailyState.color === "RECOVERY" ? "warn" : "info"));
}

function renderCanvas(canvas) {
  if (!canvas) return;
  state.lastCanvas = canvas;
  const svg = byId("delegation-canvas");
  if (!svg) return;

  const width = Number(canvas.layout?.width || 1280);
  const height = Number(canvas.layout?.height || 560);
  const nodes = canvas.nodes || [];
  const edges = canvas.edges || [];

  const defs = `
    <defs>
      <filter id="node-glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="5" result="blur" />
        <feMerge>
          <feMergeNode in="blur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
      <marker id="arrow-green" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#00ff88"></path>
      </marker>
      <marker id="arrow-cyan" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#62d6ff"></path>
      </marker>
      <marker id="arrow-amber" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#ffbe00"></path>
      </marker>
      <marker id="arrow-purple" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="strokeWidth">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#a855f7"></path>
      </marker>
    </defs>
  `;

  const edgeMarkup = edges.map((edge) => {
    const tone = edge.tone || "idle";
    const toneMap = {
      active: "edge--active",
      thinking: "edge--thinking",
      warn: "edge--warn",
      error: "edge--error",
      idle: "edge",
    };
    const marker = tone === "active" ? "url(#arrow-green)" : tone === "thinking" ? "url(#arrow-cyan)" : tone === "warn" ? "url(#arrow-amber)" : "url(#arrow-purple)";
    return `
      <g class="edge-group">
        <path id="${escapeHtml(edge.id)}" class="edge ${toneMap[tone] || "edge"}" d="${escapeHtml(edge.path)}" marker-end="${marker}"></path>
        <text class="edge-label">
          <textPath href="#${escapeHtml(edge.id)}" startOffset="50%" text-anchor="middle">${escapeHtml(edge.label || "")}</textPath>
        </text>
      </g>
    `;
  }).join("");

  const nodeMarkup = nodes.map((node) => {
    const tone = nodeToneClass(node.status);
    const accent = String(node.accent || "cyan");
    const metrics = (node.metrics || []).slice(0, 3).map((metric, index) => {
      const y = 84 + (index * 19);
      return `
        <text x="20" y="${y}" class="node__metric-label">${escapeHtml(metric.label || "")}</text>
        <text x="82" y="${y}" class="node__metric-value">${escapeHtml(metric.value ?? "")}</text>
      `;
    }).join("");
    return `
      <g class="node node--${tone} node--${escapeHtml(accent)}" transform="translate(${Number(node.x || 0)}, ${Number(node.y || 0)})">
        <rect class="node__rect" rx="20" ry="20" width="${Number(node.w || 220)}" height="${Number(node.h || 120)}"></rect>
        <circle cx="24" cy="24" r="11" fill="rgba(255,255,255,0.05)" stroke="rgba(255,255,255,0.12)"></circle>
        <text x="19" y="30" class="node__icon">${escapeHtml(node.icon || "•")}</text>
        <text x="44" y="30" class="node__label">${escapeHtml(node.label || "")}</text>
        <rect x="${Number(node.w || 220) - 88}" y="14" width="66" height="20" rx="10" class="node__badge"></rect>
        <text x="${Number(node.w || 220) - 55}" y="28" text-anchor="middle" class="node__badge-text">${escapeHtml(node.badge || "LIVE")}</text>
        <text x="20" y="56" class="node__headline">${escapeHtml(node.headline || "")}</text>
        ${metrics}
        <text x="20" y="${Number(node.h || 120) - 14}" class="node__note">${escapeHtml(node.note || "")}</text>
      </g>
    `;
  }).join("");

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = defs + edgeMarkup + nodeMarkup;
}

function renderEvents(events) {
  state.lastEvents = events || [];
  const feed = byId("event-feed");
  if (!feed) return;
  if (!events || !events.length) {
    feed.innerHTML = `
      <div class="feed-event feed-event--info">
        <div class="feed-event__time">${formatTime(new Date().toISOString())}</div>
        <div class="feed-event__icon">•</div>
        <div>
          <div class="feed-event__title">Idle</div>
          <div class="feed-event__detail">No fresh events yet. Dashboard still polling the sovereign state.</div>
        </div>
      </div>
    `;
    return;
  }

  feed.innerHTML = events.slice(0, 28).map((event) => {
    const tone = toneClass(event.tone);
    const timeLabel = formatTime(event.timestamp || new Date().toISOString());
    return `
      <div class="feed-event feed-event--${tone}">
        <div class="feed-event__time">${escapeHtml(timeLabel)}</div>
        <div class="feed-event__icon">${escapeHtml(event.icon || "•")}</div>
        <div>
          <div class="feed-event__title">${escapeHtml(event.title || "Event")}</div>
          <div class="feed-event__detail">${escapeHtml(event.detail || "")}</div>
        </div>
      </div>
    `;
  }).join("");
}

async function fetchJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} ${url}`);
  }
  return response.json();
}

async function refreshSnapshot() {
  const [summary, canvas, events] = await Promise.all([
    fetchJson("/api/summary"),
    fetchJson("/api/canvas"),
    fetchJson("/api/events?limit=24"),
  ]);
  renderSummary(summary);
  renderCanvas(canvas);
  renderEvents(events.events || []);
}

function startStream() {
  if (!window.EventSource) {
    state.fallbackTimer = setInterval(() => {
      refreshSnapshot().catch(() => {});
    }, 8000);
    return;
  }

  if (state.stream) {
    state.stream.close();
  }

  const stream = new EventSource("/api/stream");
  state.stream = stream;

  stream.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      renderSummary({
        generated_at: payload.generated_at,
        portfolio: payload.portfolio,
        services: payload.services,
        council: payload.council,
        brain: payload.brain,
        world_model: payload.world_model,
        provider_health: payload.provider_health,
        snapshots: payload.snapshots,
        telemetry: payload.telemetry,
        runtime: payload.runtime,
        strategy: payload.strategy,
        whatif: payload.whatif,
        active_trades: payload.active_trades,
        market_clock: payload.market_clock,
        service_counts: payload.service_counts,
        heartbeat: payload.heartbeat,
        system_stats: payload.system_stats,
        status_text: payload.status_text,
      });
      renderCanvas(payload.canvas);
      renderEvents(payload.events || []);
      state.connected = true;
      updateText("feed-updated", payload.market_clock?.pressure || "LIVE");
    } catch (error) {
      console.warn("Failed to parse dashboard stream payload", error);
    }
  };

  stream.onerror = () => {
    if (state.connected) {
      state.connected = false;
      if (state.fallbackTimer) {
        clearInterval(state.fallbackTimer);
      }
      state.fallbackTimer = setInterval(() => {
        refreshSnapshot().catch(() => {});
      }, 8000);
    }
  };
}

window.addEventListener("load", async () => {
  try {
    await refreshSnapshot();
  } catch (error) {
    console.warn("Initial dashboard refresh failed", error);
  }
  startStream();
  setInterval(() => {
    if (!state.connected) {
      refreshSnapshot().catch(() => {});
    }
  }, 30000);
});
