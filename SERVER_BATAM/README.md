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

## 🤖 Trinity Orchestration
The Master node manages specialized Python Executors:
- **Indodax Node**: High-frequency spot trading.
- **Polymarket Node**: Web3 prediction market execution.

---
*Environment:* **PRODUCTION (Python-Native)**
*Sovereignty Level:* **MAXIMUM**
