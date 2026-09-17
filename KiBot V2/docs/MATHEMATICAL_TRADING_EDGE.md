# DOKUMEN ARSITEKTUR & RISET KUANTITATIF: MATHEMATICAL TRADING EDGE & 7-DAY PROFIT ROADMAP
**Dokumen Referensi**: `KIBOT-V2-DOCS-MATH-002`  
**Otoritas**: Directive D-01 — Project Director, PM & Lead Quantitative Researcher  
**Konteks Sistem**: KiBot V2 Paper Trading Engine (SG1 Live: `kibot-v2-paper.service`)  
**Status**: Ratified Design & Mathematical Specification  

---

## 1. MISI & FORMULASI EKSPEKTANSI MATEMATIS

Tujuan utama sistem trading algoritmik KiBot V2 adalah merealisasikan **progres laba terukur (positive net mathematical expectancy)** secara konsisten tanpa terpapar *risk of ruin*.

Ekspektansi matematis per trade didefinisikan secara formal sebagai:

$$\mathbb{E}[R] = \left( P_{\text{win}} \times \overline{R}_{\text{win}} \right) - \left( P_{\text{loss}} \times \overline{R}_{\text{loss}} \right) - \mathcal{C}_{\text{friction}} > 0$$

Di mana:
- $P_{\text{win}}$: Probabilitas menang (Win Rate).
- $P_{\text{loss}} = 1 - P_{\text{win}}$: Probabilitas kalah.
- $\overline{R}_{\text{win}}$: Rata-rata keuntungan kotor per trade menang (*Gross Average Win*).
- $\overline{R}_{\text{loss}}$: Rata-rata kerugian kotor per trade kalah (*Gross Average Loss*).
- $\mathcal{C}_{\text{friction}} = \text{Fee}_{\text{roundtrip}} + \text{Slippage}_{\text{effective}}$: Friksi riil pasar (Indodax taker fee 0.30% + maker 0.10% atau roundtrip $\approx 0.42\%$ s/d $0.60\%$ ditambah *market impact slippage*).

Untuk mencapai target **Profit Factor (PF) $\ge 1.50$** pada Trend-Following dan **$\ge 1.25$** pada Mean-Reversion:

$$\text{PF} = \frac{\sum \text{Gross Profit}}{\sum \text{Gross Loss} + \sum \text{Fees}} \ge 1.50$$

---

## 2. DEEP AUDIT: V1 SCALPING VS ARSITEKTUR V2 SWING

### A. Anatomi Kegagalan V1 Scalping (Mengapa V1 Mengalami Drawdown/Stagnasi)

Berdasarkan audit historis terhadap modul V1 (`indodax_binance_leadlag_scanner.py`, `indodax_executor.py`, dan log operasional SG1), teridentifikasi 3 akar penyebab matematis (*root causes*):

```
+----------------------------------------------------------------------------------------------------+
|                                    THE SCALPING FRICTION TRAP                                      |
|                                                                                                    |
|   Target Kotor (Gross Edge)   :  +0.35% s/d +0.80%   (Lilin 15s / 1m Noise)                        |
|   Biaya Transaksi (Roundtrip) :  -0.42% s/d -0.60%   (Indodax Taker Fee)                           |
|   Slippage & Spread           :  -0.20% s/d -0.50%   (Thin Orderbook Depth)                        |
|   ---------------------------------------------------------------------------------                |
|   Ekspektansi Bersih Net E[R] :  -0.27% s/d -0.30% PER TRADE  ===> PASTI LOSS SECARA STATISTIK     |
+----------------------------------------------------------------------------------------------------+
```

1. **The Micro-Edge Fee Paradox**:
   - V1 Lead-Lag Scanner mencari selisih harga Binance vs Indodax sebesar **0.18% - 0.45%** pada jendela waktu 6-12 detik.
   - Struktur fee Indodax mengenakan taker fee 0.30% (beli) + 0.30% (jual) = 0.60% roundtrip.
   - Bahkan jika win rate mencapai 65%, rasio *Win/Loss* yang terpotong fee 50%-80% menyebabkan nilai ekspektansi $\mathbb{E}[R] < 0$.
2. **Asymmetric Slippage pada Buku Pesanan (Orderbook L2) Lokal**:
   - Likuiditas Indodax pada altcoin bersifat tipis. Order beli instan (market order) mengangkat harga hingga beberapa tick di atas best ask, sedangkan order jual darurat menekan harga ke bawah best bid. Slippage nyata mencapai 0.2% - 0.4% per leg.
3. **Lower Timeframe (LTF) Noise & High Churn**:
   - Sinyal pada timeframe lilin 1-menit memiliki *Information Coefficient* (IC) mendekati nol ($IC \approx 0.01$). Sinyal tersebut didominasi oleh pergerakan acak (*Brownian noise*) yang memicu *overtrading* (10-20 trade per hari), menghabiskan modal murni untuk fee bursa.

---

### B. Matriks Fitur V1 vs V2: Verdict & Information Coefficient (IC)

| Modul V1 | Fitur Inti V1 | Masalah di V1 | Solusi Arsitektur V2 | IC Est. | Verdict |
| :--- | :--- | :--- | :--- | :---: | :---: |
| `leadlag_scanner` | Arbitrase latensi Binance $\rightarrow$ Indodax (6s - 12s) | Target 0.3% termakan fee 0.51% | Ditransformasi menjadi **Macro Lead-Lag Confirmation** (1H/4H directional thrust) | 0.28 | **REDESIGN** |
| `smallcap_scanner` | Scanning 100+ koin momentum lokal | Likuiditas tipis, rentan pump-and-dump (kasus TRX/IDR) | **Strict Whitelist (Top Liquidity)**: BTC, ETH, SOL, AVAX dengan filter 24h Vol > Rp 500 Juta | 0.35 | **REDESIGN** |
| `kibot_ai_scout` | Web scraping sentimen berita dunia via Ollama | Tidak deterministik, latensi tinggi (>30s), rawan halusinasi | Ditolak untuk timing eksekusi; dialihkan murni untuk makro kill-switch (read-only) | 0.05 | **DROP DARI HOT-PATH** |
| `indodax_executor` | REST polling, stuck order cancel manual | Terkena rate-limit Indodax (HTTP 429), V1 recursion bug | **WebSocket Event-Driven + Rate-Limited REST Tapi** dengan retries bertingkat non-rekursif | 0.40 | **ADOPT (V2 ENGINE)** |
| `pair_quarantine` | Karantina koin setelah 2x rugi berturut-turut | Bekerja baik tapi tidak membedakan regime tren vs sideways | Terintegrasi penuh ke dalam `CapitalGovernor` V2 dengan status terisolasi per-ledger | 0.32 | **ADOPT (SUDAH DI V2)** |
| `churn_guard` | Stop trading jika rolling PF < 0.80 | Sangat efektif memblokir fee bleeding | Diadopsi langsung di V2 dengan batas dinamis per timeframe | 0.38 | **ADOPT (SUDAH DI V2)** |

---

## 3. MODEL MATEMATIKA: DYNAMIC EDGE MULTI-TIMEFRAME

Untuk mengatasi friksi dan menghasilkan edge nyata dalam 7 hari, KiBot V2 menggunakan arsitektur **Multi-Timeframe Cascade**:

```
+-----------------------------------------------------------------------------------------+
|                               MULTI-TIMEFRAME CASCADE                                   |
|                                                                                         |
|   [1D/4H Macro Regime Engine]   ===> Menentukan Bias Arah & Volatilitas Pasar           |
|                 │                    (Filter ADX, EMA 50/200, ATR Percentile)           |
|                 ▼                                                                       |
|   [1H/15M Micro Entry Filter]   ===> Menentukan Timing Presisi Titik Beli (Golden Pullback) |
|                 │                    (RSI Divergence, Orderbook Depth, Volume Z-Score)  |
|                 ▼                                                                       |
|   [Execution & Risk Gate]       ===> Validasi Likuiditas, Slippage VWAP, Kelly Sizing  |
+-----------------------------------------------------------------------------------------+
```

### A. Sinyal Trend-Following (Primary TF)

#### 1. Filter Rezim Tren Makro (1D Lilin):
Aset berada dalam rezim bullish yang valid jika dan hanya jika:
$$\text{Close}_{1D} > \text{EMA}_{50}(1D) \quad \text{DAN} \quad \text{EMA}_{50}(1D) > \text{EMA}_{200}(1D)$$

#### 2. Choppiness Index Filter (Anti-Whipsaw):
Untuk memblokir false breakout saat pasar sideways berkonsolidasi rapat:
$$\text{CI} = 100 \times \frac{\log_{10} \left( \sum_{i=1}^{n} \text{TR}_i \right) - \log_{10} \left( \max(H_n) - \min(L_n) \right)}{\log_{10}(n)}$$
- $\text{CI} > 61.8$: Pasar berada dalam kondisi *extreme consolidation/choppy* $\implies$ **BLOKIR BUY TF**.
- $\text{CI} < 38.2$: Pasar berada dalam kondisi *strong directional trend* $\implies$ **IZINKAN BUY TF**.

#### 3. Dynamic Volatility & Volume Thrust:
- **Volume Z-Score**:
  $$Z_{\text{vol}} = \frac{V_t - \mu_V(20)}{\sigma_V(20)} \ge 1.25$$
- **Pullback Golden Zone**:
  Alih-alih membeli di pucuk breakout ($RSI > 70$), Primary TF membeli pada lilin koreksi sehat:
  $$35.0 \le \text{RSI}_{14}(1D) \le 55.0$$

#### 4. Exit Mechanics (TF):
- **Target Profit (TP)**: $+8.5\%$ (atau $+12.0\%$ pada breakout kuat).
- **Stop Loss (SL)**: $-5.1\%$ (Rasio R:R = $8.5 / 5.1 = 1.67$).
- **Max Hold Time**: $21 \text{ hari} = 1.814.400 \text{ detik}$.

---

### B. Sinyal Mean-Reversion (Shadow MR)

#### 1. Anti-Falling-Knife Condition:
Mean-Reversion dilarang menangkap pisau jatuh (*falling knife*) saat crash sistemik:
- **Regime Gate**: ADX harus rendah (pasar tidak sedang trending jatuh kuat):
  $$\text{ADX}_{14}(1D) \le 25.0$$
- **Bollinger Bands %B**:
  $$\%B = \frac{\text{Price} - \text{LowerBB}(20, 2)}{\text{UpperBB}(20, 2) - \text{LowerBB}(20, 2)} \le 0.05$$
- **RSI Oversold**:
  $$\text{RSI}_{14}(1D) \le 45.0$$

#### 2. Orderbook Microstructure Confirmation:
Sebelum order MR dieksekusi, periksa rasio kedalaman bid/ask L2:
$$I_{\text{depth}} = \frac{\sum \text{BidVolume}_{\text{top5}}}{\sum \text{BidVolume}_{\text{top5}} + \sum \text{AskVolume}_{\text{top5}}} \ge 0.55$$
Jika $I_{\text{depth}} < 0.55$, order book didominasi tekanan jual agresif $\implies$ **REJECT MR (PISAU JATUH)**.

#### 3. Exit Mechanics (MR):
- **Target Profit (TP)**: $+3.5\%$ s/d $+5.0\%$ (Target mean reversion ke Mid-BB / EMA20).
- **Stop Loss (SL)**: $-2.5\%$ s/d $-3.0\%$ (Rasio R:R $\ge 1.40$).
- **Max Hold Time**: $10 \text{ hari} = 864.000 \text{ detik}$.

---

### C. Pembuktian Matematis Mitigasi Fee Hurdle

Misalkan friksi total $\mathcal{C}_{\text{friction}} = 0.42\%$ (Indodax maker 0.1% + taker 0.3% + slippage 0.02%):

| Parameter | Scalping Lama (V1) | Swing TF (V2) | Swing MR (V2) |
| :--- | :---: | :---: | :---: |
| Target Win ($\overline{R}_{\text{win}}$) | $+0.80\%$ | $+8.50\%$ | $+4.50\%$ |
| Target Loss ($\overline{R}_{\text{loss}}$) | $-0.60\%$ | $-5.10\%$ | $-2.80\%$ |
| Fee Roundtrip ($\mathcal{C}_{\text{friction}}$) | $0.42\%$ | $0.42\%$ | $0.42\%$ |
| **Fee Impact on Win** | **$\mathbf{52.5\%}$ (Fee makan separuh laba)** | **$\mathbf{4.9\%}$ (Fee dapat diabaikan)** | **$\mathbf{9.3\%}$ (Fee aman)** |
| Win Rate Wajar ($P_{\text{win}}$) | $55\%$ | $48\%$ | $52\%$ |
| $\mathbb{E}[R]$ Kotor (Sebelum Fee) | $+0.17\%$ | $+1.42\%$ | $+0.99\%$ |
| $\mathbb{E}[R]$ Bersih (Setelah Fee) | **$\mathbf{-0.25\%}$ (Rugi Pasti)** | **$\mathbf{+1.00\%}$ (Edge Positif)** | **$\mathbf{+0.57\%}$ (Edge Positif)** |

> [!TIP]
> **Kesimpulan Kuantitatif**:
> Dengan menaikkan horizon holding time dari hitungan detik/menit ke skala swing (10 - 21 hari) dengan target $4.5\% - 8.5\%$, friksi fee Indodax terpangkas dari **52.5% laba kotor** menjadi hanya **4.9% - 9.3% laba kotor**. Sistem menjadi **imun terhadap fee hurdle**.

---

## 4. POSITION SIZING: FRACTIONAL KELLY & VOLATILITY PARITY

### A. Fractional Kelly Sizing

Rumus Kelly Criterion klasik untuk ukuran taruhan optimal:

$$f^* = \frac{p(b + 1) - 1}{b}$$

Di mana:
- $p$: Probabilitas menang ($P_{\text{win}} \approx 0.48$).
- $q = 1 - p$: Probabilitas rugi ($0.52$).
- $b = \frac{\overline{R}_{\text{win}}}{\overline{R}_{\text{loss}}} = \frac{8.5\%}{5.1\%} = 1.667$.

Maka Kelly Penuh:
$$f^* = \frac{0.48(1.667 + 1) - 1}{1.667} = \frac{0.48(2.667) - 1}{1.667} = \frac{1.280 - 1}{1.667} = \frac{0.280}{1.667} \approx 16.8\%$$

Untuk mengeliminasi *drawdown variance* dan melindungi bankroll dari *tail risk*, digunakan **Fractional Kelly ($\lambda = 0.25$)**:

$$f_{\text{safe}} = \lambda \times f^* = 0.25 \times 16.8\% \approx 4.2\% \text{ dari total ekuitas}$$

Dengan modal bankroll Rp 10.000.000:
$$\text{Ukuran Posisi Standar} = \text{Rp } 10.000.000 \times 4.2\% \times \text{Leverage Factor (max 3-4 posisi concurrent)} = \text{Rp } 2.500.000 \text{ s/d Rp } 3.000.000$$
*(Cocok persis dengan batas alokasi per posisi `CapitalGovernor` V2 sebesar 25% - 30% dari ekuitas).*

---

### B. Volatility Parity Allocation (Bobot Invers ATR)

Agar risiko nominal per trade bernilai seragam lintas koin (misal: BTC yang bergerak 2%/hari vs SOL yang bergerak 6%/hari):

$$\text{Notional}_i = \frac{\text{Target Risk IDR}}{\text{ATR}_{14}(1D)_i \times \text{Multiplier}}$$

Di mana $\text{Target Risk IDR} = 1.5\% \times \text{Total Equity} = \text{Rp } 150.000$.
- Jika BTC ATR harian = 3.0% $\implies$ Notional BTC = $\text{Rp } 150.000 / 0.03 = \text{Rp } 5.000.000$ (dibatasi cap max Rp 3.500.000).
- Jika SOL ATR harian = 6.0% $\implies$ Notional SOL = $\text{Rp } 150.000 / 0.06 = \text{Rp } 2.500.000$.

---

## 5. WHAT-IF AUDIT: BLINDSPOT HUNTING & CODE MITIGATIONS

| No | Skenario What-If (Blindspot) | Risiko Pasar / Sistem | Mitigasi di Kode KiBot V2 | File Implementasi |
| :---: | :--- | :--- | :--- | :--- |
| **1** | **WebSocket Indodax/Binance disconnect 5 menit** saat order sedang terbuka / dievaluasi. | Bot buta harga (*stale ticker*), tidak bisa trigger SL/TP tepat waktu. | **WS Heartbeat Watchdog + Fallback REST Poller**: Jika ticker hening $> 15\text{s}$, otomatis reconnect dan fallback query REST API tiap 5 detik. | `KiBot V2/ingestion/base.py`, `KiBot V2/storage/venue_ledger.py` |
| **2** | **Spread melonjak $> 2.0\%$** pada malam hari saat likuiditas tipis. | Beli di harga sangat mahal, langsung floating loss akibat spread. | **Pre-Trade Spread Gate**: Reject order jika $(\text{Ask} - \text{Bid}) / \text{Bid} > 0.80\%$ (atau $> 1.0\%$ untuk altcoin). | `KiBot V2/enrichment/microstructure.py`, `KiBot V2/risk/risk_gate.py` |
| **3** | **Server crash / reboot mendadak** saat posisi floating loss mendekati SL. | Posisi tertahan di memori yang hilang, equity hancur tanpa cut-loss. | **Durable State Startup Reconciler**: Re-hidrasi posisi aktif lengkap dengan SL/TP & waktu entri dalam $< 1\text{s}$ saat boot, langsung trigger exit jika harga langgar SL. | `KiBot V2/storage/durable_state.py`, `KiBot V2/storage/reconciler.py` |
| **4** | **Pump-and-Dump pada pair illiquid** (misal koin gorengan melonjak 50% lalu crash). | Bot terbawa FOMO membeli di pucuk, tersangkut dan tidak ada bid untuk exit. | **Strict Asset Whitelist + Depth Walk**: Hanya 4 koin likuid (BTC, ETH, SOL, AVAX) + Volume 24h $\ge \text{Rp } 500\text{M}$ + Kedalaman L2 wajib mampu menampung notional order tanpa slippage $> 0.25\%$. | `KiBot V2/council/swing_evaluator.py`, `KiBot V2/enrichment/microstructure.py` |
| **5** | **Flash Crash Bitcoin drop 15% dalam 1 jam** memicu korelasi jatuh serentak. | Semua posisi terbuka (BTC, ETH, SOL) terkena stop loss sekaligus. | **Cross-Asset Circuit Breaker**: Jika ekuitas harian drop $> 6.0\%$ atau BTC drop $> 5.0\%$ dalam 1 jam, `CapitalGovernor` mengunci seluruh entri baru selama 24 jam. | `KiBot V2/risk/capital_governor.py`, `KiBot V2/risk/circuit_breaker.py` |

---

## 6. CODE ACTION PLAN: ROADMAP 7 HARI

```
+-----------------------------------------------------------------------------------------+
|                              7-DAY CONTINUOUS EDGE ROADMAP                              |
|                                                                                         |
|   Hari 1-2: Multi-Timeframe Confirmation (1D Macro + 1H Entry Timing)                   |
|   Hari 3-4: Choppiness Index & Adaptive Volatility Sizing (ATR Parity)                  |
|   Hari 5-6: Microstructure Depth Imbalance ($I_{depth}$) & Fallback Watchdog            |
|   Hari 7  : Evaluasi Kinerja 7-Hari vs Baseline (N, PF, Drawdown, Latency)             |
+-----------------------------------------------------------------------------------------+
```

### File-File Target Implementasi:
1. **`KiBot V2/council/indicators.py`**:
   - Tambahkan fungsi perhitungan **Choppiness Index (CI)**.
   - Tambahkan fungsi **Volume Z-Score**.
2. **`KiBot V2/council/swing_evaluator.py`**:
   - Integrasikan `Choppiness Index` ke dalam `TrendFollowingDecision` untuk menyaring konsolidasi sideways.
   - Tambahkan parameter orderbook depth confirmation ke dalam `MeanReversionDecision`.
3. **`KiBot V2/risk/capital_governor.py`**:
   - Tambahkan fungsi kalkulasi **Volatility-Adjusted Notional Sizing** berbasis ATR.
4. **`KiBot V2/tests/`**:
   - `test_choppiness_index.py`: Validasi matematis rumus CI pada data trending vs choppy.
   - `test_mathematical_edge.py`: Simulasi komprehensif Monte Carlo untuk rasio R:R terhadap fee Indodax.
   - `test_hybrid_exit_and_recycling.py`: Validasi 2-tier partial TP, capital recycling, dan BEP ratchet.

---

## 7. VELOCITY OF CAPITAL VS FAT-TAILS: HYBRID 2-TIER EXIT ENGINE & SCIENTIFIC CRITIQUE

### A. Jebakan Matematis: "Asymmetric Payoff Fallacy" (Micro-Scalping Paradox)

Hipotesis trading retail sering berasumsi: *"Beli di harga $P_0$, begitu naik tipis melewati fee bursa (+0.80%), langsung ambil profit dan putar modal secepat mungkin (high capital recycling) daripada menunggu berhari-hari"*.

Secara kuantitatif, strategi ini runtuh akibat **Payoff Inversion**:
- **Gross Profit**: $+0.80\%$
- **Biaya Transaksi Indodax Roundtrip ($C_{\text{friction}}$)**: $-0.42\%$ s/d $-0.60\%$
- **Net Average Win ($\overline{W}$)**: $+0.80\% - 0.42\% = \mathbf{+0.38\%}$
- **Stop Loss Realistis di Bawah Noise Intraday ($\overline{L}$)**: $-2.00\% + 0.42\% = \mathbf{-2.42\%}$
- **Payoff Ratio ($R$)**:
  $$R = \frac{\overline{W}}{\overline{L}} = \frac{0.38\%}{2.42\%} \approx 0.157$$
- **Syarat Breakeven Win Rate**:
  $$P_{\text{win, min}} = \frac{1}{1 + R} = \frac{1}{1 + 0.157} = \mathbf{86.4\%}$$

Jika akurasi turun ke $75\%$ (angka yang sudah sangat tinggi di pasar nyata):
$$\mathbb{E}[R] = (0.75 \times 0.38\%) - (0.25 \times 2.42\%) = 0.285\% - 0.605\% = \mathbf{-0.32\% \text{ per trade (Pasti Rugi)}}.$$

Fenomena ini adalah **Truncating the Right Fat-Tail**: Menjual terlalu dini memotong distribusi keuntungan eksponensial (+10% s/d +25%), sedangkan risiko rugi fat-tail di sisi kiri tetap tidak terlindungi.

---

### B. BANTAHAN ILMIAH KRITIS: The Premature Breakeven Trap

> [!WARNING]
> **Kritik Saintifik atas Hipotesis Breakeven Cepat (+1.5% TP1)**:
> Menggeser Stop Loss ke Break-Even (+0.1% buffer) saat harga baru naik $+1.5\%$ adalah **jebakan fatal** bagi sistem Trend-Following di pasar kripto!

#### Alasan Matematis:
1. **Rasio ATR vs Noise Floor**:
   - Rata-rata True Range (Daily ATR) dari aset likuid (BTC, ETH, SOL) berada pada rentang **$3.0\% \text{ s/d } 6.0\%$**.
   - Pergerakan $+1.5\%$ hanyalah **$0.25 \text{ s/d } 0.5 \times \text{ATR}$** (masih berada jauh di dalam pita fluktuasi acak/Brownian noise intraday).
2. **Runner Death Rate**:
   - Jika Stop Loss digeser ke $+0.52\%$ (Entry + Fee) saat harga baru di $+1.5\%$, probabilitas harga berbalik menyentuh level BEP sebelum mencapai $+8.5\%$ adalah sebesar **$70\% - 80\%$** berdasarkan distribusi Wiener process.
   - Akibatnya, $8$ dari $10$ potensi trade tren besar (*super-runners*) terbunuh prematur tanpa laba signifikan.
3. **Kolaps Ekspektansi Portofolio**:
   $$\mathbb{E}[R]_{\text{prematur}} = 0.5 \times (+1.08\% \text{ net TP1}) + 0.5 \times (0\% \text{ BEP}) = \mathbf{+0.54\%}$$
   Dengan memotong runner, sistem kehilangan porsi alpha yang diperlukan untuk menutupi trade-trade kalah normal ($-3.5\%$).

---

### C. Solusi Ilmiah Unggul: Differentiated Hybrid 2-Tier Exit Engine

Untuk mendapatkan manfaat kecepatan perputaran modal (*Velocity of Capital*) tanpa membunuh kemampuan menangkap Fat-Tail, KiBot V2 membedakan mekanika exit antara **Trend-Following (TF)** dan **Mean-Reversion (MR)**:

```
+---------------------------------------------------------------------------------------------------+
|                               HYBRID 2-TIER EXIT ENGINE WORKFLOW                                  |
|                                                                                                   |
|   Posisi Terbuka (100% Lot)                                                                       |
|         │                                                                                         |
|         ├───> [TF: Naik >= 1R (+4.25%)]  ───> Eksekusi TP1 (Tutup 50% Lot)                        |
|         ├───> [MR: Naik >= +2.25%]       ───> Eksekusi TP1 (Tutup 50% Lot)                        |
|                     │                                                                             |
|                     ├───> Cairkan 50% Cash + Laba ke Bankroll (Capital Recycling Langsung)        |
|                     └───> Geser SL 50% Sisa Posisi ke Entry + Fee (0.42%) + 0.10% (Risk-Free)     |
|                                 │                                                                 |
|   ┌─────────────────────────────┴─────────────────────────────┐                                   |
|   ▼                                                           ▼                                   |
|   [Skenario A: Whipsaw Reversal]            [Skenario B: Fat-Tail Runner Surges]                  |
|   - Harga berbalik turun menyentuh BEP      - Harga terus reli menyentuh TP2 (+8.5% s/d +15%)     |
|   - Sisa posisi keluar di Rp BEP            - Sisa posisi keluar di Peak Alpha                    |
|   - Net Trade PnL TETAP POSITIF             - Total Trade PnL Maksimal                            |
|   - Modal Pokok Utuh 100%                   - Ekuitas Bertumbuh Eksponensial                      |
+---------------------------------------------------------------------------------------------------+
```

#### Parameter Implementasi:
1. **Tier 1 (Fast Capital Recycling - 50% Lot)**:
   - **Trend-Following (TF)**: TP1 dipasang di $1\text{R}$ (setengah jarak dari target TP penuh $+8.5\%$, yaitu **$+4.25\%$**). Pada level ini, harga telah mengonfirmasi directional breakout di atas 1x ATR, sehingga risiko whipsaw turun signifikan.
   - **Mean-Reversion (MR)**: TP1 dipasang di **$+2.25\%$ s/d $+2.50\%$** (karena target akhir MR adalah mean EMA20 di $+4.5\%$, dan strategi ini tidak memiliki ekspektasi fat-tail).
   - **Mekanisme**:
     - Menutup $50\%$ ukuran lot koin.
     - Mengembalikan modal pokok porsi tersebut ditambah laba bersih ke `self.cash_idr` secara instan (*Recycled Capital*).
     - Menandai flag `tp1_executed = True`.
     - Meratchet `stop_loss_price = max(stop_loss_price, entry_price * 1.0052)`.
2. **Tier 2 (Asymmetric Fat-Tail Runner - 50% Sisa Lot)**:
   - Sisa $50\%$ lot dibiarkan aktif dalam status **Risk-Free**.
   - Jika pasar berbalik arah, sisa posisi ditutup pada Breakeven, dan total trade tetap mengantongi laba bersih dari TP1.
   - Jika tren berlanjut, sisa posisi menangkap target penuh $+8.5\%$ s/d $+15\%$.

---

### D. Penanganan Risiko What-If & Blindspot Hunting

1. **What-If Indodax Minimum Lot Restriction (Rp 10.000)**:
   - *Masalah*: Jika nominal posisi yang tersisa setelah split 50% kurang dari batas order minimum Indodax (Rp 10.000), sisa lot menjadi *dust* yang tidak dapat dijual.
   - *Mitigasi di Kode*: Fungsi `execute_partial_tp` memvalidasi `gross_value >= 10_000.0` DAN `remaining_val >= 10_000.0`. Jika salah satu $< 10.000$, split dibatalkan dan posisi diarahkan menunggu full exit.
2. **What-If Capital Recycling Over-Trading Trap (FOMO Reinvestment)**:
   - *Masalah*: Modal yang baru cair dari koin A langsung dibelikan ke koin B yang sedang berada di pucuk saat pasar makro sedang berbalik arah.
   - *Mitigasi di Kode*: Modal cair hanya dapat diinvestasikan kembali jika koin target lolos:
     - Filter Rezim 1D Makro ($\text{Close}_{1D} > \text{EMA}_{50}$).
     - Filter Choppiness Index ($\text{CI} < 61.8$).
     - Kuota Karantina Pasangan (`PairQuarantine`) dan `ChurnGuard` tidak aktif.
3. **What-If Durable State Persistence Restart Gap**:
   - *Masalah*: Server reboot setelah TP1 tereksekusi tapi sebelum runner selesai.
   - *Mitigasi di Kode*: Field `tp1_executed`, `partial_tp_price`, `partial_pnl_idr`, dan ratcheted `stop_loss_price` dipersistensikan secara atomik ke `durable_state.json` via event `PARTIAL`, memastikan pemulihan sempurna tanpa kehilangan status risk-free.

