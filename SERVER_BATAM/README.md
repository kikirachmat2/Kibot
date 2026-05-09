# Batam High Command Node (Master)

This server acts as the sovereign brain of the KiBot Trinity Mesh, orchestrating Scanners and Python Executors.

## 🚀 Quick Start
```bash
# 1. Register SSH Keys
ssh-add Infrastructure/SSH/ssh-key-batam-active.pem

# 2. Run KiBot Master
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 KiBot.py
```

## 🛠️ Infrastructure Services
- **Ollama:** `127.0.0.1:11434` (Logic Engine)
- **FastAPI Commander:** `0.0.0.0:8080` (Android Bridge)
- **Smart Signal Routing:** 
  - `9999` (UDP): Indodax Signal Route
  - `9990` (UDP): Polymarket (POLY: prefix) Route
  - `9997` (UDP): Feedback Loop

## 📋 Monitoring Logs
- **Master Log:** `tail -f Logs/kibot_master.log`
- **Executor Feedback:** `tail -f Logs/execution.log`

## 🏛️ Sovereign Trading Council
The Batam node now hosts a multi-tier governance layer that audits and refines trading strategies:
- **Fast Path Auditing**: Continuous logging of approved and vetoed signals.
- **What-If Analysis**: Background price tracking for rejected signals to quantify missed gains.
- **Agentic Debate**: Automated sessions between `MomentumHawk` and `RiskSentinel` personas to issue system-wide directives.

## 📂 Project Structure
- `Core/`: Fundamental signal routing and consensus logic.
- `Core_Logic/`: The Trading Council, Logging, and Data Aggregation.
- `Intelligence/`: AI Veto, Learning Engine, and Market Sentiment.
- `Strategic/`: Guardian safety guardrails and risk circuit breakers.
- `Security/`: Sovereign Vault (KiVault) and HMAC validation.
- `Interface/`: Trinity Pulse and mesh health monitoring.
- `Infrastructure/`: systemd services, Automation, and SSH management.
- `Support/`: Android APK build tools and Web Dashboard.

---
*Environment:* **PRODUCTION (Sovereign Python-Native Cluster)**
*Sovereignty Level:* **STRENG GEHEIM (Total Autonomy)**
