# 🧠 [Module] Core Logic (Trinity Hub)

This module is the heartbeat of KiBot. It orchestrates all incoming signals, manages the trading state, and acts as the final decision-maker.

## Critical Engine Components

### 1. `kibot_manager.py` (The General)
- **Role**: Entry point for the entire trading loop, executed by `kibot-trinity.service`.
- **V9.1 Update**: Fixed initialization sequence to prevent `NameError` on `HardStopConfig`. Handles central signal aggregation from UDP Port 9999.

### 2. `sovereign_arbitrator.py` (The Judge)
- **Role**: Resolves conflicts between Indodax spot signals and Polymarket prediction outcomes. 
- **Philosophy**: "Tekan Kerugian, Maksimalkan Probabilitas".

### 3. `trinity_governor.py` (The Sentinel)
- **Role**: Watchdog for service integrity.
- **Feature**: Performs "Midnight Evolution" - nightly optimization of trading parameters based on PnL data.

### 4. `multi_scanner_engine.py` (Internal)
- **Role**: Manages internal data piping from raw UDP streams to the Decision Engine.

### 5. `batam_ghost_agent.py` (The Advisor)
- **Role**: Interactive Batam-side AI assistant for operator questions.
- **Feature**: Can pull local knowledge and RAG context from `AI_Orchestration/kibot_rag.py`.

## Operational Standards
- **Latency**: Critical decision path must remain under **1.2ms**.
- **State Persistence**: Uses `/state/sovereign_state.json` for crash recovery.
- **AI Integration**: Non-blocking async veto calls to DeepSeek-Coder-V2 for signal verification.
