# 🔬 Core/Research — Laboratorium Backtesting & Riset Kuantitatif

Folder ini bertindak sebagai **Laboratorium Penelitian (Research & Simulation Lab)** KiBot. Tugas utamanya adalah menguji logika strategi trading terhadap data historis lilin harga (*candlestick*) sebelum suatu strategi diizinkan berjalan di pasar riil.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`backtest_engine.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Research/backtest_engine.py) | **Mesin Uji Historis (Backtester)**: Menyimulasikan eksekusi order beli/jual pada rekaman harga masa lalu dengan memperhitungkan biaya fee bursa, slippage, dan batas modal. |
| [`walk_forward.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Research/walk_forward.py) | **Penguji Walk-Forward**: Metode pengujian validasi bertahap (*out-of-sample*) untuk memastikan strategi tidak mengalami *curve-fitting* (hanya pintar menebak masa lalu tapi gagal di masa depan). |
