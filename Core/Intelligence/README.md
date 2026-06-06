# KiBot Intelligence

Folder ini berisi intelligence, council, dashboard, learning, dan audit layer untuk runtime **Indodax-only**.

## Runtime Scope
- Venue aktif: Indodax spot.
- Canonical truth: `state/live_truth.json`.
- Canonical accounting: Indodax total equity = liquid IDR + held coin mark-to-market + pending/order reserve yang valid.
- Route wallet eksternal, chain execution, prediction market, asset movement, dan withdrawal sudah dihapus dari runtime.

## Core Responsibilities
- `aggregator.py`: menyusun konteks portfolio, scanner, heatmap, trade history, dan accounting truth untuk council.
- `kibot_ai_coordinator.py`: menjalankan AI/advisory stack untuk diagnosis, kritik strategi, dan ringkasan, bukan approval order.
- `kibot_ai_scout.py`: patrol 5 menit untuk market/news/tooling/server readiness.
- `kibot_dashboard.py`: web control plane yang membaca live truth dan state Indodax.
- `decision_journal.py`: audit trail scanner, council, simulator, executor, dan verifier.
- `trade_history.py`: riwayat trade manusiawi dengan PnL fee-aware.
- `pre_trade_simulator.py`: hard feasibility check sebelum entry.
- `market_heatmap.py`: breadth Indodax dan market regime.
- `probability_engine.py`: estimasi probabilitas harian untuk menjaga sistem tidak overtrade.
- `daily_report.py`: report harian Telegram yang ringkas.

## AI Rules
- AI boleh mendiagnosis, merangkum, mengkritik, dan memberi rekomendasi parameter.
- AI tidak boleh mengeksekusi order, menaikkan sizing, mengabaikan EV, atau bypass risk gate.
- Keputusan order tetap deterministic dan harus tercatat di decision journal.

## Operational Notes
- `bin/kibotctl` adalah entrypoint operator untuk status, doctor, restart, model sync, dan tools.
- `systemd` adalah source of truth runtime Batam.
- Dashboard tidak boleh membaca state legacy sebagai sumber uang utama.
- Jika docs/runtime inventory berubah, update README dan inventory supaya AI server tidak membaca kontrak lama.
