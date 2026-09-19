# 🤖 KiBot V2 — Sovereign Autonomous Crypto Trading Cluster

**KiBot V2** adalah sistem agen trading kripto multi-strategi independen dan nir-blokir yang dibangun khusus untuk pasar Indodax (dengan referensi lead-lag Binance). Sistem ini menggabungkan deliberasi multi-agen (Sovereign Council), dynamic regime detection berbasis HMM dan getregime.com consensus, per-pair Indodax Deadman switch otomatis, serta pengujian paralel 5 varian paper trading (P1 Conservative, P2 Balanced, P3 Aggressive, P4 Volume Anomaly, P5 BTC/Alt Rotation) sebelum alokasi modal nyata.

---

## 📁 Repository Structure

```text
KiBot/
├── KiBot V2/                 # Core Python trading engine, strategies, tests, & state
│   ├── council/              # Regime detectors, council workers, & external consensus
│   ├── executor/             # VirtualLedger, Indodax TAPI routing, & Deadman switch
│   ├── notifications/        # Telegram notifier & 00:00 WIB daily reporter
│   ├── risk/                 # RiskGate circuit breakers & CapitalGovernor
│   └── storage/              # DurableStateStore, VenueLedger, & redacting logger
├── docs/                     # Cluster architecture, incident reports, & supervisor checklists
├── infra/                    # Systemd units, Tailscale mesh configs, & OCI ARM poller
└── scripts/                  # Security scanners & verification tools
```

---

## 🚀 Quickstart & Documentation

1. **Panduan Instalasi & Setup Lokal**:
   - Ikuti panduan lengkap di [`docs/SUPERVISOR_ACTION_CHECKLIST.md`](./docs/SUPERVISOR_ACTION_CHECKLIST.md) dan [`KiBot V2/README.md`](./KiBot%20V2/README.md).
   - Setup venv Python 3.10+: `python3 -m venv venv && source venv/bin/activate && pip install -r "KiBot V2/requirements.txt"`.
   - Jalankan test suite: `cd "KiBot V2" && pytest -q`.

2. **Deployment & Topologi Cluster**:
   - Dokumentasi lengkap arsitektur multi-node (SG1 Trading Node, Server 2 Executor/Witness, Batam Research Node):  
     Lihat [`docs/CLUSTER_ARCHITECTURE.md`](./docs/CLUSTER_ARCHITECTURE.md).

---

## 📊 Status Saat Ini (Current Status)

- **Mode Operasi**: Paper Trading Multi-Variant (P1–P5 + Trend Following) aktif di node SG1 (`152.69.218.198`).
- **Cluster Node**:
  - **SG1 (Singapore)**: `kibot-v2-paper.service` (ACTIVE), `kibot-auto-discovery.service` (ACTIVE).
  - **Server 2 (Frankfurt)**: `kibot-cluster.service` (ACTIVE), `kibot-v2-witness.service` (ACTIVE), `kibot-batam-hunter.service` (STANDBY).
  - **Batam Node (ap-batam-1)**: PENDING (Standby menunggu `TS_AUTHKEY` diisi oleh Supervisor untuk launch instance ARM 2 OCPU / 12 GB RAM).
- **Security & Safety**: Git pre-commit secret scanner aktif, log redacting filter aktif, Indodax Deadman switch aktif.

