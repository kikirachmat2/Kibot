# ⚡ EXECUTOR ACCESS
- IP: `TBD` (Via SSH Alias)
- User: `ubuntu`
- Role: Order Execution (Indodax & Polymarket)
- SSH: `ssh executor`
- Main Services: `kibot-indodax.service`, `kibot-polymarket.service`

## 🛡️ SOVEREIGN SYNC RULES
1. **MANUAL EXECUTION**: Semua deployment wajib dilakukan manual via SSH.
2. **ZERO TOLERANCE**: Logic di folder `Executor/` lokal harus 100% identik sebelum dideploy ke server.
3. **SERVICE HYGIENE**: Pastikan folder `Indodax/` dan `Polymarket/` tetap terpisah sesuai struktur repo.
4. **NO DEPLOY SCRIPTS**: Dilarang menggunakan script automasi. Gunakan manual command line untuk transparansi audit.
