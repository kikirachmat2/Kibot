# Batam Server Production Verification Checklist

- [x] Phase 1: Review systemd configuration files for scanner, council, and executor services.
- [x] Phase 2: Audit resource quota sandboxing (CPUQuota=60%, MemoryLimit=3.5G) on systemd services.
- [x] Phase 3: Inspect active socket listeners on remote Batam server (zero-trust network validation).
- [x] Phase 4: Sync codebase via git and clean state directory files (`leadlag_alpha.json`, `scanner_runtime.json`, `market_rotation.json`).
- [x] Phase 5: Execute systemd service restart sequence via canonical `bin/kibotctl` wrapper.
- [x] Phase 6: Run integration tests (`pytest`) and health check suite on Batam node.
- [x] Phase 7: Validate live/mock safety flags, log outputs, and emergency kill switch existence.
