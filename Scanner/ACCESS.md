# 📡 SG SCANNER ACCESS
- IP: `152.69.218.198`
- User: `ubuntu`
- Role: Market Scanning (Indodax/Polymarket)
- SSH: `ssh scanner` (via batam master)
- Main Service: `kibot-scanner-mesh.service`

## 🛡️ SOVEREIGN SYNC RULES
1. **MANUAL PULL ONLY**: Update kode hanya boleh lewat `git pull` manual di terminal server.
2. **STRICT LOGIC SYNC**: Pastikan logic di folder `Scanner/` lokal sudah dipush ke main sebelum dideploy.
3. **ISOLATION**: Jangan jalankan script Master atau Executor di server ini. Hanya folder `Scanner/` yang boleh aktif.
4. **NO SCRIPTS**: Dilarang menggunakan script automasi untuk deployment. Semuanya harus transparan via SSH.
