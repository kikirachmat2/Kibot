# 🧠 SERVER_BATAM (The Brain) - Trinity v9.1

## Overview
Batam is the **Single Source of Truth** and the central command center of the KiBot ecosystem. It aggregates sensory data from globally distributed Scanners and issues execution orders to reactive Executor nodes.

## Core Components
- **Core_Logic/**: Contains `kibot_manager.py` (Main entry) and `ki_brain.py` (Decision engine).
- **AI_Orchestration/**: Integrates local LLMs (DeepSeek-Coder-V2) via Ollama for autonomous code healing and sentiment validation.
- **Indicators_Math/**: Handles Z-Score, technical analysis, and Polymarket probability math.
- **Security/**: Enforces the "Sovereign Shield" and monitors for unauthorized system changes.

## Deployment & Management
Batam operates via systemd:
- `kibot-orchestrator.service`: Starts Manager and Brain.
- `kibot-healer.service`: Autonomous maintenance via DeepSeek AI.
- `indodax-dashboard-proxy.service`: Real-time visual monitoring (Port 8080).

## Connection Points (Trinity Mesh)
- **Primary Link**: Tailscale Private Network (100.x.x.x) for inter-node control.
- **Inbound**: UDP Sensory Stream (Port 9999) from Scanners.
- **Outbound**: Command Polling via Supabase & Direct Reactive SSH for Executors.
- **Reporting**: Telegram Monitor for real-time PnL and alerts.

## Current System Status (v9.1 Stable)
- **Uptime**: Verified >9 days.
- **Node Health**: 3/3 Nodes Online.
- **Networking**: Mesh standard enforced via `authorized_keys` & Tailscale.
