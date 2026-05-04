# 🛡️ KiBot Infrastructure (Trinity Mesh v9.1)

Low-level infrastructure and autonomous orchestration for the KiBot cluster.

## Systemd Mesh Architecture
All services are now standardized under the `kibot-` prefix for unified management:
- `kibot-orchestrator`: Main process hub.
- `kibot-healer`: Autonomous maintenance engine.
- `indodax-dashboard-proxy`: Metrics and control panel.

## Automation & Self-Healing
- **Automation/trinity_healer.py**: Jantung dari **Apex v1.2**. Memantau journalctl secara real-time, mendeteksi traceback, dan mengirimkan ke AI Fleet untuk patch otomatis.
- **Automation/kibot-healer.service**: Service penunggu yang memastikan bot tidak pernah mati lebih dari 30 detik.

## Security & Access
- **SSH/**: Centralized key management for the entire Mesh Network.
- **Infra/systemd/**: Standardized unit files with `PYTHONPATH` enforcement and resource sandboxing (`MemoryMax`, `CPUQuota`).

## Maintenance Flow
1. **Sync**: Update local files.
2. **Push**: Deploy via `Shared/Ops/deploy_trinity_ultimate.sh`.
3. **Audit**: Monitor `journalctl -fu kibot-healer` for any autonomous repair activities.
