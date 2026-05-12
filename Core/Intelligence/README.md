# 🧠 KiBot Intelligence

AI Orchestration, Learning, and Market Intelligence models.

## Ringkas
- `aggregator.py` menggabungkan konteks portfolio live, market, dan historis council.
- `kibot_ai_coordinator.py` mengatur alur AI dan provider fallback.
- `kibot_learning_engine.py` menyimpan state belajar dan validasi integritas.
- `kibot_rag.py` menyuntikkan fakta server dan memori operasional ke agent.
- `kibot_ai_scout.py` menjaga scouting intel pasar dan berita global tetap hidup.
- `kibot_whatif_engine.py` menjaga simulasi skenario selalu terbarui untuk council.
- `SovereignCouncil` membaca `whatif_results.json` dan evidence web sebelum memberi mandat trading.
- `SovereignCouncil` sekarang juga memberi posture eksplisit `ENTER / WAIT / EXIT`, plus recovery mode terkontrol saat equity harian merah dan masih ada waktu sebelum midnight.
- `SovereignCouncil` juga menjalankan `COUNCIL_ANTAGONIST` dan `POSSIBILITY_MINING` supaya council tidak berpikir satu arah saja.
- Target harian sekarang dipahami sebagai state `GREEN` bukan angka persen statis, jadi council dan executor bisa menahan winner lebih lama kalau edge masih kuat.
- `kibot_ai_scout.py` membawa `daily_state` yang sama ke `POSSIBILITY_MINING` dan validasi targeted scouting, sehingga scouting global dan council memakai posture yang konsisten.

## Live Server Atlas
Source of truth untuk keadaan server yang sebenarnya:
- [`SERVER_INVENTORY.md`](./SERVER_INVENTORY.md)

Snapshot singkat yang paling penting:
- Server: `BrainSystem` di Batam.
- OS: Ubuntu 24.04.4 LTS `aarch64`.
- Disk root: 184G total, sekitar 144G free setelah cleanup + model pulls terbaru.
- RAM: 23Gi, CPU: 4 core.
- Core services hidup: `kibot-master`, `kibot-executor`, `kibot-executor-polymarket`, `kibot-ai-scout`, `ollama`, `redis-server`.
- Port hidup: `9990`, `9991`, `9998`, `11434`, `11600`, `6379`.
- Ollama model yang tersedia saat ini: `qwen2.5:0.5b`, `qwen2.5:1.5b`, `qwen2.5:3b`, `llama3.2:3b`, `deepseek-r1:7b`, `mistral:7b`, `qwen2.5-coder:3b`, `nomic-embed-text:latest`.
- Native `TA-Lib` sudah terpasang di server; fallback `ta`/`pandas` shim tetap disimpan untuk portability.
- Portfolio snapshot council sekarang dibaca live dari Indodax API + Polymarket state API, jadi council tidak bergantung pada cache lama saat menilai saldo dan PnL.

Server-only artifacts yang tidak kelihatan dari code tree biasa:
- `state/` runtime JSON, cache, ledger, dan strategi aktif. Ini canonical runtime state; `Core/state` adalah jejak lama yang sudah dipreteli.
- `logs/` aplikasi dan notifikasi.
- `config/systemd/` untuk unit file service.
- `~/.cache`, `~/.local`, `~/.copilot`, `~/.npm`, `~/.ssh`, `~/.oci`, `~/.aider` di akun `ubuntu`.
- `SERVER_INVENTORY.md` sebagai snapshot runtime yang disimpan di repo.
- `bin/kibotctl` sebagai wrapper operasional satu pintu untuk status, doctor, restart, dan sync model.
- `gh`, `copilot`, dan `aider` tersedia di server Batam; gunakan `bin/kibotctl tools` untuk cek apakah toolchain ini benar-benar siap dipakai.
- Council tidak lagi buta skenario: hasil `whatif_results.json` ikut dibaca saat deliberasi strategis dan trading.
- Council juga tidak buta web: evidence bundle menghitung coverage, catalyst hit, risk flags, dan track-record proxy sebelum action `EXECUTING`.
- Daily learning probe dipertimbangkan jika belum ada trade hari itu, tetapi tetap dibatasi evidence bundle dan hard loss rules.
- Recovery posture dipakai hanya ketika PnL merah, waktu masih cukup, dan evidence masih kuat. Itu bukan revenge trading, melainkan controlled re-entry / de-risking.
- Deadline pressure dan antagonistic debate sekarang aktif di council planning, jadi sistem terus mencari opsi terbaik sampai menjelang midnight.
- Daily state dikirim ke planner dan executor supaya posisi pemenang tidak dipotong terlalu cepat hanya karena target angka lama sudah tercapai.
- Scanner dedupe memakai UID yang tidak mencampur market Polymarket yang berbeda, jadi sinyal tidak lagi hilang karena base_symbol yang terlalu generik.
- `EXIT_ALL` sekarang hanya sah di window midnight / emergency terkontrol; keputusan strategi normal tidak boleh mematikan trading saat sesi masih berjalan.
- Mode `DEFENSIVE` tidak lagi dipakai sebagai default saat hari `FLAT` dan server sehat; council akan cenderung tetap oportunistik dengan `CONTROLLED_AGGRESSIVE` atau `NEUTRAL` agar tidak idle.
- Ambang confidence Indodax/Polymarket dilonggarkan sedikit supaya market tipis tapi valid masih bisa ditembus; hard-loss dan spread guards tetap aktif.
- CPU spike sendiri tidak lagi cukup untuk memicu emergency pause jika RAM/disk masih sehat; council menganggap itu sebagai kondisi DEGRADED, bukan stop total.

## Responsibility
- **AI Veto**: Validating signals using local LLMs (Ollama/Dify).
- **What-If Analysis**: Simulating market conditions before execution.
- **Learning Cycle**: Continuous improvement of trading parameters.
- **RAG Context**: Providing local system knowledge to AI agents.
- **Server Awareness**: Knowing what is really installed, running, and missing on Batam.

## AI / Web Search Matrix
- **Local brain**: Ollama via `kibot_ollama_gateway.py`.
- **External fallbacks currently configured on Batam**: Gemini, Groq, OpenRouter, Cerebras, Mistral, Cohere, Jina, NVIDIA.
- **Search / intel sources**: Tavily, Serper, DDGS, Finnhub, Brave, CryptoPanic.
- **Decision evidence**: Tavily + Serper + Brave + DDGS + Finnhub + CryptoPanic dipakai untuk validasi catalyst / track record.
- **Code specialist**: `qwen2.5-coder:3b` for repo work, wrapper generation, and code review tasks.
- **Live caution**: `401` / `429` biasanya tanda auth atau rate-limit upstream, bukan bug inti bot.

## Operational Notes
- `MasterNode.py` sebaiknya tetap monitor-only dan tidak spawn duplicate services.
- `sovereign_janitor.py` sekarang menjadi pintu awal health sweep.
- `sovereign_disk_cleaner.py` adalah guardrail utama untuk nested repo, cache bloat, dan orphaned logs.
- AI provider cooldown state dipertahankan lintas boot; set `KIBOT_RESET_AI_COOLDOWNS_ON_BOOT=1` hanya saat perlu reset manual.
- `POLYMARKET_WALLET_ADDRESS` / `POLYMARKET_PRIVATE_KEY` sudah terisi di env lokal untuk eksekusi Polymarket otomatis.
- `kibotctl` adalah entrypoint operasional satu command; gunakan `status`, `doctor`, `restart`, dan `sync-models` untuk menjaga sinkronisasi server.
- Live trading executor tetap menunggu gate eksplisit `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live`.

## Key Files
- `kibot_ai_coordinator.py`: Main AI signal processor.
- `kibot_whatif_engine.py`: Mathematical risk simulator.
- `kibot_learning_engine.py`: also tracks daily trade activity for probe logic.
- `kibot_rag.py`: Local knowledge retrieval.
- `kibot_ai_scout.py`: Live market scout / intel collector.
- `kibot_ollama_gateway.py`: Local LLM gateway that now loads sovereign env explicitly and fails closed when the runtime secret is missing.
- `SovereignCouncil`: deliberation engine yang menggabungkan what-if snapshot dan evidence web sebelum final mandate.
- `kibot_ollama_gateway.py`: Local LLM gateway.
