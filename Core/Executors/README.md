# ⚙️ KiBot Executors

Executor layer menerima sinyal yang sudah divalidasi lalu mengeksekusi order secara balance-aware.

## Alur
- `indodax_executor.py`: eksekusi spot Indodax, budget allocation, fee-aware checks.
- `polymarket_executor.py`: eksekusi Polymarket, balance-aware USDC sizing.

## Catatan Operasional
- Budget dihitung dari saldo aktif dan slot yang tersedia.
- Trade ditolak jika harga 1 koin terlalu besar terhadap budget efektif setelah fee.
- Hindari double-start service jika node dijalankan via `systemd`.
- Canonical systemd unit untuk executor Indodax adalah `kibot-executor.service`.
- Runtime trade state ditulis ke `state/active_trades.json` di root repo.
