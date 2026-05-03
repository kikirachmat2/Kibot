# [Batam] The Trinity AI Brain

This directory serves as the command-and-control center for the KiBot system. It is responsible for decision-making, intelligence gathering, and system self-healing.

## Sub-components

### 1. [Core_Logic](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Core_Logic/)
Contains the central manager that orchestrates signals and position gating.
- `kibot_manager.py`: The monolithic coordinator for all trading logic.
- `ki_brain.py`: High-level intelligence management.

### 2. [AI_Orchestration](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/AI_Orchestration/)
Integrates Large Language Models and web search tools for market validation.
- `kibot_ai_coordinator.py`: Manages prompt templates and multi-provider AI calls.
- `kibot_ai_scout.py`: Autonomous world scout for real-time news validation.
- `kibot_ai_search.py`: Search utility wrapper (Tavily, Serper, etc.).

### 3. [Intelligence](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Intelligence/) (v8.0 Bayesian Evolution)
Implements simulation, learning, and regime-aware rotation logic.
- **Intelligence v8.1 (Red Team Edition)**: Bayesian Kelly sizing, Oracle Circuit Breakers, and HMAC-signed learning states.
- **Sovereign Shield**: HMAC-signed logging, Hardware-bound Vault, and Trade Sentinel price vetoes.
- `sovereign_arbitrator.py`: The master capital allocator with "What-If" validation.

### 4. [Indicators_Math](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Indicators_Math/)
Mathematical foundations for anomaly detection.
- `ki_stats.py`: Z-score and statistical calculations.
- `ki_capital_engine.py`: Position sizing and risk math.

### 5. [Stability](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Stability/)
The watchdog layer ensuring 100% uptime.
- `ki_revival_engine.py`: The "Lazarus Engine" that monitors and restarts failed services.

### 6. [Global_State](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Global_State/)
Shared JSON files acting as the system's short-term memory.

### 7. [Support](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Support/)
Non-core tools including Web Dashboard, Android APK assets, and Audit suites.

### 8. [Infrastructure](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Infrastructure/)
System logs, SSH keys, and systemd service templates.

### 9. [Sovereign Shield](file:///Users/kiki/Documents/Web%20Develop/KiBot/Batam/Security/) (New Security Layer)
Advanced defensive infrastructure protecting capital and credentials.
- `Security/kibot_sentinel.py`: Real-time trade velocity and anomaly protection.
- `Security/kibot_security.py`: Cryptographic log signing and integrity verification.
- `Support/ki_vault.py`: AES-256 hardware-bound encryption for API secrets.
- `Support/ki_config.py`: Integrated secure loading and egress health checks.
