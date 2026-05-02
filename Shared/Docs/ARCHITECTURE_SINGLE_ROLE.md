# KiBot Trinity Architecture — Single-Role Enforcement

Visual representation of the three-node cluster with strict role separation.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        KiBot Trinity Architecture                           │
│                      Single Role per Node (v7 Clean)                        │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌───────────────────────────┐
                         │   Web Dashboard (View)    │
                         │    Android App (View)     │
                         │    Telegram (Alerts)      │
                         └──────────────┬────────────┘
                                        │
                                  READ-ONLY
                                   FEEDS
                                        │
                    ┌───────────────────┴───────────────────┐
                    │                                       │
        ┌───────────▼──────────────────┐    ┌──────────────▼──────────────┐
        │                              │    │                             │
        │   BATAM (Main System)        │    │   EXECUTOR (Executor)           │
        │   Role: BRAIN / HUB          │    │   Role: EXECUTION          │
        │                              │    │                             │
        │  ┌────────────────────────┐  │    │  ┌─────────────────────┐   │
        │  │ Brain Control:         │  │    │  │ Indodax Spot:       │   │
        │  │ • kibot-manager        │  │    │  │ • kibot-executor-indodax      │   │
        │  │ • kibot-analyst        │  │    │  │                     │   │
        │  │ • kibot-orchestrator   │  │    │  │ Polymarket:         │   │
        │  │                        │  │    │  │ • kibot-polymarket  │   │
        │  └────────────────────────┘  │    │  │                     │   │
        │                              │    │  └─────────────────────┘   │
        │  ┌────────────────────────┐  │    │                             │
        │  │ Security:   │  │    │  Tunnels (optional):       │
        │  │ • kibot-security       │  │    │  • kibot-polymarket-tunnel │
        │  │ • kibot-guardian       │  │    │                             │
        │  │ • kibot-auditor        │  │    └─────────────────────────────┘
        │  │                        │  │
        │  └────────────────────────┘  │
        │                              │
        │  ┌────────────────────────┐  │
        │  │ Communications:        │  │
        │  │ • ki-telegram-monitor  │  │
        │  │ • indodax-dashboard-pr │  │  CONTROL PLANE (TCP/UDP)
        │  │ • kibot-notifier       │  ├─────────────────────────────────┐
        │  │                        │  │                                 │
        │  └────────────────────────┘  │                                 │
        │                              │   Execution Posture (9998)      │
        │  ┌────────────────────────┐  │   Control Directives           │
        │  │ AI & Analysis:         │  │   Hardguards                   │
        │  │ • kibot-ollama-gateway │  │   Market Snapshots             │
        │  │ • lazarus-ampere       │  │                                 │
        │  │ (Ollama LLM)           │  │                                 │
        │  │                        │  │                                 │
        │  └────────────────────────┘  │                                 │
        │                              │                                 │
        └──────────────┬────────────────┘                                 │
                       │                                                  │
                       │ MARKET DATA FEED (TCP:9999)                      │
                       │ Signal aggregation                               │
                       │ Heartbeats                                       │
                       │                                                  │
        ┌──────────────▼────────────────────────────────────────────────┐ │
        │                                                               │ │
        │   SCANNER (Scanner Node)                                          │ │
        │   Role: SCANNER ONLY                                          │ │
        │                                                               │ │
        │  ┌──────────────────────────────────────────────────────┐   │ │
        │  │ Global Scanner Mesh:                                │   │ │
        │  │ • ki-global-scanner-mesh (aggregator)              │   │ │
        │  │                                                    │   │ │
        │  │ Exchange Connectors (20 active):                  │   │ │
        │  │ • kibot-scanner@bybit                             │   │ │
        │  │ • kibot-scanner@kubin                             │   │ │
        │  │ • kibot-scanner@crypto                            │   │ │
        │  │ • kibot-scanner@mexc                              │   │ │
        │  │ (... 7 more active instances)                     │   │ │
        │  │                                                    │   │ │
        │  └──────────────────────────────────────────────────────┘   │ │
        │                                                               │ │
        └───────────────────────────────────────────────────────────────┘ │
                                                                           │
                                     EXECUTION ACK + STATE
                                     (TCP:8787 HTTP)
                                     Order status
                                     Health metrics
                                     Risk state
                                                                           │
                                                            ┌──────────────┘
                                                            │
                                                            │
                                       ┌────────────────────▼────────┐
                                       │                             │
                                       │ EXECUTOR → Local Execution       │
                                       │ ────────────────────────    │
                                       │ • Indodax API calls         │
                                       │ • Polymarket event streams  │
                                       │ • Hot-path state mgmt       │
                                       │                             │
                                       └─────────────────────────────┘
```

---

## Key Principles Enforced

### 1. **Single Role per Node**
   - **Batam**: ONLY brain/control work (no execution, no scanning)
   - **EXECUTOR**: ONLY execution (Indodax + Polymarket, no brain, no scanning)
   - **SCANNER**: ONLY scanning (20 sources, no execution, no brain)

### 2. **Communication Hierarchy**
   - **Hub-and-Spoke**: Batam is the hub. EXECUTOR and SCANNER are spokes.
   - **Uplink**: SG nodes send data to Batam (signals, heartbeats, state)
   - **Downlink**: Batam sends control to SG nodes (posture, directives, hardguards)
   - **NO Direct SG-to-SG Traffic** (no EXECUTOR ↔ SCANNER messages)

### 3. **Read-Only Surfaces**
   - Web Dashboard, Android app, Telegram = **observers only**
   - They pull state from Batam but never push control
   - If dashboard crashes, cluster keeps running

### 4. **Service Dependencies**
   - EXECUTOR kibot-executor-indodax depends only on `network-online.target` (not on remote Batam services)
   - SCANNER ki-global-scanner-mesh depends only on `network-online.target`
   - Batam services can depend on kibot-manager (local), but SG nodes should not
   - Each node must boot and be healthy even if the other SG node is down

---

## Port Mapping (Enforced Topology)

| Port | Node | Service | Direction | Purpose |
|------|------|---------|-----------|---------|
| 9998 | Batam | kibot-manager | HTTP | Control plane state |
| 9999 | Batam | kibot-manager | UDP | Fast signals & heartbeats |
| 8787 | EXECUTOR | kibot-executor-indodax | HTTP | Execution state & health |
| 11600 | EXECUTOR | kibot-polymarket | HTTP | Polymarket runtime state |
| 19999 | Batam | netdata | HTTP | Host-level monitoring |
| 11435 | Batam | ollama-gateway | HTTP | Local LLM access |

---

## Service Deployment Matrix

| Service | Batam | EXECUTOR | SCANNER | Note |
|---------|:-----:|:---:|:---:|------|
| kibot-manager | ✅ | ❌ | ❌ | Brain hub only |
| kibot-analyst | ✅ | ❌ | ❌ | Brain work only |
| kibot-auditor | ✅ | ❌ | ❌ | Brain work only |
| kibot-orchestrator | ✅ | ❌ | ❌ | Brain work only |
| kibot-security | ✅ | ❌ | ❌ | Brain work only |
| kibot-guardian | ✅ | ❌ | ❌ | Brain work only |
| kibot-notifier | ✅ | ❌ | ❌ | Brain comms only |
| ki-telegram-monitor | ✅ | ❌ | ❌ | Brain ops only |
| kibot-ollama-gateway | ✅ | ❌ | ❌ | Brain AI only |
| indodax-dashboard-proxy | ✅ | ❌ | ❌ | Brain dashboard only |
| lazarus-ampere | ✅ | ❌ | ❌ | Brain market analysis |
| kibot-executor-indodax | ❌ | ✅ | ❌ | Execution only |
| kibot-polymarket | ❌ | ✅ | ❌ | Execution only |
| ki-global-scanner-mesh | ❌ | ❌ | ✅ | Scanner only |
| kibot-scanner@* | ❌ | ❌ | ✅ | Scanner only |

---

## Diagram Update Instructions for PNG

The new `contohdiagram.png` should:

1. **Three distinct colored boxes** (instead of current overlapping design):
   - **Batam**: Green border, centered top
   - **EXECUTOR**: Blue border, bottom-right (Executor)
   - **SCANNER**: Orange border, bottom-left (Scanner)

2. **Inside each box**, list ONLY the services that should run there:
   - **Batam** lists: Brain Control, Security, Comms, AI layers
   - **EXECUTOR** lists: kibot-executor-indodax, kibot-polymarket ONLY
   - **SCANNER** lists: ki-global-scanner-mesh + kibot-scanner instances ONLY

3. **Arrows show data flow** (no cross-SG arrows):
   - SCANNER → Batam (scanner signals, heartbeats)
   - Batam → EXECUTOR (execution posture, control)
   - EXECUTOR → Batam (execution state, health)
   - Batam → Web/Telegram/Android (read-only feeds)

4. **Color legend**:
   - **Green** = Brain/Control (Batam)
   - **Blue** = Execution (EXECUTOR)
   - **Orange** = Scanning (SCANNER)
   - **Gray** = Read-only surfaces (Web, Telegram, Android)
   - **Red arrows** = Control flow (Batam → EXECUTOR)
   - **Green arrows** = Data flow (SCANNER → Batam, EXECUTOR → Batam)
   - **Gray arrows** = Read-only (Batam → outputs)

5. **Explicit "SINGLE ROLE" label** on the diagram to indicate this is the enforced topology.

---

## Verification Command (Post-Deployment)

Run this on each node to confirm role purity:

```bash
#!/bin/bash
NODE=$HOSTNAME

echo "=== $NODE Role Verification ==="
systemctl list-units --type=service --state=enabled --no-pager | \
  grep -E 'kibot|KiBot|KiBot|ki-|kicryp' | \
  awk '{print $1}' | sort

case "$NODE" in
  batam)
    echo "Expected: 13+ services (all brain/brain-support)"
    ;;
  EXECUTOR-executor)
    echo "Expected: 2 services only (kibot-executor-indodax, kibot-polymarket)"
    ;;
  SCANNER-scanner)
    echo "Expected: 2+ services (ki-global-scanner-mesh + kibot-scanner@*)"
    ;;
esac
```

---

## Migration Notes

If any node currently has out-of-role services enabled:

1. **Before** disabling, verify the service is NOT actively processing orders or scans
2. Disable with: `sudo systemctl disable <service>`
3. Stop with: `sudo systemctl stop <service>`
4. Restart the node
5. Verify with `systemctl status <service>` that it's inactive/disabled

---

## Audit Trail

- **Version**: KiBot Trinity v7 (Clean)
- **Date Created**: 2025-08-XX
- **Authority**: BLUEPRINT.md Section 3 + User Role Enforcement Request
- **Status**: ACTIVE (enforced across all deployments post-2025-08-XX)
