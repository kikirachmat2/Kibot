# 🗄️ KiBot Sovereign — Server Inventory
> **Server**: BrainSystem (Batam Master)  
> **Last Verified**: 2026-05-12  
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
| `ollama` | active | Local AI server |
| `redis-server` | active | Runtime state store |

### Legacy / Auxiliary
| Service | Status | Catatan |
|---------|--------|---------|
| `kibot-trinity` | retired / masked | Service tambahan lama, tidak lagi dipakai sebagai jalur runtime |
| `kibot-commander` | retired / masked | Helper service lama |
| `kibot-notifier` | retired / masked | Helper service lama |
| `ki-telegram-monitor` | retired / masked | Helper service lama |

### Ports
| Port | Service | Protokol | Fungsi |
|------|---------|----------|--------|
| 9990 | PolymarketExecutor | UDP | Receive signals |
| 9991 | MasterNode Council | UDP | Council deliberation |
| 9998 | IndodaxExecutor | UDP | Receive signals |
| 11434 | Ollama | TCP | AI model API |
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
18. `EXIT_ALL` is clamped so it only applies in the midnight window or a genuine emergency; CPU-only spikes are downgraded to DEGRADED instead of a full trading shutdown when RAM/disk are still healthy. A healthy FLAT day is no longer allowed to default the council into `DEFENSIVE`; it is softened toward `CONTROLLED_AGGRESSIVE` or `NEUTRAL` so the system keeps seeking edges instead of going passive. Confidence floors were also relaxed slightly so narrow-spread, high-liquidity opportunities can still pass when evidence quality is good enough.

---

## 🧾 Why this file exists
This file is kept in GitHub so Claude and other agents can see what the server actually has:
- what is installed,
- what is running,
- what is missing,
- what is server-only and not visible in code review.
