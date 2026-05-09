# KiBot Trinity Mesh: Sovereign Trading Intelligence

Sovereign autonomous trading ecosystem optimized for high-frequency execution and self-healing across a distributed mesh (Batam & Singapore).

## 🛰️ Mesh Architecture (Trinity)
- **Master Node (Batam - Ubuntu 24.04):** The Command Center. Hosts the Brain (KiBrain), Vault, and the AI Mechanic.
- **Scanner Node (Singapore):** Global market sentiment and signal generation.
- **Executor Node (Singapore):** High-speed exchange execution (Indodax & Polymarket).

## 🧠 AI Operational Layers
1. **The Sniper (Llama 3.2 1.5B):** Real-time signal gatekeeper. Low latency noise rejection.
2. **The Scout (Llama 3.1 1B):** Background sentiment analyst. Keeps the system aligned with global market pulse.
3. **The Mechanic (Qwen2.5-Coder 7B):** Autonomous self-healer. Diagnoses logs and patches code-level bugs using `aider`.

## 🛡️ Sovereign Security & Vault
- **Hardware-Bound Encryption:** API Keys are bound to the Batam server hardware via `SovereignVault`.
- **Auto-Fallback:** System automatically handles .env -> .env.kiv transitions for seamless deployment.
- **Tailscale Mesh:** All inter-node communication is encrypted and isolated from the public internet.

## 🛠️ Operational Commands (Batam)
```bash
# Start the High Command
export PYTHONPATH=$PYTHONPATH:$(pwd)
python3 SERVER_BATAM/KiBot.py

# Check System Logs
tail -f SERVER_BATAM/Logs/kibot_master.log

# Trigger Manual AI Healing
python3 SERVER_BATAM/Support/ki_vault.py setup
```

## 💓 Autonomous Heartbeats
- **Resource Monitor:** Every 5 mins (RAM/Mesh Health).
- **Global Market Pulse:** Every 30 mins (Sentiment Update).
- **Daily Heartbeat:** Every 08:00 AM (Telegram Performance Report).
- **Midnight Oracle:** 00:00 AM (Encrypted Backups & Audit).

---
*Status:* **LIVE MODE ACTIVE 🟢**
*Sovereignty:* **FULLY AUTONOMOUS 🦾**