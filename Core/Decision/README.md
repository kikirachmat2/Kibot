# 🧠 Core/Decision — Otak Pertimbangan & Pengambilan Keputusan

Folder ini bertindak sebagai **Dewan Pertimbangan Utama (Decision Engine)** bagi KiBot. Tugas utamanya adalah menganalisis peluang yang dikirim oleh modul Scanner, menimbang kelayakan risiko, menentukan prioritas target koin, dan memutuskan apakah sebuah order boleh diteruskan ke modul eksekusi.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`decision_authority.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/decision_authority.py) | **Otoritas Pembuat Keputusan**: Memeriksa apakah suatu keputusan trading sah secara aturan sebelum diproses lebih lanjut. |
| [`deterministic_decision_gate.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/deterministic_decision_gate.py) | **Pintu Gerbang Aturan Pasti**: Memastikan parameter matematika (rasio profit, batas rugi) terpenuhi secara mutlak tanpa keraguan. |
| [`autonomous_trading_brain.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/autonomous_trading_brain.py) | **Otak Trading Mandiri**: Mengintegrasikan analisis teknikal pasar dengan kondisi modal riil untuk menghasilkan keputusan beli/jual mandiri. |
| [`indodax_target_board.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/indodax_target_board.py) | **Papan Target Indodax**: Memeringkat koin-koin crypto di Indodax dari yang paling menjanjikan hingga yang berisiko tinggi. |
| [`live_opportunity_tier.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/live_opportunity_tier.py) | **Klasifikasi Tingkat Peluang**: Mengelompokkan sinyal menjadi Tier-1 (APPROVED dengan konfirmasi Council) dan Tier-2 (sinyal biasa). |
| [`live_order_dispatcher.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/live_order_dispatcher.py) | **Pemberi Instruksi Order**: Mengirimkan perintah order yang telah disetujui dewan langsung ke antrean modul Executor. |
| [`deadline_profit_enforcer.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/deadline_profit_enforcer.py) | **Penjaga Batas Waktu Profit**: Mengawasi posisi yang terbuka agar tidak menggantung terlalu lama dan memaksa keluar jika batas waktu habis. |
| [`daily_reset_coordinator.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/daily_reset_coordinator.py) | **Koordinator Reset Harian**: Mereset batas rugi harian, kuota transaksi, dan mencatat ringkasan PnL setiap pukul 00:00 WIB. |
| [`indodax_no_idle_loop.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/indodax_no_idle_loop.py) | **Pencegah Node Menganggur**: Menjaga agar sistem selalu aktif mencari peluang baru di pasar secara berkala. |
| [`indodax_live_brain.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/indodax_live_brain.py) | **Logika Khusus Pasar Indodax**: Memperhitungkan karakteristik likuiditas dan order book rupiah (IDR). |
| [`script_adaptation_engine.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/script_adaptation_engine.py) | **Mesin Adaptasi Strategi**: Menyesuaikan parameter trading saat pasar berganti dari fase tenang (*sideways*) ke fase tren kencang. |
| [`target_board_runner.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/target_board_runner.py) | **Pemicu Evaluasi Target**: Runner mandiri yang memicu pembaruan papan target secara terjadwal. |
| [`engine_independence.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/engine_independence.py) | **Isolasi Logika Keputusan**: Memastikan keputusan trading tetap objektif dan terisolasi dari kegagalan subsistem lain. |
