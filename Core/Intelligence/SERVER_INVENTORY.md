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
| Disk | 184G root, sekitar 154G free setelah cleanup terakhir |
| Python | 3.12.3 |
| Node.js | v18.19.1 |

---

## ⚙️ Live Services
### Core
| Service | Status | Catatan |
|---------|--------|---------|
| `kibot-master` | active | MasterNode / council supervisor |
| `kibot-executor` | active | Executor Indodax |
| `kibot-executor-polymarket` | active | Executor Polymarket |
| `kibot-ai-scout` | active | Intel / scouting loop |
| `ollama` | active | Local AI server |
| `redis-server` | active | Runtime state store |

### Legacy / Auxiliary
| Service | Status | Catatan |
|---------|--------|---------|
| `kibot-trinity` | legacy / audit | Service tambahan, perlu dicek apakah masih diperlukan |
| `kibot-commander` | inactive | Helper service lama |
| `kibot-notifier` | inactive | Helper service lama |
| `ki-telegram-monitor` | inactive | Helper service lama |

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
| `nomic-embed-text:latest` | ✅ ADA | Embeddings / RAG |
| `deepseek-r1:7b` | ❌ belum | Heavy reasoning |
| `mistral:7b` | ❌ belum | Bridge / synthesis |

> Catatan: model besar belum dipull karena kebijakan disk dan prioritas runtime.

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
| `OPENROUTER_API_KEY` | SET | AI gateway |
| `TAVILY_API_KEY` | SET | Web search |
| `SERPER_API_KEY` | SET | Web search |
| `FINNHUB_API_KEY` | SET | Market news |
| `JINA_API_KEY` | SET | Search / scrape |
| `GDELT_API_KEY` | SET | News events |
| `COHERE_API_KEY` | SET | AI fallback |

### Not loaded / missing
| Variable | Status | Catatan |
|----------|--------|---------|
| `CEREBRAS_API_KEY` | EMPTY | Raw `.env` ada encrypted value, tapi vault runtime drop karena decrypt gagal |
| `MISTRAL_API_KEY` | EMPTY | Raw `.env` ada encrypted value, tapi vault runtime drop karena decrypt gagal |
| `POLYMARKET_WALLET_ADDRESS` | EMPTY | Belum ada di runtime |
| `POLYMARKET_PRIVATE_KEY` | EMPTY | Belum ada di runtime |
| `BRAVE_API_KEY` | EMPTY | Belum dikonfigurasi |
| `CRYPTOPANIC_API_KEY` | EMPTY | Belum dikonfigurasi |
| `DEEPSEEK_API_KEY` | EMPTY | Belum dikonfigurasi |

---

## 🔍 Web Search / Intelligence Sources
| Source | Library / API | Status | Catatan |
|--------|---------------|--------|---------|
| Tavily | `tavily-python` | ✅ | Deep search / catalyst |
| Serper | `requests` | ✅ | Google-result style search |
| DuckDuckGo | `duckduckgo-search` | ✅ | Free search |
| Finnhub | `finnhub-python` | ✅ | Crypto / market news |
| Jina AI | `httpx` | ✅ | Scrape / semantic fetch |
| GDELT | `httpx` | ✅ | News events |
| Brave Search | `httpx` | ❌ | Key missing |
| CryptoPanic | `httpx` | ❌ | Key missing |

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
| `TA-Lib` | ❌ | Native package unavailable; repo uses `ta` / `pandas` fallback shim |

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

---

## 🧠 Operational Notes
1. `MasterNode.py` should stay monitor-only and avoid spawning duplicate child services.
2. `sovereign_janitor.py` now delegates to `sovereign_disk_cleaner.py` when disk pressure is high.
3. `sovereign_disk_cleaner.py` is the main guardrail for nested repo duplication, cache bloat, and orphaned logs.
4. `CEREBRAS_API_KEY` / `MISTRAL_API_KEY` raw blobs may still live in `.env`, but they are not usable until re-encrypted or replaced.
5. `POLYMARKET_*` is still missing, so Phantom-driven Polymarket automation is not fully armed yet.
6. 401 / 429 failures from upstream AI providers should be treated as provider-health/rate-limit signals, not immediate bot crashes.

---

## 🧾 Why this file exists
This file is kept in GitHub so Claude and other agents can see what the server actually has:
- what is installed,
- what is running,
- what is missing,
- what is server-only and not visible in code review.

