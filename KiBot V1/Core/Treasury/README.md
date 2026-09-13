# 💰 Core/Treasury — Bendahara Modal & Penjaga Batas Risiko (Treasury Layer)

Folder ini bertindak sebagai **Brankas & Bendahara Keuangan (Treasury & Risk Governor Layer)** KiBot. Tugas utamanya adalah melindungi modal operator: menghitung total ekuitas portofolio, mencatat saldo kas dan koin, serta menegakkan batasan kerugian harian (*Hard Daily Loss Limit*) yang mutlak dan tidak boleh dilanggar.

> [!CAUTION]
> **Safety Gate Kritis**: Modul di folder ini (terutama `capital_governor.py`) adalah **pelindung terakhir uang Anda**. Jika kerugian mencapai ambang batas harian (misalnya 1.5%), sistem otomatis membekukan order baru (*Circuit Breaker*). Mekanisme ini tidak boleh dilemahkan atau di-bypass oleh proses otomatis apa pun.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`capital_governor.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/capital_governor.py) | **Gubernur Modal (Capital Governor)**: Polisi penjaga modal trading. Memantau penurunan modal (*drawdown*), menghitung batas rugi harian, dan mengunci trading (*lockout*) jika ambang batas terlampaui. |
| [`live_truth_manager.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/live_truth_manager.py) | **Manajer Kebenaran Saldo (Live Truth)**: Sumber kebenaran tunggal saldo akun Indodax (Kas IDR + Nilai Pasar Koin yang sedang di-hold) yang dicatat ke `state/live_truth.json`. |
| [`pnl_reconciliation.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/pnl_reconciliation.py) | **Rekonsiliasi Untung-Rugi**: Mencocokkan angka keuntungan/kerugian di catatan internal bot dengan data transaksi asli dari mutasi bursa. |
| [`accounting_truth.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/accounting_truth.py) | **Standar Akuntansi Portofolio**: Memastikan rumus perhitungan ekuitas portofolio konsisten dan tidak memasukkan angka fiktif. |
| [`venue_ledger.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/venue_ledger.py) | **Buku Besar Bursa**: Mencatat arus kas masuk dan keluar khusus untuk venue bursa Indodax. |
| [`capital_commander.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/capital_commander.py) | **Komandan Alokasi Modal**: Menentukan batas maksimal modal yang boleh digunakan untuk satu putaran siklus trading. |
| [`deposit_event_manager.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/deposit_event_manager.py) | **Pencatat Deposit Manual**: Mendeteksi jika operator melakukan deposit rupiah baru ke akun Indodax, sehingga anchor perhitungan PnL harian otomatis disesuaikan secara adil. |
| [`allocation_policy.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/allocation_policy.py) | **Kebijakan Alokasi**: Aturan pembagian porsi modal antara kas mengendap (*cash reserve*) dan modal aktif trading. |
