# 🔍 scripts/diagnostics — Alat Investigasi Forensik Runtime

Folder ini berisi skrip investigasi mendalam yang digunakan untuk mendeteksi akar masalah teknis ketika terjadi anomali data di server.

---

## 📁 Daftar Skrip & Fungsinya

| Skrip | Penjelasan Fungsi (Bahasa Awam) |
| :--- | :--- |
| [`trace_equity_source.py`](./trace_equity_source.py) | **Pelacak Asal-Usul Saldo Ekuitas**: Menelusuri dari mana data saldo akun berasal (apakah dari cache lokal, file state, atau mutasi bursa asli) untuk memastikan kebenaran pembukuan modal. |
