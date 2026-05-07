# 🧠 SERVER_BATAM (The Brain) - Trinity v9.1

## Overview
Batam is the **Single Source of Truth** and the central command center of the KiBot ecosystem. It aggregates sensory data from globally distributed Scanners and issues execution orders to reactive Executor nodes.

## Core Components
- **Core_Logic/**: Contains `kibot_manager.py` (Main entry), `trinity_governor.py` (Git-safe tuning and recovery), and `batam_ghost_agent.py` (interactive AI assistant).
- **AI_Orchestration/**: Integrates local LLMs via Ollama, the local RAG index, and the Ollama gateway for autonomous code healing and sentiment validation.
- **Indicators_Math/**: Handles Z-Score, technical analysis, and Polymarket probability math.
- **Security/**: Enforces the "Sovereign Shield" and monitors for unauthorized system changes.

## Deployment & Management
Batam operates via systemd:
- `kibot-trinity.service`: Primary autonomous brain runtime on Batam.
- `kibot-manager.service`: Compatibility shim for legacy references.
- `kibot-orchestrator.service`: Oversees support services and recovery helpers.
- `kibot-healer.service`: Autonomous maintenance via local Ollama-backed AI.
- `kibot-command-center.service`: Local command dashboard and status UI.
- `kibot-trinity.service`: Primary runtime; `kibot-manager.service` exists only as a compatibility shim.

## Current System Status (v9.1.1 Sovereign)
- **Mode**: 100% LOCAL-FIRST (Supabase Disabled to prevent quota breach).
- **Resource Management**: Autonomous Governor active (Self-cleaning logs).
- **Node Health**: 3/3 Nodes Online (Batam, Scanner, Executor).
- **Stability**: High (Uptime verified).
- **Safety**: "Sovereign Shield" active (Zero-trust SSH mesh).
