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
- `delegation_workflows.md` dan `delegation_workflows.json` mendokumentasikan alur delegasi formal KiBot: discovery, council, executor, verification, dan maintenance.
- `kibot_dashboard.py` menampilkan alur delegasi, saldo live, council lens, strategy state, dan event trail dalam visual control plane web di port `8787`.
- `dashboard/` memuat Dashboard V3.1: delegation graph sederhana ala node workflow, activity log dedupe, agent inspector, workflow board, live ledger Indodax/Polymarket, dan SSE updates.
- `bin/kibotctl` sekarang ikut mengelola `kibot-dashboard`, jadi visual control plane masuk ke wrapper operasional satu pintu.
- `aggregator.py` sekarang menghitung equity Indodax sebagai `idr_cash + coin_holdings_idr`, sehingga saldo koin yang sedang dipegang ikut tampil di dashboard dan council snapshot.
- Daily PnL sekarang mark-to-market: realized PnL dari `risk_state.json` + unrealized open trades dari `active_trades.json` (`current_value - cost`), bukan lagi menganggap seluruh coin holdings sebagai profit.
- Scanner mentah sekarang hanya menjadi input Council. Indodax/Polymarket executor default-nya menolak raw scanner signal dan hanya menerima `COUNCIL_MANDATE`.
- Pump intelligence sekarang menolak tick-trap: `price_increment / price` terlalu besar, level harga 24h terlalu sedikit, spread terlalu lebar, OBI condong jual, atau OHLC terlalu datar / zero-volume.
- Indodax gateway memakai endpoint resmi `ticker/{pair}` dan `depth/{compact_pair}`; orderbook kini benar-benar terbaca untuk slippage/OBI.
- Executor mensinkronkan amount sell dengan live balance dan metadata minimum order Indodax supaya tidak spam gagal exit ketika state amount berbeda dari saldo aktual.
- Indodax executor sekarang melakukan wallet/open-order reconciliation berkala: posisi yang tidak punya balance/open order dibuang sebagai stale, sedangkan holding yang muncul di wallet dan memenuhi minimum order otomatis di-attach kembali ke `active_trades.json`.
- Council trading deliberation sekarang bounded: `COUNCIL_ANTAGONIST`, `COUNCIL_SPEAKER`, dan evidence web search punya timeout. Jika AI/provider lambat, deterministic fallback memilih `ENTER/WAIT` dari local evidence (confidence, spread, tick trap, OHLC quality, what-if), bukan menggantung.
- RiskGate dan aggregator memakai business day WIB, sehingga daily PnL/report tidak salah tanggal ketika server masih UTC.
- `PUMP_LIFECYCLE_STRATEGY.md` adalah kontrak strategi utama untuk pump riding, green-builder fallback, deadline intelligence, role-agent debate, Telegram report, dan dashboard alignment.
- `decision_journal.py` mencatat scanner slate, council vote, pre-trade simulation, dan execution event ke `state/decision_journal/YYYY-MM-DD.jsonl` supaya semua keputusan bisa diaudit.
- `pre_trade_simulator.py` menolak entry yang tidak masuk akal sebelum order: spread terlalu lebar, slippage buruk, min sellable tidak tercapai, partial TP tidak feasible, atau depth kosong.
- `market_heatmap.py` membangun snapshot breadth Indodax dari ticker live sehingga council tahu apakah pasar sedang pump-friendly, mixed, risk-off, atau thin.
- `probability_engine.py` menghitung estimasi probabilitas harian untuk tetap/menjadi GREEN berdasarkan PnL, deadline, heatmap, kandidat scanner, order quality, health server, dan health sumber data.
- `daily_report.py` membuat template Telegram midnight report yang singkat: state, PnL, cash/holdings, scanner/council/executor summary, risk flags, dan next posture.
- Executor Indodax sekarang memakai `exit_plan` per posisi: hard stop, trailing stop, partial TP, max hold, distribution exit, dan fallback legacy jika plan belum ada.
- Dashboard membaca `daily_context`, `green_probability`, `market_heatmap`, `scanner_candidates`, dan `decision_journal`, sehingga control plane menampilkan kecerdasan strategi yang sama dengan runtime.

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
- Indodax pump hunting kini menganggap 24h run-up, jarak ke high harian, dan volume persistence sebagai sinyal valid untuk continuation, bukan hanya lonjakan 5m.
- Low-price leaderboard pump seperti harga 1↔2 IDR tidak lagi dianggap edge; tick-size, sellable minimum amount, orderbook spread, dan distinct candle levels harus lolos dulu.
- `support_bounce_reclaim` menambahkan jalur wave-riding yang memantul dari intraday support lalu reclaim lagi, tapi tetap dibatasi room-to-run dan recovery score supaya tidak liar.
- `pivot_reclaim` menambahkan jalur reclaim yang lebih awal lagi untuk menangkap rebound awal, tetapi masih dibatasi supaya tidak berubah jadi entry liar.
- Jika depth/OBI Indodax tidak tersedia dari server, scanner memakai proxy struktural agar pump hunting tetap berjalan alih-alih mati di hard gate.
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
- Telegram status path sudah diverifikasi lagi via shared throttled notifier; manual status bisa dikirim tanpa membuka spam loop, sedangkan report harian tetap di window midnight WIB.
- Pump lifecycle runtime sekarang punya empat lapis sebelum real-money entry: scanner evidence, fast+deep council mandate, pre-trade orderbook simulation, lalu RiskGate/executor validation.
- Green objective tidak diperlakukan sebagai angka statis. `daily_context` memberi deadline mode, color state, dan remaining time supaya council tahu kapan harus oportunistik, kapan harus preserve green, dan kapan harus stop mengejar setup buruk.
- Universal lead-lag scanner tetap dicatat sebagai konteks, tetapi tidak lagi membangunkan Council sendirian jika tidak ada sinyal Indodax/Polymarket yang tradeable.
- `coin_category.py` menjadi intelligence layer untuk fallback non-pump: `HIGH_LIQUIDITY_MAJOR`, `BTC_ETH_BETA`, `AI_BIG_DATA`, `RWA_DEFI`, `MEME_ROTATION`, dan `LOCAL_MOMENTUM`. Scanner menempelkan `fallback_category`; Council dan Executor mempertahankannya sampai active trade audit.
- Unit-price law aktif: setiap BUY Indodax wajib harga 1 unit koinnya strict di bawah total saldo/equity saat itu. `RiskGate` dan `IndodaxExecutor` sama-sama menolak `price_idr >= total_equity_idr`.

## Key Files
- `kibot_ai_coordinator.py`: Main AI signal processor.
- `kibot_whatif_engine.py`: Mathematical risk simulator.
- `kibot_learning_engine.py`: also tracks daily trade activity for probe logic.
- `kibot_rag.py`: Local knowledge retrieval.
- `kibot_ai_scout.py`: Live market scout / intel collector.
- `kibot_ollama_gateway.py`: Local LLM gateway that now loads sovereign env explicitly and fails closed when the runtime secret is missing.
- `SovereignCouncil`: deliberation engine yang menggabungkan what-if snapshot dan evidence web sebelum final mandate.
- `kibot_ollama_gateway.py`: Local LLM gateway.
- `daily_context.py`: WIB business-day context, daily color, deadline pressure, and trade posture.
- `decision_journal.py`: Runtime audit trail for scanner, council, simulation, and executor decisions.
- `pre_trade_simulator.py`: Pre-entry orderbook feasibility and size sanity check.
- `market_heatmap.py`: Indodax breadth and pump-market regime snapshot.
- `probability_engine.py`: Green-probability estimator for deadline-aware decisioning.
- `daily_report.py`: Midnight Telegram report builder.
