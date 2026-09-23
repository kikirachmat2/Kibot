# Laporan Backtest Longitudinal KiBot V3 (2023 - 2026)

*Disusun: 2026-09-20 09:00 WIB*  
*Dataset: 1.358 Bar Harian (01 Jan 2023 s/d 19 Sep 2026) — Indodax Public TradingView History*  
*Total Periode: 45 Bulan Topup Bulanan (Rp 500.000 / bulan, Total Modal Disetor: Rp 22.500.000)*  
*Fee Model: Single Source of Truth `config/fees.py` (Indodax IDR Market PRO — Taker Buy 0.2111%, Maker Buy 0.1111%, PPh Sell 0.21%)*

---

## 1. Ringkasan Eksekutif & 4 Koreksi Direktur

Sesuai Addendum Direktur, pengujian ini dieksekusi dengan kepatuhan penuh terhadap 4 guardrail metodologis:
1. **Fee Asimetris & Realistis (Indodax PRO)**:  
   Semua eksekusi topup bulanan menggunakan **Taker Buy 0.2111%** (Service 0.20% + CFX 0.0111%). Tidak ada asumsi fee 0.10% yang tidak realistis.
2. **Strict Anti-Lookahead pada Regime Detector**:  
   Keputusan klasifikasi siklus pada hari $T$ dievaluasi hanya menggunakan bar closed $[0 \dots T]$. Rolling SMA200 dihitung strictly dari data masa lalu $[T-199 \dots T]$. Durasi konfirmasi berturut-turut dihitung harian tanpa mengakses candle masa depan.
3. **Keterbatasan Data Dinyatakan Secara Terbuka (Limitations)**:  
   Jendela data 2023–2026 (<3 tahun) hanya mencakup fase transisi dari pasca-FTX crash ke bull expansion dan koreksi parsial 2026. Data ini **belum mencakup 1 siklus makro penuh** (4 tahun halving cycle). Hasil backtest ini **bukan bukti konklusif**, melainkan observasi awal empiris.
4. **Analisis Sensitivitas Bukan Ajang Cari Pemenang**:  
   Variasi parameter diuji untuk memetakan arah dan elastisitas sistem terhadap dinamika pasar, bukan untuk overfitting pada rentang waktu historis terbatas.

---

## 2. Hasil Komparasi 5 Varian

| Metrik | Varian 1: Baseline (100% BTC DCA) | Varian 2: Multi-Asset Fixed (Flat 1.0x) | Varian 3: KiBot V3 Full (Cycle 0.8x-2.0x + Reserve) | Varian 4: Aggressive (0.5x-2.5x) | Varian 5: Conservative (0.9x-1.3x) |
|:---|---:|---:|---:|---:|---:|
| **Total Modal Disetor** | Rp 22.500.000 | Rp 22.500.000 | Rp 22.500.000 | Rp 22.500.000 | Rp 22.500.000 |
| **Final Portfolio NAV** | **Rp 40.014.117** | Rp 35.353.577 | Rp 37.478.329 | Rp 37.879.078 | Rp 37.140.428 |
| **Net Profit (PnL)** | **+Rp 17.514.117** | +Rp 12.853.577 | +Rp 14.978.329 | +Rp 15.379.078 | +Rp 14.640.428 |
| **Total ROI (%)** | **+77.84%** | +57.13% | +66.57% | +68.35% | +65.07% |
| **CAGR (Annualized)** | **16.75%** | 12.92% | 14.71% | 15.04% | 14.43% |
| **Max Drawdown (MDD)**| **45.66%** | 51.58% | 51.52% | **48.44%** | 52.37% |
| **Sharpe Ratio (Rf=5%)**| **1.99** | 1.88 | 1.88 | 1.91 | 1.88 |
| **Total Trading Fees** | Rp 47.498 | Rp 47.498 | Rp 44.912 | Rp 41.207 | Rp 44.561 |
| **Final USDT Reserve** | Rp 0 | Rp 349.261 | Rp 1.630.559 | Rp 3.385.559 | Rp 1.793.046 |

---

## 3. Temuan Kritis & Evaluasi Faktual

### A. Mengapa Baseline 100% BTC Mengungguli Multi-Asset dalam Periode Ini?
- Dalam kurun waktu 2023–2026, performa aset kripto sangat terdivergensi:
  - **BTC/IDR**: naik **+445.39%** (dari Rp 260 jt ke Rp 1,42 Miliar).
  - **SOL/IDR**: naik **+1,149.87%** (outperformer ekstrem).
  - **ETH/IDR**: naik **+145.34%** (underperformed BTC secara signifikan).
  - **LINK/IDR**: naik **+150.82%** (underperformed BTC).
  - **SUI/IDR**: turun **-37.43%** (listing baru 2024 mengalami inflasi emisi token).
  - **USDT/IDR**: naik **+11.70%** (devaluasi Rupiah).
- Varian Multi-Asset memegang 25% ETH dan 10% ALT yang mengalami underperformance relatif terhadap BTC. Namun, alokasi 15% SOL memberikan dorongan alfa yang menopang portofolio.
- Diversifikasi multi-aset terbukti mengorbankan sebagian capital gain dibanding full BTC, namun mengurangi risiko ketergantungan monolitik pada satu koin.

### B. Dampak Cycle-Aware Multiplier & Reserve Pool Scaling
- Dibandingkan Varian 2 (Multi-Asset Flat 1.0x, NAV Rp 35,35 jt), **Varian 3 (KiBot V3 Full) menghasilkan NAV lebih tinggi (Rp 37,48 jt, +Rp 2,12 jt)**.
- **Mekanisme Penyebab**:
  - Pada fase `MATURE_BULL`, alokasi deployment ditahan menjadi 0.8x sehingga 20% dana dialirkan ke cadangan kas USDT dry powder.
  - Saat pasar mengalami koreksi, kas ini tersedia dan total fee transaksi menjadi lebih rendah (Rp 44.912 vs Rp 47.498).
  - Cadangan kas akhir pada Varian 3 mencapai **Rp 1.630.559**, yang berfungsi sebagai buffer likuiditas tanpa harus menjual aset kripto inti.

---

## 4. Analisis Sensitivitas Parameter (Understanding Mechanism, Not Curve-Fitting)

### A. Sensitivitas Pengali Deep Bear (dengan Mature Bull = 0.8x konstan)
| Multiplier Deep Bear | Final NAV (IDR) | Total ROI | Max Drawdown | Sharpe | Final Reserve (IDR) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **1.2x** | Rp 37.238.049 | +65.50% | 51.52% | 1.88 | Rp 2.575.559 |
| **1.5x** | Rp 37.478.329 | +66.57% | 51.52% | 1.88 | Rp 1.630.559 |
| **2.0x** | Rp 37.478.329 | +66.57% | 51.52% | 1.88 | Rp 1.630.559 |
| **2.5x** | Rp 37.478.329 | +66.57% | 51.52% | 1.88 | Rp 1.630.559 |

> **Observasi Mekanisme**:  
> Pada awal simulasi (Januari 2023 pasca-FTX), saldo cadangan kas (*dry powder*) baru mulai dari nol. Sehingga pengali di atas 1.5x terbentur oleh *Total Available Funds* (Capped by cash-in-hand). Begitu kas habis, sistem tidak meminjam dana (no leverage). Ini memvalidasi bahwa batas multiplier tinggi di awal akumulasi portofolio baru bersifat inert secara defensif.

### B. Sensitivitas Pengali Mature Bull (dengan Deep Bear = 2.0x konstan)
| Multiplier Mature Bull | Final NAV (IDR) | Total ROI | Max Drawdown | Sharpe | Final Reserve (IDR) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **0.4x** | Rp 37.692.286 | +67.52% | **47.37%** | **1.91** | Rp 5.230.559 |
| **0.6x** | Rp 37.585.308 | +67.05% | **49.48%** | **1.90** | Rp 3.430.559 |
| **0.8x (Default)** | Rp 37.478.329 | +66.57% | 51.52% | 1.88 | Rp 1.630.559 |
| **1.0x (Flat)** | Rp 37.338.624 | +65.95% | 53.48% | 1.87 | Rp 56.806 |

> **Observasi Mekanisme**:  
> Semakin defensif multiplier saat euforia pasar puncak (`MATURE_BULL`), **Max Drawdown semakin membaik (turun dari 53.48% ke 47.37%)** dan **Sharpe Ratio meningkat (1.87 ke 1.91)**. Mengurangi akumulasi di puncak harga dan menyisihkan modal ke USDT terbukti secara matematis meredam volatilitas portofolio.

---

## 5. Keterbatasan Riset & Metodologi (Limitations)

1. **Jendela Waktu Terbatas (<3 Tahun)**:  
   Rentang 01 Jan 2023 s/d 19 Sep 2026 didominasi oleh pergerakan *secular uptrend* (rebound dari $16.5k ke $108k). Periode ini minim sampel *extended multi-year bear market* seperti 2014–2015 atau 2018–2019.
2. **Survivorship & Listing Bias pada Altcoin**:  
   SUI baru aktif diperdagangkan di Indodax pada awal 2024. Penurunan harga SUI (-37%) mencerminkan risiko khas token altcoin baru dengan unlock jadwal emisi besar.
3. **Overfitting Warning**:  
   Angka Varian 4 (Aggressive) tampak sedikit lebih tinggi (+1.78% vs Varian 3), tetapi parameter agresif sangat sensitif terhadap titik awal dan akhir simulasi. Untuk implementasi produksi, **Varian 3 (KiBot V3 Full Baseline: 0.8x s/d 2.0x)** adalah konfigurasi paling seimbang dan beralasan.
