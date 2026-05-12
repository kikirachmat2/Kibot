# 🛠️ KiBot Support

Configuration, Utilities, Web Dashboard, and Node Agents.

## Ringkas
- `ki_config.py` menyimpan path dan port bersama.
- `ki_utils.py` berisi helper umum seperti signing/verification.
- `ki_vault.py` memuat secret dari vault ke environment saat boot.

## Responsibility
- **Configuration**: `ki_config.py` and `dynamic_config.py`.
- **Utilities**: Shared helper functions and vault management.
- **Node Control**: `kibot_node_agent.py` for remote management.
- **UI/Web**: Dashboard templates and cluster monitoring.

## Subdirectories
- `Web/`: Dashboard and HTML/JS components.
- `Audit_Testing/`: Benchmarking and system audit tools.
- `Android APK/`: Control scripts for the Android interface.
