# 📈 Core/Trading — Strategi & Manajemen Ukuran Posisi (Trading Layer)

Folder ini bertindak sebagai **Pusat Kalkulasi Trading (Trading & Position Sizing Layer)** KiBot. Tugas utamanya adalah menghitung alokasi modal optimal untuk setiap order, menyesuaikan ukuran posisi dengan volatilitas pasar, dan mencegah alokasi modal yang berlebihan.

---

## 📁 Daftar File & Fungsinya

| File | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`autonomous_sizing.py`](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Trading/autonomous_sizing.py) | **Kalkulator Ukuran Posisi Otonom**: Menggunakan kriteria Kelly fraksional dan batas risiko portofolio untuk menentukan persis berapa Rupiah yang boleh dialokasikan ke suatu koin, sehingga risiko kerugian tetap terukur dan terkendali. |
