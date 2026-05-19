# 🗄️ KiBot Sovereign — Server Inventory
> **Server**: BrainSystem (Batam Master)  
> **Last Verified**: 2026-05-15  
> **Purpose**: Snapshot runtime server state yang tidak selalu terlihat dari repo source

---

## 🖥️ Server Snapshot
| Item | Value |
|------|-------|
| Hostname | BrainSystem |
| OS | Ubuntu 24.04.4 LTS (aarch64) |
| Kernel | 6.17.0-1011-oracle |
| CPU | 4 cores |
| RAM | 23Gi total |
| Disk | 184G root, sekitar 144G free setelah cleanup + model pulls terbaru |
| Python | 3.12.3 |
| Node.js | v18.19.1 |

---

## ⚙️ Live Services
### Core
| Service | Status | Catatan |
|---------|--------|---------|
| `kibot-master` | active | MasterNode / council supervisor |
| `kibot-executor` | active | Executor Indodax (canonical unit name) |
| `kibot-executor-polymarket` | active | Executor Polymarket |
| `kibot-ai-scout` | active | Intel / scouting loop |
| `kibot-janitor` | active | Disk/service self-healing |
| `kibot-dashboard` | active | Visual control plane / System Brain |
| `ollama` | active | Local AI server |
| `redis-server` | active | Runtime state store |

### Legacy / Auxiliary
| Service | Status | Catatan |
|---------|--------|---------|
| `kibot-trinity` | retired / masked | Service tambahan lama, tidak lagi dipakai sebagai jalur runtime |
| `kibot-commander` | retired / masked | Helper service lama |
| `kibot-notifier` | retired / masked | Helper service lama |
| `ki-telegram-monitor` | retired / masked | Helper service lama |
| `kibot-analyst`, `kibot-healer`, `kibot-monitor`, `kibot-orchestrator` | retired / disabled | Unit lama yang menunjuk path `Batam/...` yang sudah tidak ada |
| `kibot-guardian`, `kibot-security`, `kibot-sentiment` | retired / disabled | Unit lama non-canonical, digantikan SystemCommander / scout / dashboard health |
| `kibot-ollama-gateway`, `kibot-command-center`, `kibot-high-command`, `kibot-scanner-consolidated`, `kibot-governor` | retired / disabled | Duplicate/legacy daemons yang tidak lagi jadi sumber kebenaran runtime |
| `executor-healer.timer`, `kibot-memory-watchdog.timer`, `kibot-sovereign-backup.timer` | retired / disabled | Timer lama yang memicu failed legacy one-shot; digantikan janitor + pre-deploy backup |
| `kibot-batam-watchdog`, `kibot-batam-health-report`, `kibot-config-sanity`, `kibot-crashloop-guard` | retired / disabled | Server-only timers lama yang masih memanggil unit/path legacy; digantikan `kibot-janitor`, `SystemCommander`, dashboard, dan `bin/kibotctl` |

### Ports
| Port | Service | Protokol | Fungsi |
|------|---------|----------|--------|
| 9990 | PolymarketExecutor | UDP | Receive signals |
| 9991 | MasterNode Council | UDP | Council deliberation |
| 9998 | IndodaxExecutor | UDP | Receive signals |
| 11434 | Ollama | TCP | AI model API |
| 8787 | KiBot Dashboard | TCP | Visual control plane |
| 11600 | PolymarketExecutor | TCP | State API |
| 6379 | Redis | TCP | State store |
| 22 | SSH | TCP | Remote access |

---

## 🤖 AI Models (Ollama)
| Model | Status | Fungsi |
|-------|--------|--------|
| `qwen2.5:0.5b` | ✅ ADA | Fast watchman / quick analysis |
| `qwen2.5:1.5b` | ✅ ADA | Default council model |
| `qwen2.5:3b` | ✅ ADA | Pro tasks / liquidity hunting |
| `llama3.2:3b` | ✅ ADA | Sentiment / NLP |
| `qwen2.5-coder:3b` | ✅ ADA | Code specialist / wrapper generation |
| `nomic-embed-text:latest` | ✅ ADA | Embeddings / RAG |
| `deepseek-r1:7b` | ✅ ADA | Heavy reasoning |
| `mistral:7b` | ✅ ADA | Bridge / synthesis |

> Catatan: semua model inti sudah dipull; `ollama ps` sempat menunjukkan `qwen2.5:1.5b` aktif saat validasi.

---

## 🔑 API Keys / Env Status
### Loaded at runtime
| Variable | Status | Catatan |
|----------|--------|---------|
| `INDODAX_API_KEY` | SET | Trading API |
| `INDODAX_API_SECRET` | SET | Signing |
| `KIBOT_TELEGRAM_TOKEN` | SET | Telegram alerts |
| `KIBOT_TELEGRAM_CHAT_ID` | SET | Telegram target |
| `GEMINI_API_KEY` | SET | AI fallback |
| `GROQ_API_KEY` | SET | AI fallback |
| `CEREBRAS_API_KEY` | SET | AI fallback |
| `MISTRAL_API_KEY` | SET | AI fallback |
| `OPENROUTER_API_KEY` | SET | AI gateway |
| `TAVILY_API_KEY` | SET | Web search |
| `SERPER_API_KEY` | SET | Web search |
| `FINNHUB_API_KEY` | SET | Market news |
| `JINA_API_KEY` | SET | Search / scrape |
| `COHERE_API_KEY` | SET | AI fallback |
| `POLYMARKET_WALLET_ADDRESS` | SET | Wallet EVM untuk Polymarket |
| `POLYMARKET_PRIVATE_KEY` | SET | Private key Phantom/EVM untuk eksekusi Polymarket |
| `KIBOT_LIVE_TRADING_ENABLED` | SET / TRUE | Gate entry real-money |
| `KIBOT_TRADING_MODE` | live | Explicit operator mode |

---

## 🔍 Web Search / Intelligence Sources
| Source | Library / API | Status | Catatan |
|--------|---------------|--------|---------|
| Tavily | `tavily-python` | ✅ | Deep search / catalyst |
| Serper | `requests` | ✅ | Google-result style search |
| DuckDuckGo | `ddgs` / `duckduckgo-search` | ✅ | Free search |
| Finnhub | `finnhub-python` | ✅ | Crypto / market news |
| Jina AI | `httpx` | ✅ | Scrape / semantic fetch |

---

## 📦 Python Packages Kritis
| Package | Status | Catatan |
|---------|--------|---------|
| `httpx` | ✅ | Async HTTP client |
| `aiohttp` | ✅ | Async HTTP server/client |
| `cryptography` | ✅ | Vault / crypto |
| `psutil` | ✅ | Resource monitoring |
| `pytz` | ✅ | WIB / timezone |
| `redis` | ✅ | Redis client |
| `requests` | ✅ | Sync HTTP |
| `tavily-python` | ✅ | Search |
| `finnhub-python` | ✅ | News |
| `python-telegram-bot` | ✅ | Telegram |
| `pydantic` | ✅ | Validation |
| `uvicorn` | ✅ | ASGI runtime |
| `py-clob-client` | ✅ | Polymarket CLOB |
| `nest_asyncio` | ✅ | Nested loop helper |
| `numpy` | ✅ | Numerical computing |
| `pandas` | ✅ | Data handling |
| `web3` | ✅ | Polygon / EVM |
| `TA-Lib` | ✅ | Native package installed on Batam; fallback shim remains for portability |

---

## 🧩 Server-Only Artifacts
These exist on the server but are easy to miss if you only inspect the code tree:

- `state/` runtime JSON:
  - `active_strategy.json`
  - `ai_coordinator_cache.json`
  - `ai_coordinator_providers.json`
  - `ai_coordinator_rate.json`
  - `brain_status.json`
  - `learning_state.json`
  - `telemetry_snapshot.json`
  - `world_model.json`
- `logs/` application logs.
- `config/systemd/` local unit files for Kibot services.
- `bin/kibotctl` operator wrapper for status / doctor / restart / sync-models.
- `gh`, `copilot`, and `aider` are installed on the server; validate them with `bin/kibotctl tools`.
- User caches and tooling:
  - `~/.cache`
  - `~/.local`
  - `~/.copilot`
  - `~/.npm`
  - `~/.aider`
  - `~/.pki`
  - `~/.oci`
  - `~/.ssh`
- Extra runtime folders:
  - `Data/State/`
  - `SERVER_BATAM/`
  - `KiBot_LEGACY_BACKUP/`

## 🛠️ Operator Toolchain
| Tool | Status | Catatan |
|------|--------|---------|
| `gh` | authenticated | Login aktif di server Batam; dipakai untuk publish / inspect repo |
| `copilot` | installed | Copilot CLI tersedia di server |
| `aider` | installed | Terpasang via `pipx`; gunakan path explicit atau `bin/kibotctl tools` |
| `bin/kibotctl` | installed | Wrapper operasional satu pintu untuk status / doctor / toolchain / model sync |

---

## 🧠 Operational Notes
1. `MasterNode.py` should stay monitor-only and avoid spawning duplicate child services.
2. `sovereign_janitor.py` now delegates to `sovereign_disk_cleaner.py` when disk pressure is high.
3. `sovereign_disk_cleaner.py` is the main guardrail for nested repo duplication, cache bloat, and orphaned logs.
4. `POLYMARKET_*` is now present locally for Phantom-driven Polymarket automation.
5. 401 / 429 failures from upstream AI providers should be treated as provider-health/rate-limit signals, not immediate bot crashes.
6. `kibot-executor.service` is the canonical Indodax systemd unit; the older `kibot-executor-indodax` naming is retired.
7. `bin/kibotctl` is the canonical operator wrapper; it should stay thin and delegate runtime authority to systemd.
8. Real-money entries stay blocked until `KIBOT_LIVE_TRADING_ENABLED=true` or `KIBOT_TRADING_MODE=live` is set explicitly.
9. Telegram is a scarce incident channel and is throttled / deduped by the shared helper.
10. `whatif_results.json` is treated as live council input, so the system does not deliberate blind.
11. `SovereignCouncil` now merges `evidence_bundle` from Tavily, Serper, Brave, DuckDuckGo, Finnhub, and CryptoPanic before executing.
12. `IndodaxSmallCapScanner` and `PolymarketFullScanner` both emit richer confidence metadata so council can be more selective without going blind.
13. Daily learning probe logic exists to encourage at least one controlled entry per day, but it still respects hard loss limits and evidence floors.
14. `SovereignCouncil` now emits explicit `ENTER / WAIT / EXIT` posture and a recovery mode when equity is red but the evidence is still strong enough before midnight.
15. `SovereignCouncil` now also queries an antagonist / devil's-advocate view and `POSSIBILITY_MINING` so it can challenge its own thesis and avoid one-direction consensus drift.
16. Daily objective is now represented as `GREEN` state rather than a fixed numeric target, so profitable winners can stay open longer when the edge remains strong.
17. Scanner delta filtering now uses stable per-signal UIDs, so Polymarket signals are keyed by market ID instead of a generic `base_symbol` that can collapse distinct opportunities.
18. `EXIT_ALL` is clamped so it only applies in the midnight window or a genuine emergency; CPU-only spikes are downgraded to DEGRADED instead of a full trading shutdown when RAM/disk are still healthy. A healthy FLAT day is no longer allowed to default the council into `DEFENSIVE`; it is softened toward `CONTROLLED_AGGRESSIVE` or `NEUTRAL` so the system keeps seeking edges instead of going passive. Confidence floors were also relaxed slightly so narrow-spread, high-liquidity opportunities can still pass when evidence quality is good enough. Indodax pump continuation now uses 24h run-up, near-high structure, and volume persistence so pump coins from the leaderboard are not missed just because the latest 5m delta is modest. If Indodax depth/OBI is blocked from the server, the scanner falls back to a structural proxy instead of dropping the signal outright.
19. Live runtime strategy on Batam was restored from a stale defensive snapshot back to adaptive wildcard mode with `allowed_pairs=["*"]`, bounded `min_confidence`, capped slots, and spread/tick guards, so valid Indodax continuation candidates can actually reach the executor again without locking to one hallucinated pair.
20. Formal delegation workflow artifacts now exist in `Core/Intelligence/delegation_workflows.md` and `Core/Intelligence/delegation_workflows.json`, so discovery -> council -> executor -> verification -> maintenance has an explicit contract.
21. A visual control-plane dashboard now exists at `Core/Intelligence/kibot_dashboard.py` and is launched with `bin/kibot-dashboard` on port `8787`, so the whole delegation flow can be inspected in a browser. Dashboard V3.1 now serves a simplified delegation graph with dotted canvas, clean connected agent cards, left activity/technical logs with dedupe, workflow lanes, live Indodax/Polymarket ledger, council lens, and SSE event stream from `Core/Intelligence/dashboard/`.
22. `config/systemd/kibot-dashboard.service` is now the canonical systemd unit for the visual control plane, dan `bin/kibotctl` ikut mengelolanya sebagai service operasional supaya dashboard tetap online seperti core services lain. Dashboard launcher uses short graceful shutdown and systemd has `TimeoutStopSec=8` / `KillMode=mixed`, so stale SSE browser connections no longer make dashboard restarts hang.
23. Indodax equity snapshot now separates `idr_cash` and `coin_holdings_idr`, then exposes total `equity_idr`, so held coins are no longer invisible in portfolio/equity displays.
24. Daily PnL is now mark-to-market instead of holdings-as-profit: `risk_state.daily_pnl` + open trade unrealized PnL from `active_trades.json` (`current_value_idr - cost_idr`) + Polymarket daily PnL. Dashboard also reprices active holdings from live Indodax tickers, so stale telemetry prices do not make PnL lie. This prevents Dashboard/Council from showing GREEN just because the account holds coins.
25. `MasterNode.pnl_watchdog_loop` now consumes the same aggregator portfolio snapshot, so the 5-minute PnL watchdog and dashboard use one shared mark-to-market contract.
26. Scanner raw execution bypass is closed by default: `kibot-scanner` sends Indodax/Polymarket opportunities to Council, while executors reject non-`COUNCIL_MANDATE` payloads unless an explicit override env is set.
27. Indodax pump quality was hardened against fake leaderboard pumps: the scanner now checks official price increments, 24h price-level count, correct depth/OBI, spread, and OHLC flat-history / zero-volume traps before confidence scoring.
28. Phantom capital now has a multichain treasury controller and reconciliation gate: Base/EVM IDRX is treated as the source of truth for Phantom live execution, and `state/TREASURY_RECONCILIATION_REQUIRED` is only kept when the wallet does not match the expected real balance.
28. Indodax public endpoints were corrected to the official forms: ticker uses `/api/ticker/{pair}` and depth uses `/api/depth/{compact_pair}` such as `attidr`; this restores real spread/slippage checks.
29. Indodax executor now uses live wallet balance and pair metadata before selling, so stale `active_trades.json` amount drift no longer causes repeated insufficient-balance exits. Unsellable dust/minimum-order cases are throttled with `exit_blocked_until`.
30. Runtime strategy is sanitized after AI planning: pair locks are disabled by default, `allowed_pairs=["*"]`, max slots are capped for small capital, and confidence/spread floors remain bounded so Council stays opportunistic without going chaotic.
31. Telegram midnight report uses WIB window `00:00-00:04` and shared throttle/dedupe, so the daily report is restored without reintroducing noisy periodic spam.
32. RiskGate daily reset now follows WIB business day rather than server UTC. On Batam (`Etc/UTC`), this prevents the dashboard/Council from carrying yesterday's PnL after midnight WIB.
33. Indodax executor now reconciles `active_trades.json` against live wallet balances and `openOrders`: stale ghost positions are removed, pending exits stay tracked until wallet delta confirms fill, and external/late-filled holdings are re-attached only if they meet sellable minimums.
34. Council trading deliberation is bounded. Web evidence calls and AI roles have explicit timeouts; if provider/search stalls, a deterministic local scorer uses confidence, spread, tick-size, price levels, OHLC quality, what-if edge, and deadline pressure to produce a `WAIT` or `COUNCIL_MANDATE`.
35. The deterministic fallback is restricted to tradeable Indodax IDR pairs for real execution. Universal lead-lag items such as exchange names can inform context, but cannot become buy mandates.
36. A manual Telegram status report was verified through `SovereignNotifier.send_status_reply()` with the shared throttle helper; it returned `TELEGRAM_STATUS_SENT True`.
37. `TRADING_STRATEGY.md` is now the canonical trading-intelligence contract. It covers Indodax pump lifecycle, green-builder fallback, Polymarket event trading, cross-exchange capital commander, deadline discipline, role-agent debate, online evidence, scanner/executor gaps, Telegram report template, and dashboard requirements.
38. `decision_journal.py` writes a daily JSONL audit trail under `state/decision_journal/`. Scanner candidates, council decisions, pre-trade simulations, and executor events can now be traced after the fact.
39. `market_heatmap.py` snapshots Indodax market breadth from live tickers and persists `state/market_heatmap.json`, giving Council a market-regime input instead of relying on isolated pair signals.
40. `probability_engine.py` persists `state/green_probability.json` from daily PnL color, deadline mode, market breadth, scanner slate, order quality, system health, and source health.
41. `pre_trade_simulator.py` runs before buy-side execution. It blocks entries with empty depth, excessive spread/slippage, unsellable minimum amount, or partial-TP infeasibility, and can recommend smaller size before RiskGate.
42. Indodax executor now stores `exit_plan`, `pre_trade_simulation`, `trade_grade`, `lifecycle`, `deadline_mode`, and `capital_state` inside `active_trades.json`, so every position carries its own reason, risk, and exit contract.
43. Exit management now supports partial take-profit, trailing stop, max-hold timeout, and distribution exits while still falling back to legacy hard stop / take profit for old positions.
44. Midnight Telegram reporting is routed through `SovereignNotifier.send_daily_report()` and `daily_report.py` with shared throttling, so the operator receives one compact report instead of spam.
45. Dashboard V3.1 now surfaces strategy intelligence: deadline mode, risk mode, quality floor, green probability, scanner slate, decision journal count, and market breadth in the visual workflow board.
46. Universal lead-lag signals are now context-only when they appear alone. They are persisted in scanner state, but Council is only awakened when there is at least one tradeable Indodax or Polymarket signal, preventing non-executable exchange names from consuming AI deliberation time.
47. Fallback category intelligence is implemented in `Core/Intelligence/coin_category.py`. Scanner now labels each Indodax candidate with deterministic category policy (`HIGH_LIQUIDITY_MAJOR`, `BTC_ETH_BETA`, `AI_BIG_DATA`, `RWA_DEFI`, `MEME_ROTATION`, `LOCAL_MOMENTUM`) so Council can switch from pump riding to structured green-builder mode without buying random dead coins.
48. The Indodax unit-price law is enforced by both `RiskGate` and `IndodaxExecutor`: a BUY is rejected when `price_idr >= total_equity_idr`. This makes the operator rule explicit: KiBot may only buy coins whose one-unit price is below the current total balance/equity.
49. Strategy documentation is now split by responsibility: `TRADING_STRATEGY.md` for trading, `SYSTEM_STRATEGY.md` for non-trading autonomy, `AUTONOMY_GAP_REGISTER.md` for gap tracking, `IMPLEMENTATION_ROADMAP.md` for phased execution, `INVENTORY_UTILIZATION.md` for server asset usage, `SYSTEM_COMMANDER_SPEC.md` for the missing non-trading brain, `POLYMARKET_RUNTIME_ROADMAP.md` for Polymarket V2, and `OBSERVABILITY_DASHBOARD_SPEC.md` for dashboard/control-plane visibility.
50. `SystemCommander` is now the canonical non-trading system brain. It writes `state/system_commander.json` and `state/inventory_matrix.json`, classifies health (`HEALTHY/DEGRADED/BLIND/UNSAFE`), scores canonical services/models/tools/state, reads provider/source health, and exposes GitHub/server drift. It no longer treats absent Tailscale as a missing runtime dependency.
51. Dashboard System Brain now consumes a stable `system_brain` summary contract, so inventory utilization, source health, and drift status are rendered from live state instead of mismatched frontend IDs.
52. Backup automation now defaults to non-secret protected archives (`state/`, strategy docs, inventory) with private file permissions. Plaintext `.env` is excluded unless `KIBOT_BACKUP_INCLUDE_SECRETS=1` is deliberately set.
53. Server-only legacy systemd restart loops and stale timers were retired/disabled so missing historical `Batam/...` paths no longer spam logs or burn CPU. Canonical runtime remains `kibot-master`, `kibot-scanner`, `kibot-executor`, `kibot-executor-polymarket`, `kibot-ai-scout`, `kibot-janitor`, `kibot-dashboard`, `ollama`, and `redis-server`.
54. Solana trending meme hunter now exists as a guarded live-control module: `Core/Web3/solana_trending_scanner.py` feeds `state/solana_trending_candidates.json`, `Core/Intelligence/strategy/solana_momentum_meme_strategy.py` scores small-cap momentum, and dashboard/control-plane surfaces the best candidate plus reject reason without enabling reserve spend or bypassing exit plans.
55. Autonomous sizing is now a runtime source-of-truth in `Core/Trading/autonomous_sizing.py`; executors consume its `size_idr` output instead of hardcoded fixed trade caps, and the latest sizing decision is written to `state/autonomous_sizing.json` and surfaced on the dashboard.

---

## 🧾 Why this file exists
This file is kept in GitHub so Claude and other agents can see what the server actually has:
- what is installed,
- what is running,
- what is missing,
- what is server-only and not visible in code review.
