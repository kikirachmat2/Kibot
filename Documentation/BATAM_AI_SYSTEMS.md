# 🤖 KiBot Batam — Master AI & Support System Inventory
> **Server:** `168.110.201.228` | **Role:** Command Center | **Status:** SOVEREIGN-READY
> **Last Updated:** 2026-05-07

---

## 🧠 LAYER 1: LOCAL AI (Sovereign — Offline, No Internet Needed)

### Ollama Engine (Primary Brain)
| Model | Ukuran | Peran | Speed |
|---|---|---|---|
| `qwen3:0.6b` | 522 MB | **Fast Path** — Screening & scoring sinyal cepat | ~200ms |
| `qwen3:1.7b` | 1.4 GB | **Default Brain** — Reasoning & veto analysis | ~1-3 detik |
| `qwen3:4b` | 2.5 GB | **Deep Brain** — Daily review, what-if, post-mortem | ~3-8 detik |
| `nomic-embed-text` | 274 MB | **RAG Embeddings** — Mengubah teks → vektor untuk memory | ~50ms |

**Config kunci Ollama:**
```
KIBOT_OLLAMA_FAST_NUM_CTX=2048
KIBOT_OLLAMA_DEFAULT_NUM_CTX=3072
KIBOT_OLLAMA_DEEP_NUM_CTX=4096
KIBOT_OLLAMA_THINK_LEVEL=true   ← Chain of Thought aktif
keep_alive: Fast=45s, Default=90s, Deep=5m
```

---

## ⚡ LAYER 2: ONLINE AI PROVIDERS (Fallback Mesh — Ordered by Priority)

| Priority | Provider | Model | Limit/Hari | Keunggulan |
|---|---|---|---|---|
| **#1** | **Cerebras** | `llama3.1-8b` | 50.000 req | 🚀 Tercepat di dunia (<500ms) |
| **#2** | **Groq** | `llama-3.1-8b-instant` | 14.400 req | ⚡ Ultra-cepat (<1 detik) |
| **#3** | **Gemini 2.0 Flash** | `gemini-2.0-flash-lite` | 1.500 req | 🌐 Google Search native |
| **#4** | **DeepSeek** | `deepseek-chat` | 5.000 req | 🧮 Reasoning kuat |
| **#5** | **Mistral** | `mistral-tiny` | 5.000 req | 💡 Bahasa Indonesia bagus |
| **#6** | **SambaNova** | `Meta-Llama-3.1-8B` | 5.000 req | 🔄 Cadangan Llama |
| **#7** | **Together AI** | `Llama-3-8b-chat-hf` | 3.000 req | 🔄 Cadangan |
| **#8** | **Fireworks** | `llama-v3-8b-instruct` | 2.000 req | 🔄 Cadangan |
| **#9** | **Cohere** | `command-r` | Unlimited* | ✅ Key aktif di server |
| **#10** | **Mistral** | `mistral-tiny` | 5.000 req | 🔄 Cadangan |
| **#11** | **OpenRouter** | `llama-3.1-8b-instruct` | 200 req | 🌐 Multi-model gateway |
| **#12** | **NVIDIA** | `llama-3.1-70b-instruct` | 1.000 req | 🔥 Model terbesar (70B) |
| **#13** | **DeepInfra** | `Meta-Llama-3-8B` | 500 req | 🔄 Cadangan |
| **#14** | **Novita** | `llama-3-8b-instruct` | 500 req | 🔄 Cadangan |
| **#15** | **Perplexity** | `sonar-small-online` | 100 req | 🌐 Web-aware AI |

**Cara kerja Fallback:** Ollama → (timeout/fail) → Cerebras → Groq → Gemini → ... otomatis tanpa intervensi.

---

## 🔍 LAYER 3: WEB SEARCH & INTELIJEN PASAR

| Tool | Limit | Fungsi | Status |
|---|---|---|---|
| **DuckDuckGo** (`ddg_search`) | Unlimited | Cari berita crypto bebas tanpa API key | ✅ Aktif (no key) |
| **Tavily AI** | **950 credits/bulan** | Deep web search + AI summarization | ✅ Key baru aktif |
| **Serper.dev** (Google) | **2.450 credits/bulan** | Real-time Google Search (bahasa ID) | ✅ Key baru aktif |
| **Jina AI** | ~1M token/bulan | Web scraping + URL reader untuk RAG | ✅ Key aktif |
| **Brave Search** | Free tier | Backup web search | ⚠️ Perlu BRAVE_API_KEY |

---

## 📰 LAYER 4: DATA BERITA & SENTIMEN PASAR

| Tool | Limit | Fungsi | Status |
|---|---|---|---|
| **Finnhub.io** | **60 req/menit** | Berita finansial institusional (crypto, stocks) | ✅ Key baru aktif |
| **Finnhub Secret** | — | API secret untuk webhook Finnhub | ✅ Aktif |
| **GDELT Project** | Unlimited | Global news tracker (no key required) | ✅ Aktif (no key) |
| **CryptoPanic** | Free tier | Hot news crypto + vote sentiment | ⚠️ Perlu CRYPTOPANIC_API_KEY |

---

## 🤖 LAYER 5: AUTONOMOUS CODING & SELF-HEALING

| Tool | Fungsi | Status |
|---|---|---|
| **Aider** (`aider-chat`) | AI coding agent — auto-fix service crashes | ✅ Running |
| **Model:** `qwen3:1.7b` | Model yang digunakan Aider untuk analisis & perbaikan kode | ✅ Loaded |
| **GitHub CLI** (`gh`) | Deploy otomatis ke repo — sudah login di server | ✅ Login aktif |
| **GitHub Copilot** | AI code completion untuk Aider | ✅ Login aktif |
| **trinity_healer.py** | Trigger otomatis Aider saat service crash | ✅ Running |

**Cara kerja Auto-Repair:**
```
Service crash → trinity_healer.py detects → spawn Aider 
→ Aider pakai deepseek-coder-v2:16b → analisis log → fix kode 
→ gh commit & push → service restart otomatis
```

---

## 📊 LAYER 6: DATA & EMBEDDING (RAG)

| Tool | Fungsi | Status |
|---|---|---|
| **nomic-embed-text** (Ollama) | Mengubah market data → vector embedding | ✅ Installed |
| **Jina Embeddings** | Cloud embeddings untuk document chunking | ✅ Key aktif |
| **Supabase** | Database + vector storage (LEGACY) | ❌ DEPRECATED (Sovereign Mode) |
| **SQLite (Local)** | Primary Trade & Post-Mortem Logs | ✅ ACTIVE (Sovereign DB) |
| **JSON/Local Vector** | Vector storage untuk RAG memory | ✅ ACTIVE (Local) |
| **Redis** | In-memory cache sinyal & state | ✅ Running |

---

## 🌐 LAYER 7: PASAR & EXCHANGE INTELLIGENCE

| Tool | Fungsi |
|---|---|
| **Polymarket Oracle** | Sentiment pasar prediksi (probabilitas event crypto) |
| **Indodax API** | Live trading execution (via Executor) |
| **Binance/KuCoin** (via Scanner) | Price feed & orderbook data 24/7 |
| **Lead-Lag Pairs** | 20+ pasangan koin terdeteksi otomatis |

---

## 🔧 SERVICES AKTIF DI BATAM (systemd)

| Service | Status | Fungsi |
|---|---|---|
| `kibot-trinity.service` | ✅ Running | Brain utama / autonomous loop |
| `kibot-ollama-gateway.service` | ✅ Running | Ollama API gateway |
| `kibot-healer.service` | ✅ Running | Self-healing & Aider trigger |
| `kibot-polymarket.service` | ✅ Running | Polymarket oracle |
| `kibot-resource-governor.timer` | ✅ Running | Disk & Memory cleanup (6h cycle) |
| `kibot-command-center.service` | ✅ Running | Web command dashboard |
| `ki-telegram-monitor.service` | ✅ Running | Telegram monitor & alerts |

---

## 🚀 2026 SOTA RECOMMENDATIONS (Hardware: 4-Core ARM, 24GB RAM)

| Task Tier | Recommended Model | Current | Benefit |
|---|---|---|---|
| **Deep Reasoning** | `qwen3:4b` | `qwen3:0.6b` | Lebih kuat untuk daily review, what-if, dan post-mortem. |
| **Default Logic** | `qwen3:1.7b` | `qwen3:0.6b` | Balance terbaik untuk keputusan inti trading. |
| **Fast Veto** | `qwen3:0.6b` | `qwen3:0.6b` | Latensi paling rendah untuk screening cepat. |

---

## ⚠️ YANG PERLU DITAMBAHKAN (Optional Upgrade)

| Tool | Kegunaan | Aksi |
|---|---|---|
| `BRAVE_API_KEY` | Backup web search privacy-first | Daftar di brave.com/search/api |
| `CRYPTOPANIC_API_KEY` | Hot crypto news + vote sentiment | Daftar di cryptopanic.com |
| `PERPLEXITY_API_KEY` | Web-aware AI queries | Daftar di perplexity.ai/api |

---

> **Total AI Providers:** 15 Online + 3 Local Ollama Models + 1 Embedding Model
> **Infrastructure Status:** 100% Sovereign (No Cloud Dependency)
> **Self-Healing:** Aider + deepseek-coder-v2:16b + GitHub Copilot (fully autonomous)
