# 📜 KIBOT V3 — KEPUTUSAN FINAL ARSITEKTUR STRATEGI

Dokumen ini adalah **catatan resmi dan permanen** mengenai evaluasi 8 hipotesis strategi trading kuantitatif/aktif yang telah diuji secara empiris menggunakan data historis riil Indodax PRO (2023–2026) dengan memperhitungkan friksi riil (fee asimetris Indodax dan pajak PPh 0,21%).

Dokumen ini menjadi rujukan utama bagi Supervisor dan developer di masa depan agar tidak mengulang eksperimen yang secara matematis dan empiris telah terbukti inferior terhadap akumulasi murni.

---

## 1. RANGKUMAN 8 STRATEGI YANG TELAH DIUJI & PENYEBAB KEGAGALANNYA

| No | Percobaan / Strategi | Hipotesis Awal | Hasil Empiris | Mengapa Gagal? |
|:---:|:---|:---|:---|:---|
| **1** | **High-Frequency Scalping** | Mengambil spread mikro 0,1% - 0,3% di order book Indodax | **Gagal Total** (Rugi modal) | Fee roundtrip Indodax PRO (0,43% maker / 0,63% taker) jauh melampaui rata-rata spread. Eksekusi tergerus fee dan pajak. |
| **2** | **Swing Mean-Reversion / Trend (EMA/RSI)** | Beli saat oversold/uptrend, jual saat overbought/downtrend | **Kalah vs DCA** | Sinyal palsu (*whipsaw*) di konsolidasi kripto memicu rentetan *cut-loss*, membakar modal lewat fee jual dan pajak PPh. |
| **3** | **Lead-Lag Cross-Exchange Arbitrage** | Memanfaatkan pergerakan Binance untuk mendahului harga Indodax | **Tidak Layak** | Latensi jaringan SG/ID, likuiditas tipis Indodax, dan selisih kurs USD/IDR mengeliminasi margin arbitrase sebelum eksekusi selesai. |
| **4** | **Market Making (Order Book Grid)** | Memasang bid/ask pasif untuk menangkap spread dan volume rebate | **Terlalu Berisiko** | Risiko *adverse selection* (saat pasar crash, bot memborong pisau jatuh; saat pasar terbang, inventori habis terlalu dini). |
| **5** | **Cycle-Aware Dynamic Multiplier** | Mengatur besar topup (0.5x - 2.0x) berdasarkan posisi siklus halving/RSI macro | **Kalah vs DCA Polos** | Mengurangi topup di fase akumulasi awal (karena sinyal ragu) membuat rata-rata harga beli lebih tinggi dibanding DCA konstan. |
| **6** | **Emergency Auto-Sell / Circuit Breaker** | Menjual seluruh aset ke stablecoin saat terjadi flash crash mendadak | **Merusak Portofolio** | Hampir selalu menjual di dasar jurang (*panic bottom*) dan gagal membeli kembali sebelum harga pulih (*missed V-shape recovery*). |
| **7** | **Faber (2007) Trend-Filter SMA-200** | Beli hanya jika Price > SMA-200; jual ke IDR jika Price <= SMA-200 | **Kalah Telak** (+11,87% vs DCA +58,94%) | Cek bulanan terlalu lambat untuk kripto (menjual setelah crash, beli kembali setelah reli tinggi). Menghilangkan 79% keuntungan DCA. |
| **8** | **Academic Time-Series Momentum (Liu et al. 2022)** | Likuidasi jika return N-bulan <= 0, redeploy jika return N-bulan > 0 | **Sangat Rapuh (Brittle Overfitting)** | Hasil lompat drastis (+87% di 1M vs -26% di 3M/6M). Membakar fee hingga Rp 3 juta (11% modal) akibat 40 kali likuidasi dan whipsaw. |

---

## 2. KEPUTUSAN FINAL: PURE DCA 70% BTC / 30% ETH (BUY-ONLY)

Sistem KiBot V3 secara resmi dan permanen mengadopsi arsitektur:
### **PURE BUY-ONLY ACCUMULATION (70% BTC / 30% ETH)**

### Rasional Utama:
1. **Proteksi Modal Alami (Worst Capital Loss < 1%)**:
   - Backtest longitudinal 3,7 tahun membuktikan bahwa strategi DCA bertahap (*irregular timing & amount*) menjaga risiko modal pokok pada level ekstrem aman (penurunan modal pokok terburuk hanya **-0,61%**).
   - Akumulasi berkala secara matematis menurunkan harga rata-rata (*dollar-cost averaging*) tanpa perlu menebak arah pasar.
2. **Eliminasi Pajak & Fee Asimetris**:
   - Di Indonesia, setiap transaksi jual aset kripto dikenakan pajak PPh final (0,21%) + biaya bursa.
   - Dengan **tidak pernah menjual dari bot**, portofolio KiBot V3 menghemat jutaan rupiah fee/pajak yang pada strategi aktif terbukti menggerogoti hasil investasi.
3. **Ketahanan Operasional Jangka Panjang**:
   - Menghapus seluruh logika penjualan (*auto-sell / emergency / rebalance*) menyederhanakan kode dari ~4.000 baris menjadi sistem deterministik yang tahan banting.
   - Tidak ada risiko bug eksekusi order jual, slippage likuiditas, atau kegagalan API saat kepanikan pasar.
4. **Kedaulatan Supervisor**:
   - Bot bertugas sebagai *disciplined accumulator*. Penjualan atau penarikan dana sepenuhnya adalah keputusan personal Supervisor di aplikasi resmi Indodax di luar sistem bot.

---

## 3. STATUS KODE PRODUKSI
- Seluruh modul aktif (regime detector, self updater, multiplier, signal aggregator, emergency seller) telah **dihapus permanen** dari codebase.
- File riset disimpan secara pasif di `scripts/research/` sebagai artefak dokumentasi dan **tidak memiliki dependensi** ke `main.py` atau sistem runtime SG1.
