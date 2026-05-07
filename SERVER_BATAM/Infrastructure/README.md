# 🛡️ KiBot Infrastructure (Trinity Mesh v9.1)

Low-level infrastructure and autonomous orchestration for the KiBot cluster.

## Systemd Mesh Architecture
All services are now standardized under the `kibot-` prefix for unified management:
- `kibot-trinity`: Primary Batam brain runtime.
- `kibot-manager`: Legacy compatibility shim.
- `kibot-orchestrator`: Main process hub.
- `kibot-healer`: Autonomous maintenance engine powered by local Ollama.
- `kibot-command-center`: Metrics and control panel.
- `executor-healer`: Memory watchdog for the executor node.

## Automation & Self-Healing
- **Automation/trinity_healer.py**: Jantung dari **Apex v1.2**. Memantau journalctl secara real-time, mendeteksi traceback, dan mengirimkan ke AI Fleet untuk patch otomatis.
- **Automation/kibot-healer.service**: Service penunggu yang memastikan bot tidak pernah mati lebih dari 30 detik.

## Security & Access
- **SSH/**: Centralized key management for the entire Mesh Network.
- **Infra/systemd/**: Standardized unit files with `PYTHONPATH` enforcement and resource sandboxing (`MemoryMax`, `CPUQuota`).

## Maintenance Flow
1. **Sync**: Update local files.
2. **Push**: Deploy via `SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh` or the Batam deploy wrappers.
3. **Audit**: Monitor `journalctl -fu kibot-healer` and the command center for any autonomous repair activities.
4. **Executor Recovery**: Use `SERVER_BATAM/Infrastructure/Infra/setup_executor_autonomous.sh` to install the executor memory watchdog baseline.
