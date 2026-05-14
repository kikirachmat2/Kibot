const fmtIdr = new Intl.NumberFormat("id-ID", {
  style: "currency",
  currency: "IDR",
  maximumFractionDigits: 0,
});

const agentColors = {
  Portfolio: "var(--text2)",
  Council: "var(--council)",
  Scanner: "var(--scanner)",
  Executor: "var(--indo)",
  Janitor: "var(--janitor)",
  Market: "var(--blue)",
  Log: "var(--text2)",
};

function byId(id) {
  return document.getElementById(id);
}

function fmtRp(value) {
  const amount = Number(value || 0);
  if (Math.abs(amount) >= 1_000_000_000) return `Rp ${(amount / 1_000_000_000).toFixed(2)}M`;
  if (Math.abs(amount) >= 1_000_000) return `Rp ${(amount / 1_000_000).toFixed(1)}jt`;
  return fmtIdr.format(amount);
}

function fmtPct(value) {
  const amount = Number(value || 0);
  return `${amount >= 0 ? "+" : ""}${amount.toFixed(2)}%`;
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
  const clock = byId("clock");
  if (clock) {
    clock.textContent = `${String(wib.getHours()).padStart(2, "0")}:${String(wib.getMinutes()).padStart(2, "0")}:${String(wib.getSeconds()).padStart(2, "0")} WIB`;
  }

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
    const name = String(bet.market_id || bet.symbol || bet.title || "market").slice(0, 12);
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

function renderTrail(events) {
  const list = byId("trail-list");
  if (!list) return;
  list.innerHTML = (events || []).slice(0, 40).map((event) => {
    const agent = event.agent || event.title || "Event";
    const tag = String(event.tag || event.level || "INFO").toUpperCase();
    const time = event.time ? new Date(event.time).toLocaleTimeString("id-ID", { hour12: false }) : new Date().toLocaleTimeString("id-ID", { hour12: false });
    const color = agentColors[agent] || "var(--text2)";
    return `
      <div class="trail-item">
        <span class="trail-time">${escapeHtml(time)}</span>
        <div>
          <div class="trail-agent" style="color:${color}">${escapeHtml(agent)}</div>
          <div class="trail-msg">${escapeHtml(event.message || event.detail || "")}</div>
        </div>
        <span class="trail-tag ${tag}">${escapeHtml(tag)}</span>
      </div>
    `;
  }).join("");
}

function renderWhatif(items) {
  const holder = byId("whatif-list");
  if (!holder) return;
  if (!items || !items.length) {
    holder.innerHTML = "No data yet";
    return;
  }
  holder.innerHTML = items.slice(0, 3).map((item) => {
    if (typeof item === "string") return `<div>${escapeHtml(item)}</div>`;
    const label = item.pair || item.symbol || item.market || item.name || "opportunity";
    const score = item.score || item.ev || item.expected_value || item.confidence || "";
    return `<div>${escapeHtml(label)} ${score ? `· ${escapeHtml(score)}` : ""}</div>`;
  }).join("");
}

function renderSummary(data) {
  const portfolio = data.portfolio || {};
  const poly = portfolio.polymarket || {};
  const strategy = data.strategy || {};
  const indoStrategy = strategy.indodax || {};
  const council = data.council || {};
  const system = data.system || {};
  const services = data.services || {};

  const dailyColor = String(portfolio.daily_color || "FLAT").toUpperCase();
  const badge = byId("state-badge");
  if (badge) badge.className = `state-pill ${dailyColor}`;
  updateText("state-text", dailyColor);
  updateText("combined-equity", fmtRp(portfolio.combined_equity_idr || 0));
  updateText("equity-breakdown", `cash ${fmtRp(portfolio.idr_cash || 0)} · koin ${fmtRp(portfolio.coin_holdings_idr || 0)}`);
  updateText("daily-pnl", fmtRp(portfolio.daily_pnl_idr || 0));
  const pnlEl = byId("daily-pnl");
  if (pnlEl) pnlEl.className = Number(portfolio.daily_pnl_idr || 0) > 0 ? "positive" : Number(portfolio.daily_pnl_idr || 0) < 0 ? "negative" : "neutral";

  updateText("indo-total", fmtRp(portfolio.equity_idr || 0));
  updateText("indo-cash", `cash ${fmtRp(portfolio.idr_cash || 0)}`);
  updateText("indo-holdings", `koin ${fmtRp(portfolio.coin_holdings_idr || 0)}`);
  const indoPositions = byId("indo-positions");
  if (indoPositions) indoPositions.innerHTML = renderPositions(portfolio.active_positions || []);

  updateText("poly-total", `$${Number(poly.usdc_balance || 0).toFixed(2)} USDC`);
  updateText("poly-idr", `~ ${fmtRp(poly.equity_idr || 0)}`);
  const polyPositions = byId("poly-positions");
  if (polyPositions) polyPositions.innerHTML = renderBets(poly.active_bets || []);

  updateText("strategy-mode", strategy.global_mode || "UNKNOWN");
  updateText("s-conf", Number(indoStrategy.min_confidence || 0).toFixed(2));
  updateText("s-tp", `${indoStrategy.take_profit_pct || 0}%`);
  updateText("s-slots", `${Object.keys(data.active_trades || {}).length}/${indoStrategy.max_slots || 100}`);
  updateText("s-stop", `${indoStrategy.hard_stop_pct || -1.5}% day`);

  const decision = String(council.decision_state || "WAIT").toUpperCase();
  const lens = byId("council-lens");
  if (lens) lens.className = `council-lens ${decision}`;
  updateText("cl-state", decision);
  updateText("cl-detail", `${council.ticker || "no ticker"} · ${council.action || "NONE"} · conf ${Number(council.confidence || 0).toFixed(2)}`);

  renderWhatif(data.whatif?.top || []);
  updateText("sys-cpu", `${Number(system.cpu || 0).toFixed(1)}%`);
  updateText("sys-ram", `${Number(system.ram || 0).toFixed(1)}%`);
  updateText("sys-disk", `${Number(system.disk || 0).toFixed(1)}%`);
  updateText("sys-ollama", services.ollama || "--");
  updateText("sys-redis", services["redis-server"] || "--");
  renderTrail(data.events || []);

  window.KiBotCanvas?.render(data);
}

async function poll() {
  const data = await fetch("/api/summary", { cache: "no-store" }).then((r) => r.json());
  renderSummary(data);
}

function startStream() {
  if (!window.EventSource) {
    setInterval(() => poll().catch(() => {}), 8000);
    poll().catch(() => {});
    return;
  }
  const stream = new EventSource("/api/stream");
  stream.onmessage = (event) => {
    try {
      renderSummary(JSON.parse(event.data));
    } catch (error) {
      console.warn("Dashboard stream parse failed", error);
    }
  };
  stream.onerror = () => {
    stream.close();
    setTimeout(() => {
      poll().catch(() => {});
      setInterval(() => poll().catch(() => {}), 8000);
    }, 2000);
  };
}

renderClock();
setInterval(renderClock, 1000);
poll().catch(() => {});
startStream();

window.KiBotLive = { fmtRp, renderSummary };
