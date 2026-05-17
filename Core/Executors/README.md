# ⚙️ KiBot Executors

Executor layer menerima sinyal yang sudah divalidasi lalu mengeksekusi order secara balance-aware dan risk-adjusted melalui Capital Commander.

## Multi-Sector Sovereign Hedge Fund
KiBot tidak lagi hanya trading spot di Indodax. KiBot sekarang mengeksekusi 10 Strategi Web3 Mandiri menggunakan infrastruktur **Phantom Router (EVM & SPL)** yang sudah di-harden dengan error-handling dan circuit breakers:

1. **Prediction Markets** (`polymarket_executor.py`): Eksekusi Polymarket (Polygon).
2. **Yield Farming** (`defi_yield_executor.py`): Pasok aset ke Kamino Finance (Solana) saat modal sedang *idle*.
3. **Perpetual DEX** (`defi_perp_executor.py`): Buka posisi Long/Short di Drift Protocol (Solana) sebagai *hedging*.
4. **Meme Sniping** (`solana_executor.py`): Beli aset spekulatif via Jupiter dengan high-slippage (Solana).
5. **Liquid Staking** (`defi_yield_executor.py`): Konversi SOL ke JitoSOL untuk *passive income*.
6. **Airdrop Farming**: Interaksi volume rendah secara berkala pada protokol baru.
7. **Liquidity Provision (LP)**: Pemasokan likuiditas terpusat di Orca/Meteora.
8. **Cross-Chain Bridging** (`bridge_router.py`): Pemindahan dana antar-chain via DeBridge/Wormhole.
9. **NFT Lending** (`defi_nft_executor.py`): Pinjaman (Lending) aset digital di SharkyFi untuk *high yield*.
10. **MEV Arbitrage** (`solana_executor.py`): Arbitrase kilat lintas-DEX di ekosistem Solana.

## Alur Eksekusi
- `indodax_executor.py`: eksekusi spot Indodax, budget allocation, fee-aware checks.
- Executor menerima mandat yang sudah lolos evidence bundle council (BULL/CRAB/BEAR regime), jadi keputusan bukan cuma dari satu sinyal mentah.
- Semua eksekusi Web3 dilalui via `PhantomRouter` yang mengabstraksi Private Key dan validasi saldo (`balance-aware`).
- Jika saldo CEX stagnan, Capital Commander memutar uang ke DeFi (Yield/NFT Lending) agar tidak ada modal *idle*.

## Catatan Operasional
- Budget dihitung dari saldo aktif dan slot yang diizinkan oleh `CapitalCommander`.
- Jika `PhantomRouter` mendeteksi error pada RPC, RPC failover circuit breaker aktif dan Executor mengembalikan status ke `WAIT`.
- Trade ditolak jika harga 1 koin terlalu besar terhadap budget efektif setelah fee.
- Order real-money hanya dibuka jika `KIBOT_LIVE_TRADING_ENABLED=true` atau `KIBOT_TRADING_MODE=live`.
- Canonical systemd unit untuk executor Indodax adalah `kibot-executor.service`.
- Runtime trade state ditulis ke `state/active_trades.json` di root repo.
- Executable env untuk systemd di-load dari `/home/ubuntu/KiBot/.env` dan `/home/ubuntu/KiBot/.env.kiv`. Khusus untuk Web3, `PHANTOM_PRIVATE_KEY` dan `SOLANA_RPC_URL` wajib terisi.
