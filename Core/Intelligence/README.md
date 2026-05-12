# 🧠 KiBot Intelligence

AI Orchestration, Learning, and Market Intelligence models.

## Ringkas
- `aggregator.py` menggabungkan konteks portfolio, market, dan historis council.
- `kibot_ai_coordinator.py` mengatur alur AI dan provider fallback.
- `kibot_learning_engine.py` menyimpan state belajar dan validasi integritas.
- `kibot_rag.py` menyuntikkan fakta server dan memori operasional ke agent.
- `kibot_ai_scout.py` menjaga scouting intel pasar dan berita global tetap hidup.

## Live Server Atlas
Source of truth untuk keadaan server yang sebenarnya:
- [`SERVER_INVENTORY.md`](./SERVER_INVENTORY.md)

Snapshot singkat yang paling penting:
- Server: `BrainSystem` di Batam.
- OS: Ubuntu 24.04.4 LTS `aarch64`.
- Disk root: 184G total, sekitar 154G free setelah cleanup terakhir.
- RAM: 23Gi, CPU: 4 core.
- Core services hidup: `kibot-master`, `kibot-executor`, `kibot-executor-polymarket`, `kibot-ai-scout`, `ollama`, `redis-server`.
- Port hidup: `9990`, `9991`, `9998`, `11434`, `11600`, `6379`.
- Ollama model yang tersedia saat ini: `qwen2.5:0.5b`, `qwen2.5:1.5b`, `qwen2.5:3b`, `llama3.2:3b`, `nomic-embed-text:latest`.
- Native `TA-Lib` tidak terpasang; repo memakai fallback `ta`/`pandas` shim.

Server-only artifacts yang tidak kelihatan dari code tree biasa:
- `state/` runtime JSON, cache, ledger, dan strategi aktif. Ini canonical runtime state; `Core/state` adalah jejak lama yang sudah dipreteli.
- `logs/` aplikasi dan notifikasi.
- `config/systemd/` untuk unit file service.
- `~/.cache`, `~/.local`, `~/.copilot`, `~/.npm`, `~/.ssh`, `~/.oci`, `~/.aider` di akun `ubuntu`.
- `SERVER_INVENTORY.md` sebagai snapshot runtime yang disimpan di repo.

## Responsibility
- **AI Veto**: Validating signals using local LLMs (Ollama/Dify).
- **What-If Analysis**: Simulating market conditions before execution.
- **Learning Cycle**: Continuous improvement of trading parameters.
- **RAG Context**: Providing local system knowledge to AI agents.
- **Server Awareness**: Knowing what is really installed, running, and missing on Batam.

## AI / Web Search Matrix
- **Local brain**: Ollama via `kibot_ollama_gateway.py`.
- **External fallbacks**: Gemini, Groq, OpenRouter, Cerebras, Mistral, Cohere, DeepSeek, Together, Fireworks, DeepInfra, Novita, Nvidia, Perplexity, SambaNova, HuggingFace, Jina.
- **Search / intel sources**: Tavily, Serper, DuckDuckGo, Finnhub, GDELT, Brave Search, CryptoPanic.
- **Live caution**: `401` / `429` biasanya tanda auth atau rate-limit upstream, bukan bug inti bot.

## Operational Notes
- `MasterNode.py` sebaiknya tetap monitor-only dan tidak spawn duplicate services.
- `sovereign_janitor.py` sekarang menjadi pintu awal health sweep.
- `sovereign_disk_cleaner.py` adalah guardrail utama untuk nested repo, cache bloat, dan orphaned logs.
- AI provider cooldown state dipertahankan lintas boot; set `KIBOT_RESET_AI_COOLDOWNS_ON_BOOT=1` hanya saat perlu reset manual.
- `POLYMARKET_WALLET_ADDRESS` / `POLYMARKET_PRIVATE_KEY` masih perlu diisi agar Polymarket benar-benar otomatis.

## Key Files
- `kibot_ai_coordinator.py`: Main AI signal processor.
- `kibot_whatif_engine.py`: Mathematical risk simulator.
- `kibot_rag.py`: Local knowledge retrieval.
- `kibot_learning_engine.py`: Performance optimization.
- `kibot_ai_scout.py`: Live market scout / intel collector.
- `kibot_ollama_gateway.py`: Local LLM gateway.
