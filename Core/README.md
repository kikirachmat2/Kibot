# 🏛️ KIBOT SOVEREIGN CORE v1.1
> **Status:** PRODUCTION READY | **Architecture:** Decentralized Intelligence + Fee-Aware Execution

Selamat datang di jantung pertahanan **KiBot Sovereign**. Folder ini berisi logika pusat yang mengatur seluruh ekosistem Trinity Mesh secara otonom, cerdas, dan tahan terhadap gangguan (spam-resistant).

---

## 🧠 Komponen Utama

### 1. [Sovereign Council](./sovereign_council.py)
Ini adalah "Otak Kolektif" KiBot. Council tidak berjalan linear, melainkan melalui 5 tahap deliberasi menggunakan model AI bertingkat (Qwen 2.5/3):
- **Observer / The Watchman (0.6b):** Mengumpulkan snapshot sistem dan melakukan *Anomaly Detection*. Dilengkapi dengan **Hybrid Safety Net** (Python code) yang menjamin kegagalan kritis (Redis OFFLINE, Tailscale NeedsAuth) tidak pernah terlewatkan.
- **Diagnostician (1.5b):** Menganalisa akar masalah (root cause) dari setiap anomali.
- **Strategist (DeepSeek-R1 / Reasoning):** Pake "Thinking Mode" buat analisa efek domino dan anomali pasar. Ini "Otak Jenius" Council yang mikir 5 langkah ke depan.
- **Global Eye Integration:** Council terhubung langsung ke web search (Brave/Tavily/Jina) untuk memvalidasi apakah gangguan sistem disebabkan oleh faktor eksternal (Market outage).
- **Risk Arbiter (0.6b):** Menentukan keputusan final dan tingkat kepercayaan (confidence).
- **Executor Bridge:** Menjalankan aksi otomatis (Service Restart, ADB Recovery, Aider Self-Healing) jika `confidence >= 85%` dan `risk <= MEDIUM`.
- **Live Trading Gate:** Order real-money hanya dibuka jika `KIBOT_LIVE_TRADING_ENABLED=true` atau mode trading `live` sudah di-set eksplisit.
- **What-If First:** Council selalu membawa hasil simulasi what-if ke deliberasi supaya keputusan tidak buta skenario.

---

## 🏛️ Filosofi Deliberasi: Chain of Command
Berbeda dengan AI "Chat" biasa, Sovereign Council menggunakan pendekatan **Sekuensial Terstruktur (Military Style)**:
1. **Speed Over Noise:** Dalam trading, keputusan harus diambil dalam hitungan detik. Debat interaktif (tanya-jawab) dihindari untuk mencegah *infinite loops* dan latensi tinggi.
2. **Internal Reasoning:** Strategist menggunakan model **DeepSeek-R1** yang melakukan "Self-Debate" (Chain-of-Thought) di dalam kepalanya sebelum mengeluarkan saran. Hasilnya adalah strategi yang sudah diuji secara internal.
3. **Deterministic Logic:** Setiap tahap memiliki peran yang kaku (Lapor -> Diagnosa -> Saran -> Putusan) untuk memastikan sistem tetap stabil dan bisa diprediksi.

---

### 2. [Circuit Breaker](./circuit_breaker.py)
Tameng pelindung dari loop gila dan spam notifikasi. 
- Jika sebuah komponen gagal lebih dari **3 kali**, sirkuit akan **OPEN** (Putus).
- Retries akan dihentikan selama **5-10 menit** (Cooldown).
- Mencegah spam Telegram saat terjadi gangguan jaringan atau API outage.
- Notifikasi Telegram memakai throttle bersama untuk dedupe dan incident cooldown.

### 3. [KiBot Sovereign Master](../MasterNode.py)
Satu-satunya entry point sistem. Semua modul (Manager, Monitor, API) telah dilebur ke sini.
- **Unified Command:** Tidak ada lagi konflik proses antar-skrip.
- **Mesh Aware:** Sadar penuh terhadap kesehatan node Singapore (Scanner & Executor).

---

## 🛠️ Cara Operasi

### Menjalankan Sistem Master
```bash
# Pastikan Ollama sudah aktif
python3 MasterNode.py
```

---

## 📊 Resource Management (RAM: 24GB)
Sistem diatur agar sangat efisien:
- **Core Engine:** ~200MB RAM.
- **Ollama Models:** Load on demand. Qwen 0.5b tetap hangat di RAM, model besar di-unload setelah 90 detik tidak digunakan.

**"Sovereign power is the ability to make decisions in the face of uncertainty."**
