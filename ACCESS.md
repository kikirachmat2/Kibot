# 🏰 BATAM MASTER ACCESS (SOVEREIGN)
- IP: `168.110.201.228`
- User: `ubuntu`
- Role: Command & Control, Trading Master, AI Orchestration
- SSH: `ssh batam` (via your local config)

## 🛡️ SYNC PROTOCOL
1. **CENTRAL DEPLOY**: Semua perubahan dilakukan di MacBook, disinkronkan ke GitHub, lalu di-pull di Batam.
2. **SERVICE RESTART**: `sudo systemctl restart kibot-*` untuk menerapkan perubahan.
3. **LOG MONITORING**: Gunakan `journalctl -f -u kibot-*` untuk melihat log real-time.
