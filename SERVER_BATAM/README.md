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

## Current System Status (v9.1.1 Sovereign)
- **Mode**: 100% LOCAL-FIRST (Supabase Disabled to prevent quota breach).
- **Resource Management**: Autonomous Governor active (Self-cleaning logs).
- **Node Health**: 3/3 Nodes Online (Batam, Scanner, Executor).
- **Stability**: High (Uptime verified).
- **Safety**: "Sovereign Shield" active (Zero-trust SSH mesh).
