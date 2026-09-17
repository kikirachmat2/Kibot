# EVALUASI STRATEGIS KUANTITATIF & BASELINE BACKTEST KIBOT V2 (REVISED)

> **Status Dokumen**: RESMI & MENGIKAT (BASELINE DIREKSI).  
> **Tanggal Efektif**: 17 September 2026.  
> **Klasifikasi**: *Pre-Implementation Research & Backtest Framework*.  
> **Pemberitahuan Khusus**: **Option D dinyatakan PRELIMINARY, belum boleh jadi dasar produksi sampai seluruh protokol backtest pada 3 skenario historis lulus uji statistik.**

---

## 1. MODEL BIAYA SEJATI (OFFICIAL REGULATORY FRICTION BASELINE)

Berdasarkan regulasi resmi pasar kripto Indonesia (PMK 50/2025 berlaku sejak 1 Agustus 2025, Indodax Pro Mode IDR, dan Bursa Berjangka Kripto CFX per Maret 2026):

### 1.1 Skenario A — Limit Order (Maker) di Kedua Sisi
- **Exchange Trading Fee**: $0.10\% \text{ buy} + 0.10\% \text{ sell} = 0.20\%$
- **Pajak PPh Final Pasal 22**: $0.21\%$ (hanya dipungut 1 kali saat transaksi PENJUALAN; pembelian bebas PPN)
- **Fee Kliring & Bursa CFX**: $0.0111\% \times 2 = 0.0222\%$
- **Spread Cost**: $0.10\%$ (antrean limit order pasif di spread L1/L2)
- **Slippage Pasif (Queue Drift)**: $0.03\%$
- **TOTAL FRIKSI MAKER BTC/ETH = $\mathbf{0.5622\% \approx 0.56\%}$** *(Altcoin SOL/AVAX: $\mathbf{0.70\%}$)*

### 1.2 Skenario B — Market Order (Taker) di Kedua Sisi
- **Exchange Trading Fee**: $0.20\% \text{ buy} + 0.20\% \text{ sell} = 0.40\%$
- **Pajak PPh Final**: $0.21\%$
- **Fee CFX**: $0.0222\%$
- **Spread Crossing**: $0.10\%$
- **Execution Slippage**: $0.05\%$
- **TOTAL FRIKSI TAKER BTC/ETH = $\mathbf{0.7822\% \approx 0.78\%}$** *(Altcoin SOL/AVAX: $\mathbf{0.95\%}$)*

> [!CAUTION]
> **Audit Status Sistem Saat Ini**: `KiBot V2/executor/virtual_ledger.py` saat ini adalah **100% TAKER-ONLY** (menyapu kedalaman order book dengan `analyze_orderbook()`, fee $0.21\%$ per sisi, dan $100\%$ fill instan). Selama belum diubah menjadi Maker Limit Order, bot terbebani friksi **$0.78\% - 0.95\%$**.

---

## 2. KOREKSI SISTEMATIS SIMULASI (FAKTOR 2 & REALITY CHECK)

Pada audit awal, terjadi kesalahan pembagian dua pada kalkulasi total friksi nominal:
- **Option B (28 trade, Taker $0.88\%$)**: Friksi aktual adalah $\text{Rp } 1.232.000$ (bukan Rp 616.000). Net PnL riil = **$\mathbf{-Rp\ 201.600\ (-2.02\%)}$**.
- **Option C (21 trade, Taker $0.95\%$)**: Friksi aktual adalah $\text{Rp } 997.500$ (bukan Rp 498.750). Net PnL riil = **$\mathbf{-Rp\ 39.900\ (-0.40\%)}$**.

**Kesimpulan**: Seluruh strategi rotasi berbasis **Taker Market Order** terbukti matematis **NET NEGATIF (MERUGI)**. Maker Limit Order adalah prasyarat mutlak.

---

## 3. OXFORD ADVERSE SELECTION PENALTY & REALISTIC EXECUTION MODEL

Mengacu pada riset kuantitatif University of Oxford (*"Lead-Lag and High-Frequency Execution Risk"*):
1. **Adverse Selection pada Lead-Lag ($40\%$ PnL Discount)**:  
   Sinyal dislokasi lead-lag sangat padat (*crowded*). Eksekusi hanya berhasil terisi ketika tren berbalik (*false lead*), dan gagal terisi ketika harga terus lari menguntungkan (*winner slip*).
2. **Adverse Selection pada Mean Reversion ($30\%$ PnL Discount)**:  
   Limit order di Lower Bollinger Band menghadapi fenomena *falling knife*: order terisi $100\%$ saat terjadi penembusan tren ekstrem (*catastrophic breakdown*), dan tidak terisi ($0\%$) saat harga memantul tipis sebelum menyentuh band.
3. **Fill Rate Constraint**:  
   Asumsi $100\%$ fill instan pada paper trading diubah menjadi model probabilistik **$85\%$ fill rate** untuk limit order pasif.

---

## 4. DEFINISI 4 KANDIDAT STRATEGI UNTUK UJI BACKTEST

| Opsi Strategi | Basis Logika | Timeframe | Order Type | Lead-Lag Filter Wajib |
| :--- | :--- | :---: | :---: | :--- |
| **Option D1** | Mean Reversion Lower BB touch murni | 1-Hour (1H) | Maker Limit | None (Unfiltered baseline) |
| **Option D2** | MR 1H Lower BB touch + BB Bandwidth Squeeze (< P20) | 1-Hour (1H) | Maker Limit | None (Volatility filter only) |
| **Option D3** | MR 1H Lower BB touch + Filter Squeeze + Filter Lead-Lag | 1-Hour (1H) | Maker Limit | **Wajib**: Binance 1h momentum $\ge -0.50\%$, Pearson corr $\ge 0.80$ |
| **Option C'** | High-Conviction Lead-Lag Multi-Pair (Dislokasi $\ge 2.0\%$) | 15-Min / 1H | Maker Limit | Primary Trigger + OFI Aggressor Volume Confirmation |

---

## 5. PROTOKOL & AMBANG BATAS KELULUSAN BACKTEST (DECISION GATES)

Strategi **DITOLAK** dan dilarang masuk ke tahap implementasi shadow engine jika gagal di salah satu dari 3 skenario data historis:
1. **Skenario 1**: 2023 Full Year (Rezim pasar campuran bull/bear/consolidation).
2. **Skenario 2**: Q3 2024 (Rezim pasar konsolidasi mati / sideways summer).
3. **Skenario 3**: Jan 2025 - Sekarang (Rezim pasca-PMK 50/2025 dan fee structure terbaru).

### Syarat Kelulusan Mutlak (All 3 Scenarios Required):
- **Expectancy Mingguan Bersih**: $\mathbb{E}_{\text{weekly}} > +0.30\%$ setelah memotong seluruh friksi maker dan penalti adverse selection ($30\%$ untuk MR, $40\%$ untuk LL).
- **Profit Factor**: $\text{PF} > 1.20$.
- **Max Rolling 7-Day Drawdown**: $\text{MDD} < 4.0\%$.
- **Frekuensi Trade**: $\ge 5 \text{ trade per minggu}$ (memastikan perputaran modal nyata).
- **Signifikansi Statistik**: $N \ge 100 \text{ trades}$ total.
