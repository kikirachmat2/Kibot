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
- Order real-money hanya dibuka jika `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live`.
- Council sekarang punya confidence floor adaptif, jadi entry yang terlalu lemah akan masuk `WAIT` bukan dipaksa eksekusi.
- Hindari double-start service jika node dijalankan via `systemd`.
- Canonical systemd unit untuk executor Indodax adalah `kibot-executor.service`.
- Runtime trade state ditulis ke `state/active_trades.json` di root repo.
- Executable env untuk systemd di-load dari `/home/ubuntu/KiBot/.env` dan `/home/ubuntu/KiBot/.env.kiv` kalau tersedia.
