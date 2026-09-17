# KiBot V2 — Quantitative Backtest Engine

Modul backtesting bar-by-bar bebas look-ahead bias untuk menguji kelayakan statistik strategi rotasi modal mikro sebelum diimplementasikan ke Shadow Ledger.

## Komponen yang Akan Dibangun:
1. `data_loader.py`: Download & local caching data historis OHLCV hourly dari Indodax TradingView API dan Binance REST API / Data Vision archive.
2. `engine.py`: Bar-by-bar historical replay engine. Menghitung indikator teknikal saat bar close dan mengeksekusi order pada bar berikutnya.
3. `friction.py`: Pemodelan komprehensif friksi Maker ($0.56\% - 0.70\%$) dan Taker ($0.78\% - 0.95\%$) dengan probabilistik fill rate ($85\%$) dan adverse selection penalty ($30\%$ untuk MR, $40\%$ untuk LL).
4. `metrics.py`: Analisis performa kuantitatif: Expectancy, Profit Factor, Win Rate, Max Drawdown, Calmar Ratio, Sharpe Ratio, dan Fee-to-Gross Ratio.
5. `report.py`: Generator laporan perbandingan 4 opsi kandidat strategi (D1, D2, D3, C') pada 3 skenario pasar historis (2023 Full, Q3 2024 Sideways, Jan 2025-Sekarang).
