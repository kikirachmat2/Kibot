# KiBot Trinity Role Manifest

**Authority**: BLUEPRINT.md Section 3 + ROLE_ENFORCEMENT

This document defines the EXACT services that must be enabled on each node to enforce the single-role design. This is the deployment target after the recent audit.

---

## Batam (Main System) — Brain / Hub Role ONLY

### MUST BE ENABLED (Batam-core services):
1. `kibot-manager.service` — UDP veto daemon, control plane
2. `kibot-analyst.service` — Daily PnL, post-mortem, reports
3. `kibot-auditor.service` — Real-time position audit
4. `kibot-notifier.service` — Alert distribution (stdout → logging)
5. `kibot-orchestrator.service` — State machine coordination
6. `kibot-security.service` — Runtime security & hardguards
7. `kibot-guardian.service` — Server watchdog, auto-heal
8. `kibot-ollama-gateway.service` — Local AI access
9. `ki-telegram-monitor.service` — Ops alerts & daily reports
10. `indodax-dashboard-proxy.service` — Web dashboard reverse proxy
11. `lazarus-ampere` — Market mover detection (on Batam for centralized analysis)
12. `ollama.service` — Local LLM (system service, if running)
13. `netdata.service` — Host monitoring (system service, if running)

### MUST BE DISABLED (non-Batam roles):
- `kibot-executor-indodax.service` → EXECUTOR only
- `kibot-polymarket.service` → EXECUTOR only [ALREADY DONE]
- `ki-global-scanner-mesh.service` → SCANNER only
- `kibot-scanner@*.service` → SCANNER only
- `kibot-executor-indodax.service` → DEPRECATED or EXECUTOR only
- Any tunnel services (they shouldn't be on Batam)

---

## EXECUTOR (Executor) — Indodax + Polymarket Execution ONLY

### MUST BE ENABLED (EXECUTOR-core services):
1. `kibot-executor-indodax.service` — Indodax spot trading engine
2. `kibot-polymarket.service` — Polymarket conditional executor

### OPTIONAL SUPPORT (connectivity only):
- `kibot-polymarket-tunnel.service` → For fallback/testing only (optional)

### MUST BE DISABLED (non-executor roles):
- `kibot-manager.service` → Batam only
- `kibot-analyst.service` → Batam only
- `kibot-auditor.service` → Batam only
- `kibot-notifier.service` → Batam only
- `kibot-orchestrator.service` → Batam only
- `kibot-security.service` → Batam only
- `kibot-guardian.service` → Batam only
- `kibot-ollama-gateway.service` → Batam only
- `ki-telegram-monitor.service` → Batam only
- `indodax-dashboard-proxy.service` → Batam only
- `lazarus-ampere.service` → Batam only
- `ki-global-scanner-mesh.service` → SCANNER only
- `kibot-scanner@*.service` → SCANNER only
- `kibot-executor-indodax.service` → Deprecated
- `kicryp-engine.service` → Batam only
- `kicryp-manager.service` → Batam only

---

## SCANNER (Scanner) — Global Market Scanner ONLY

### MUST BE ENABLED (SCANNER-core services):
1. `ki-global-scanner-mesh.service` — Unified scanner aggregator + Batam relay
2. `kibot-scanner@binance.service` — Binance scanner
3. `kibot-scanner@bybit.service` — Bybit scanner
4. `kibot-scanner@kucoin.service` — KuCoin scanner
5. `kibot-scanner@cryptocom.service` — Crypto.com scanner
6. `kibot-scanner@mexc.service` — MEXC scanner
7. `kibot-scanner@gate.service` — Gate scanner
8. `kibot-scanner@htx.service` — HTX scanner
9. `kibot-scanner@okx.service` — OKX scanner
10. `kibot-scanner@bitget.service` — Bitget scanner
11. `kibot-scanner@bitbank.service` — Bitbank scanner
12. `kibot-scanner@bitmart.service` — Bitmart scanner
13. `kibot-scanner@coinbase.service` — Coinbase scanner
14. `kibot-scanner@lbank.service` — LBank scanner
15. `kibot-scanner@upbit.service` — Upbit scanner
16. `kibot-scanner@phemex.service` — Phemex scanner
17. `kibot-scanner@bithumb.service` — Bithumb scanner
18. `kibot-scanner@whale.service` — Whale scanner
19. `kibot-scanner@indodax.service` — Indodax scanner
20. `kibot-scanner@polymarket.service` — Polymarket scanner
21. `kibot-scanner@kraken.service` — Kraken scanner

### MUST BE DISABLED (non-scanner roles):
- `kibot-executor-indodax.service` → EXECUTOR only
- `kibot-polymarket.service` → EXECUTOR only
- `kibot-manager.service` → Batam only
- `kibot-analyst.service` → Batam only
- `kibot-auditor.service` → Batam only
- `kibot-notifier.service` → Batam only
- `kibot-orchestrator.service` → Batam only
- `kibot-security.service` → Batam only
- `kibot-guardian.service` → Batam only
- `kibot-ollama-gateway.service` → Batam only
- `ki-telegram-monitor.service` → Batam only
- `indodax-dashboard-proxy.service` → Batam only
- `lazarus-ampere.service` → Batam only
- `kibot-executor-indodax.service` → Deprecated
- `kicryp-engine.service` → Batam only
- `kicryp-manager.service` → Batam only

---

## Enforcement Steps (One-Time Setup)

Run these on each node to achieve the desired state:

### On Batam:
```bash
# Enable Batam-core services
sudo systemctl enable kibot-manager kibot-analyst kibot-auditor kibot-notifier \
  kibot-orchestrator kibot-security kibot-guardian kibot-ollama-gateway \
  ki-telegram-monitor indodax-dashboard-proxy lazarus-ampere

# Disable everything else
sudo systemctl disable kibot-executor-indodax kibot-polymarket ki-global-scanner-mesh \
  kibot-scanner@* kibot-executor-indodax 2>/dev/null || true
```

### On EXECUTOR:
```bash
# Enable EXECUTOR-core services
sudo systemctl enable kibot-executor-indodax kibot-polymarket

# Disable everything else
sudo systemctl disable kibot-manager kibot-analyst kibot-auditor kibot-notifier \
  kibot-orchestrator kibot-security kibot-guardian kibot-ollama-gateway \
  ki-telegram-monitor indodax-dashboard-proxy lazarus-ampere ki-global-scanner-mesh \
  kibot-scanner@* kibot-executor-indodax kicryp-engine kicryp-manager 2>/dev/null || true
```

### On SCANNER:
```bash
# Enable SCANNER-core services
sudo systemctl enable ki-global-scanner-mesh kibot-scanner@*

# Disable everything else
sudo systemctl disable kibot-executor-indodax kibot-polymarket kibot-manager kibot-analyst \
  kibot-auditor kibot-notifier kibot-orchestrator kibot-security kibot-guardian \
  kibot-ollama-gateway ki-telegram-monitor indodax-dashboard-proxy lazarus-ampere \
  kibot-executor-indodax kicryp-engine kicryp-manager 2>/dev/null || true
```

---

## Verification Steps

After deployment, verify each node has ONLY its designated role:

```bash
# On each node:
systemctl list-units --type=service --state=enabled --no-pager | grep -E 'kibot|KiBot|KiBot|ki-|kicryp'
```

Expected output:
- **Batam**: 13 services (kibot-manager, kibot-analyst, … lazarus-ampere)
- **EXECUTOR**: 2 services (kibot-executor-indodax, kibot-polymarket)
- **SCANNER**: 20+ sources + 1 aggregator (ki-global-scanner-mesh, kibot-scanner@*)

Any other services appearing = VIOLATION, must disable.

---

## Diagram Update

The diagram (`contohdiagram.png`) must be redrawn to show:

1. **Batam box** (green border) containing ONLY these functional groups:
   - Brain Control (kibot-manager, kibot-analyst, kibot-orchestrator)
   - Security (kibot-security, kibot-guardian)
   - Comms (ki-telegram-monitor, indodax-dashboard-proxy)
   - AI (kibot-ollama-gateway)
   - Indicators_Math (lazarus-ampere)

2. **EXECUTOR box** (blue border) containing ONLY:
   - Indodax Engine (kibot-executor-indodax)
   - Polymarket Executor (kibot-polymarket)

3. **SCANNER box** (orange border) containing ONLY:
   - Global Scanner Mesh (ki-global-scanner-mesh + kibot-scanner@*; 20 source scanners)

4. Data flows:
   - SCANNER → Batam: market signals, heartbeats
   - Batam → EXECUTOR: execution posture, control directives
   - EXECUTOR → Batam: execution state, health
   - Batam → Web/Telegram: read-only outputs

---

## Notes

- This manifest replaces all previous role definitions. It is the authority.
- Services are listed by their systemd unit name (e.g., `kibot-manager.service`).
- The `@` character denotes template units; `kibot-scanner@*` means all instances.
- Once this is applied, restart all nodes and verify no cross-role traffic occurs.
- Diagram must match this manifest exactly.
