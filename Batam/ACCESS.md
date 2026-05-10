# 🏰 BATAM MASTER ACCESS
- IP: `168.110.201.228`
- User: `ubuntu`
- Role: Command & Control, AI Council, Master Registry
- SSH: `ssh batam` (via config)
- Main Service: `kibot-command-center.service`

## 🛡️ SOVEREIGN SYNC RULES
1. **NO AUTO-DEPLOY SCRIPTS**: Semua deployment harus dilakukan manual via SSH.
2. **LOCAL-MASTER ALIGNMENT**: Perubahan logika di MacBook/Lokal WAJIB disinkronkan ke GitHub sebelum di-pull ke server.
3. **MANUAL RESTART**: Setelah update file, restart service manual: `sudo systemctl restart <service>`.
4. **FOLDER LOCK**: Struktur folder di server harus identik dengan folder `Batam/` di repository ini.
