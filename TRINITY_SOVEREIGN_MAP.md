# 🗺️ TRINITY SOVEREIGN RECOVERY MAP (v9.1.1)
> **Last Updated**: 2026-05-05 03:30 WIB
> **Status**: OPERATIONAL / SOVEREIGN MODE

## 📡 Node Infrastructure (Oracle Cloud)
Semua node terhubung via **Tailscale Mesh**. Jika IP Tailscale mati, gunakan IP Publik terbaru dari dashboard.

| Node Name | Public IP (Last) | Tailscale IP | Role | Access Key |
|-----------|------------------|--------------|------|------------|
| **BATAM (Brain)** | `168.110.201.228` | `100.82.164.116` | Logic, Arbitrase, Governor | `ssh-key-batam-active.pem` |
| **SCANNER (Eyes)** | `152.69.218.198` | `100.105.139.21` | UDP Sensory Mesh (Port 9997) | `ssh-key-2026-03-27.key` |
| **EXECUTOR (Hands)**| `213.35.118.26` | `100.126.138.125`| Fast Execution (SSH commands) | `ssh-key-2026-03-22.key` |

## 🔑 Security & Authentication
- **Master Key**: `ssh-key-batam-active.pub` sudah terdaftar di `authorized_keys` SEMUA node.
- **Protocol**: Batam mengontrol Scanner & Executor secara otonom tanpa butuh input user.

## ⚙️ Critical Logic (Self-Healing)
1. **Supabase Kill-Switch**: `SUPABASE_BACKUP_ENABLED = False` (Mencegah quota breach).
2. **Resource Governor**: Monitoring `/home/ubuntu/KiBot/SERVER_BATAM/Infrastructure/logs`. Otomatis hapus log jika disk < 5GB.
3. **Internal Bugfix**: File sampah `/home/ubuntu/KiBot/SERVER_BATAM/ki_brain.py` sudah dihapus untuk mencegah `AttributeError`.

## 🆘 Emergency Recovery SOP
Jika AI (atau kamu) lupa cara masuk:
1. **Cek IP**: Jika ping gagal, cek Dashboard Oracle. IP Publik sering berubah!
2. **Re-Sync IP**: Update file `/home/ubuntu/KiBot/.env.server` di Batam dengan IP Scanner baru.
3. **Restart**: `sudo systemctl restart kibot-orchestrator`.

---
"Sovereign Trinity is designed to survive. If one node fails, the Brain adapts."
