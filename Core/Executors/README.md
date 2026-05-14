# ⚙️ KiBot Executors

Executor layer menerima sinyal yang sudah divalidasi lalu mengeksekusi order secara balance-aware.

## Alur
- `indodax_executor.py`: eksekusi spot Indodax, budget allocation, fee-aware checks.
- `polymarket_executor.py`: eksekusi Polymarket, balance-aware USDC sizing.
- Executor menerima mandat yang sudah lolos evidence bundle council, jadi keputusan bukan cuma dari satu sinyal mentah.
- Jika council menandai `learning_probe`, executor akan mengecilkan size entry tetapi tetap menghormati hard risk gate.
- Polymarket executor memakai private key Phantom EVM yang diekspor sebagai EOA dan bootstrap API creds ke CLOB client sebelum order dikirim.

## Catatan Operasional
- Budget dihitung dari saldo aktif dan slot yang tersedia.
- Trade ditolak jika harga 1 koin terlalu besar terhadap budget efektif setelah fee.
- Untuk Indodax pump continuation, executor sekarang bisa melonggarkan momentum/confidence floor secara terkontrol jika scanner menandai `trend_continuation` atau `mature_pump`.
- Untuk wave yang sudah retrace lalu reclaim lagi, executor juga mengenali `pullback_reclaim` dan melonggarkan floor sedikit, tetapi hanya setelah fee, spread, dan balance checks tetap lolos.
- Untuk wave yang lebih jauh dari high, executor dapat mengenali `late_reclaim`, tetapi hanya bila recovery score dan volume persistence masih cukup kuat.
- Order real-money hanya dibuka jika `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live`.
- Council sekarang punya confidence floor adaptif, jadi entry yang terlalu lemah akan masuk `WAIT` bukan dipaksa eksekusi.
- Hindari double-start service jika node dijalankan via `systemd`.
- Canonical systemd unit untuk executor Indodax adalah `kibot-executor.service`.
- Runtime trade state ditulis ke `state/active_trades.json` di root repo.
- Executable env untuk systemd di-load dari `/home/ubuntu/KiBot/.env` dan `/home/ubuntu/KiBot/.env.kiv` kalau tersedia.
