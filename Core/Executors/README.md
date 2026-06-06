# KiBot Executors

Executor layer sekarang **Indodax-only**.

## Runtime Contract
- Executor aktif: `Core/Executors/Indodax/indodax_executor.py`.
- Canonical service: `kibot-executor.service`.
- Order real-money hanya boleh lewat live gate eksplisit dan deterministic risk checks.
- Tidak ada executor external wallet, chain route, prediction market, asset movement, withdrawal, atau non-Indodax route.
- State trade live ditulis ke `state/active_trades.json`, `state/orders/`, dan `state/trade_history/`.

## Execution Rules
- BUY hanya setelah scanner, council, expected value, pre-trade simulator, risk gate, dan balance checks lolos.
- Entry harus memastikan posisi nanti bisa dijual kembali dengan minimum order, depth, spread, fee, dan slippage yang masuk akal.
- Pending order yang stale harus dibatalkan, bukan dibiarkan mengejar harga lama.
- Exit harus fee-aware dan menggunakan real fill/reconciliation, bukan asumsi dashboard.
- Telegram hanya untuk exception penting dan trade summary, bukan spam kandidat.

## Operator Notes
- Jangan menambah ulang executor wallet/chain eksternal tanpa keputusan arsitektur baru.
- Jangan commit `.env`, API key, private key, seed phrase, atau secret.
- Gunakan `bin/kibotctl status` dan `bin/kibotctl doctor` untuk audit runtime Batam.
