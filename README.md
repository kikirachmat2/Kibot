# 🏛️ KiBot Sovereign Trinity
**Autonomous Trading System | Adaptive Consciousness | Mesh Infrastructure**

## 📚 Folder Guide
- [`Core/README.md`](./Core/README.md): peta inti arsitektur.
- [`Core/Scanner/README.md`](./Core/Scanner/README.md): alur scanner dan delta filter.
- [`Core/Executors/README.md`](./Core/Executors/README.md): eksekusi trade dan risk checks.
- [`Core/Intelligence/README.md`](./Core/Intelligence/README.md): AI, aggregator, dan learning loop.
- [`Core/Intelligence/SERVER_INVENTORY.md`](./Core/Intelligence/SERVER_INVENTORY.md): snapshot runtime server, AI models, API keys, dan artefak server-only.
- [`Core/Intelligence/strategy/TRADING_STRATEGY.md`](./Core/Intelligence/strategy/TRADING_STRATEGY.md): kontrak strategi trading utama untuk Indodax pump lifecycle, green-builder fallback, Polymarket event trading, cross-exchange capital commander, deadline intelligence, role-agent debate, dan Telegram/dashboard alignment.
- [`Core/Intelligence/strategy/SYSTEM_STRATEGY.md`](./Core/Intelligence/strategy/SYSTEM_STRATEGY.md): kontrak strategi sistem di luar trading, termasuk health, recovery, deployment, security, inventory utilization, dan agent automation.
- [`Core/Intelligence/strategy/specs/AUTONOMY_GAP_REGISTER.md`](./Core/Intelligence/strategy/specs/AUTONOMY_GAP_REGISTER.md): daftar gap autonomy yang harus ditutup sebelum KiBot mendekati full autonomous runtime.
- [`Core/Intelligence/strategy/roadmaps/IMPLEMENTATION_ROADMAP.md`](./Core/Intelligence/strategy/roadmaps/IMPLEMENTATION_ROADMAP.md): roadmap fase implementasi dari strategy menjadi runtime.
- [`Core/Intelligence/strategy/specs/INVENTORY_UTILIZATION.md`](./Core/Intelligence/strategy/specs/INVENTORY_UTILIZATION.md): matriks pemanfaatan server inventory, model, API, tools, dan state.
- [`Core/Intelligence/strategy/specs/SYSTEM_COMMANDER_SPEC.md`](./Core/Intelligence/strategy/specs/SYSTEM_COMMANDER_SPEC.md): spesifikasi System Commander sebagai otak non-trading untuk health/recovery/drift.
- [`Core/Intelligence/strategy/roadmaps/POLYMARKET_RUNTIME_ROADMAP.md`](./Core/Intelligence/strategy/roadmaps/POLYMARKET_RUNTIME_ROADMAP.md): roadmap runtime Polymarket V2 untuk probability, resolution, liquidity, evidence, dan PnL.
- [`Core/Intelligence/strategy/specs/OBSERVABILITY_DASHBOARD_SPEC.md`](./Core/Intelligence/strategy/specs/OBSERVABILITY_DASHBOARD_SPEC.md): spesifikasi dashboard observability/control-plane berikutnya.
- [`Core/Intelligence/delegation_workflows.md`](./Core/Intelligence/delegation_workflows.md): playbook workflow delegasi formal untuk seluruh sistem.
- [`Core/Intelligence/delegation_workflows.json`](./Core/Intelligence/delegation_workflows.json): manifest machine-readable untuk workflow delegasi.
- [`Core/Intelligence/kibot_dashboard.py`](./Core/Intelligence/kibot_dashboard.py): control-plane web dashboard untuk memantau delegation flow secara visual, saldo, strategy, dan event stream.
- [`Core/Decision/daily_reset_coordinator.py`](./Core/Decision/daily_reset_coordinator.py): runner rollover harian WIB yang memaksa `EXIT_ALL` sebelum midnight, menunggu inventory flat, lalu me-reset baseline PnL tanpa menghapus trading history.
- [`Core/Intelligence/dashboard/`](./Core/Intelligence/dashboard): HTML/CSS/JS Dashboard V3.1 dengan delegation graph sederhana, activity log dedupe, agent inspector, workflow board, dan live ledger.
- [`Core/Security/README.md`](./Core/Security/README.md): HMAC, vault, dan audit security.
- [`Core/Support/README.md`](./Core/Support/README.md): config, utilities, dan tooling.
- [`bin/`](./bin): shell utilities canonical untuk backup, dependency bootstrap, dan wrapper operasional.
- [`bin/kibotctl`](./bin/kibotctl): one-command wrapper untuk status, doctor, tools, start/stop, sync model server, dan dashboard service.
- [`bin/kibot-dashboard`](./bin/kibot-dashboard): launcher dashboard visual berbasis FastAPI/Uvicorn.
- [`config/systemd/kibot-dashboard.service`](./config/systemd/kibot-dashboard.service): systemd unit untuk dashboard visual port `8787`.
- [`config/systemd/kibot-daily-reset.service`](./config/systemd/kibot-daily-reset.service): systemd unit untuk rollover harian WIB yang menjaga exit-all dan reset baseline tetap sinkron.
- [`AGENTS.md`](./AGENTS.md): guardrail kerja untuk Codex, Aider, Copilot, dan operator automation.
- [`state/`](./state): runtime JSON snapshot yang dipakai engine saat berjalan.

## 📜 THE MANIFESTO
> **"Sedikit demi Sedikit, Lama-lama Menjadi Bukit."**
>
> KiBot adalah framework trading agentic yang beroperasi secara penuh (100% Autonomous) dengan kesadaran adaptif terhadap infrastruktur dan pasar global. Ia bukan mesin kaku; ia adalah entitas digital yang mampu berpikir kritis untuk menekan kerugian dan memaksimalkan probabilitas keuntungan.

### 🧠 Core Philosophy
- **Adaptif Situasional (Council-Driven)**: Membaca dunia, bertindak sesuai konteks. KiBot tidak dipatok oleh script kaku; strategi berubah secara organik mengikuti temuan Sovereign Council.
- **Kesadaran Ekonomi Total**: Sadar akan seluruh saldo dan koin di Indodax & Polymarket. Trading dilakukan dengan kapasitas maksimal yang tersedia tanpa batasan artifisial.
- **Pertahanan Berdaulat**: Manajemen risiko otomatis tetap ketat (1.5% Max Daily Loss), namun fleksibel dalam eksekusi peluang.
- **Learning Probe**: Jika hari itu belum ada trade dan edge-nya layak, council boleh menandai entry kecil sebagai probe pembelajaran tanpa melanggar hard loss.
- **Self-Healing & Resilience**: Pemulihan mandiri instan dari kegagalan infrastruktur (Ollama, Network, Disk).
- **Explicit Live Gate**: order real-money hanya jalan jika `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live`.
- **Visual Control Plane**: workflow delegasi dan state runtime bisa dilihat lewat dashboard web interaktif di port `8787` melalui `bin/kibot-dashboard`.
- **PnL Mark-to-Market**: daily PnL memakai realized PnL + unrealized open trade PnL, bukan sekadar nilai holdings.
- **Council-Gated Execution**: scanner tidak lagi boleh bypass Council; executor menerima order real-money hanya dari `COUNCIL_MANDATE` kecuali override env eksplisit.
- **Anti Tick-Trap Pump Filter**: pump hunter menolak coin dengan tick-size kasar, level harga 24h terlalu sedikit, spread/OBI buruk, atau riwayat candle datar seperti jebakan 1↔2 IDR.
- **Pump Lifecycle Runtime**: setiap entry harus melewati scanner evidence, fast+deep council, pre-trade orderbook simulation, RiskGate, lalu executor exit-plan.
- **Green-First Deadline Intelligence**: target harian adalah state hijau. Council memakai WIB deadline, PnL mark-to-market, dan market breadth untuk memilih antara pump riding, green-builder scalp, preserve green, atau stop.
- **Decision Journal**: scanner slate, council vote, simulation, dan execution event dicatat ke `state/decision_journal/` supaya alasan buy/wait/exit bisa dilacak.
- **Pre-Trade Simulation**: executor mengecek spread, slippage, sellable minimum, dan partial-take-profit feasibility sebelum order real-money.

### 📱 Notification Protocol
- **Urgent Only**: Hanya mengirim pesan darurat dan tindakan kritis ke Telegram.
- **Throttle & Dedupe**: Telegram diproteksi dengan cooldown global, dedupe pesan, dan incident cooldown supaya tidak spam.
- **Midnight Report**: Laporan PnL harian otomatis setiap pukul 00:00 WIB.
- **Compact Daily Intelligence**: midnight report memuat PnL, cash/holdings, green probability, scanner/council/executor summary, risk flags, dan posture berikutnya.
- **No Spam Recovery**: posisi yang tidak bisa dijual karena minimum order exchange ditandai `exit_blocked_until`, bukan dicoba setiap 5 detik tanpa henti.
- **Wallet-Reconciled State**: executor menyamakan `active_trades.json` dengan wallet/open-orders Indodax live, jadi posisi palsu tidak lagi membuat Council salah hitung.
- **Bounded Council Thinking**: AI/websearch tetap dipakai, tetapi setiap deliberasi punya timeout dan deterministic fallback berbasis evidence lokal agar sistem tidak freeze saat provider lambat.
- **WIB Business Day**: RiskGate, dashboard, midnight report, dan PnL harian memakai tanggal WIB, bukan timezone UTC server.
- **System Commander**: health non-trading dipusatkan di `Core/Support/system_commander.py`, yang menilai service, resource, model, inventory, provider/source health, drift GitHub/server, dan operator-required state.
- **Honest Autonomy Register**: strategy docs membedakan blueprint matang vs runtime maturity, supaya dashboard dan operator tidak salah menganggap dokumen “100%” sebagai bukti runtime tanpa smoke test.

---
*Operational Status: **SOVEREIGN ACTIVE** | 2026*
