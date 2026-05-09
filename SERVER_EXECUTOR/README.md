# ⚡ KiBot: Precision Execution (Python-Native Executor)

> **Role**: High-Speed Python Order Fulfillment & Sovereign Resiliency
> **Motto**: "Pythonic Precision, Maximum Sovereign Profits"

## 📂 Structured Hierarchy

### 🐍 [/Core/Python_Executor](file:///home/ubuntu/KiBot/SERVER_EXECUTOR/Core/Python_Executor/)
The sovereign execution core. No JVM/Kotlin dependencies.
- `indodax_executor.py`: Dedicated Indodax trading node (Port 9999).
- `polymarket_executor.py`: Dedicated Polymarket Web3 node (Port 9990).
- `risk_gate.py`: Safety-first order validation engine.
- `trinity_cli.py`: Unified control interface for all executors.

### 📦 [/Infrastructure](file:///home/ubuntu/KiBot/SERVER_EXECUTOR/Infrastructure/)
Service management and hardening.
- `systemd/`: Autonomous background services (`kibot-indodax.service`, `kibot-polymarket.service`).

### 🛡️ [/Security](file:///home/ubuntu/KiBot/SERVER_BATAM/Support/ki_vault.py)
The sovereign vault integration.
- Uses `ki_vault.py` to load encrypted secrets from `.env.kiv`.

---
*Operational Protocol: "Execute with Pythonic Speed, Guard the Capital with Sovereign Logic"*
