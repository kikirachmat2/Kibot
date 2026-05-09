# Batam High Command Node (Master)

This server acts as the sovereign brain of the KiBot Trinity Mesh.

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
- **Signal Ports:** `9998` (Receiver), `9997` (Feedback)

## 📋 Monitoring Logs
- **Master Log:** `tail -f Logs/kibot_master.log`
- **Vault Debug:** `tail -f Logs/vault.log`

## 🤖 Self-Healing (The Mechanic)
When a mesh node fails, the Master will:
1. Pull remote logs via `get_remote_logs()`.
2. Analyze via `qwen2.5-coder:7b`.
3. Apply fix via `aider`.
4. Restart remote service.

---
*Environment:* **PRODUCTION**
*Sovereignty Level:* **MAXIMUM**
