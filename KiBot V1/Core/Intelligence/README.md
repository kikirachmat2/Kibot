# 🧠 Core/Intelligence — Mata, Telinga & Analisis Intelijen Pasar

Folder ini bertindak sebagai **Pusat Intelijen & Analisis Pasar (Intelligence Layer)** KiBot. Tugas utamanya adalah mengumpulkan data pasar global, menjalankan penalaran AI, menyusun konteks portofolio, memantau riwayat trade, serta menyajikan visualisasi web dashboard bagi operator.

---

## 📁 Daftar File Utama & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`kibot_ai_coordinator.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_coordinator.py) | **Koordinator AI**: Mengelola antrean permintaan ke model AI (Gemini, Groq, Ollama) untuk analisis sentimen berita dan kritik strategi. |
| [`kibot_ai_scout.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_scout.py) | **Pramuka Intelijen Pasar**: Melakukan patroli otomatis tiap 5 menit untuk mengecek berita crypto global, kesiapan server, dan anomali pasar. |
| [`kibot_dashboard.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_dashboard.py) | **Server Web Dashboard**: Menyajikan antarmuka visual web pemantau saldo riil, posisi aktif, dan log trading bagi operator. |
| [`autonomous_director.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/autonomous_director.py) | **Direktur Otonom**: Memfilter sinyal kandidat yang disetujui Council dan mengecek safety gate CapitalGovernor sebelum order dikirim. |
| [`council_data_aggregator.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/council_data_aggregator.py) | **Pengumpul Data Dewan**: Merangkum kondisi saldo, daftar koin panas, dan histori trade menjadi satu laporan ringkas untuk sidang Council. |
| [`pre_trade_simulator.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/pre_trade_simulator.py) | **Simulator Pra-Trading**: Melakukan simulasi instan sebelum order dikirim — mengecek apakah keuntungan kotor cukup untuk menutup fee bursa. |
| [`expected_value.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/expected_value.py) | **Kalkulator Nilai Harapan (EV)**: Memastikan hanya peluang dengan probabilitas untung positif (*Positive Expected Value*) yang boleh dieksekusi. |
| [`decision_journal.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/decision_journal.py) | **Buku Harian Keputusan**: Mencatat secara transparan setiap alasan mengapa sebuah koin disetujui atau ditolak trading. |
| [`trade_history.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/trade_history.py) | **Catatan Riwayat Transaksi**: Mencatat hasil untung/rugi bersih (*Net PnL*) setelah dipotong fee bursa untuk setiap trade yang selesai. |
| [`paper_trade_tracker.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/paper_trade_tracker.py) | **Pelacak Trading Virtual (Simulasi)**: Menguji kinerja strategi baru dengan uang virtual sebelum diizinkan memakai uang asli. |
| [`market_heatmap.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/market_heatmap.py) | **Peta Suhu Pasar**: Mengukur apakah pasar Indodax sedang bergairah (*bullish*), lesu (*bearish*), atau stagnan (*sideways*). |
| [`leadlag_alpha.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/leadlag_alpha.py) | **Detektor Lead-Lag**: Membaca pergerakan harga di Binance mendahului Indodax untuk menangkap momentum kenaikan lebih awal. |
| [`pair_quarantine.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/pair_quarantine.py) | **Karantina Koin Bermasalah**: Mengunci koin yang baru saja mengalami stop-loss beruntun agar tidak dibeli ulang sementara waktu. |
| [`exit_plan.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/exit_plan.py) | **Rencana Penjualan Posisi**: Menghitung target Take Profit realistis dan Stop Loss protektif sebelum posisi dibuka. |
| [`ai_performance_analyst.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/ai_performance_analyst.py) | **Analis Kinerja AI**: Menganalisis win rate varian strategi trading dan menyusun laporan performa mingguan. |
| [`daily_report.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/daily_report.py) | **Penyusun Laporan Harian**: Merangkum hasil trading dan saldo portofolio untuk dikirim ke Telegram tiap pukul 00:00 WIB. |

---

## 🤖 Aturan Integritas AI (AI Safety Rules)
- AI bertindak sebagai **penasihat dan penganalisis** (mendiagnosis pasar, merangkum berita, mengkritik strategi).
- AI **DILARANG mengeksekusi order langsung**, dilarang membesarkan ukuran posisi, dan dilarang melonggarkan batas risiko modal.
- Keputusan order tetap deterministic (mengikuti aturan matematika pasti) dan tercatat di Decision Journal.
