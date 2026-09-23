# 🤖 KiBot — Autonomous Safety-First Crypto DCA Bot

**KiBot** adalah sistem bot akumulasi kripto (DCA 70/30 BTC/ETH) otomatis, transparan, dan berorientasi keamanan (*safety-first*) yang beroperasi di bursa Indodax. Sistem dirancang dengan arsitektur tangguh, pemulihan otomatis, logging terstruktur, dan pemantauan jarak jauh via Telegram.

---

## 📁 Repository Structure

```text
KiBot/
├── archive/                  # Arsip terkompresi kode historis KiBot V1 & V2
├── cluster/                  # Watchdog failover & monitoring heartbeat
├── config/                   # Konfigurasi sistem, fee schedules, & environment loader
├── core/                     # Portofolio tracker, event detector (topup), & alokasi aset
├── data/                     # Dataset historis & data candle
├── docs/                     # Arsitektur sistem, Disaster Recovery, & panduan keamanan
├── infra/                    # Systemd service units & konfigurasi logrotate
├── ingestion/                # REST client Indodax untuk data pasar & akun
├── intelligence/             # Modul diagnosa mandiri (Self-Diagnostics)
├── notifications/            # Telegram bot reporter & command handler (/status, /health, dll)
├── scripts/                  # Script automasi backup state SQLite WAL & security checks
├── storage/                  # SQLite persistent storage & model data
├── tests/                    # Unit & integration test suite (pytest)
├── main.py                   # Titik masuk utama (Orchestrator V3)
└── requirements.txt          # Dependensi Python
```

---

## 🚀 Quickstart & Testing

1. **Setup Environment**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

2. **Jalankan Test Suite**:
   ```bash
   python3 -m pytest tests/
   ```

3. **Menjalankan Bot**:
   ```bash
   python3 main.py
   ```

---

## 🛡️ Keamanan & Monitoring

- **Node Produksi**: SG1 (`152.69.218.198`) menjalankan `kibot-v3-core.service`.
- **Node Monitoring / Watchdog**: Server 2 (`213.35.118.26`) menjalankan `kibot-v3-watchdog.service`.
- **Status Endpoint**: Endpoint HTTP `/health` lokal berjalan pada port `8789`.
- **Disaster Recovery**: Panduan pemulihan database SQLite terdokumentasi lengkap di [`docs/DISASTER_RECOVERY.md`](./docs/DISASTER_RECOVERY.md).
