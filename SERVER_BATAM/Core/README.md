# 🏰 KiBot Core

Fundamental trading engine and sovereign gateway logic.

## Responsibility
- **Signal Ingestion**: Handling high-frequency UDP packets.
- **Decision Matrix**: Core logic for execution dispatch.
- **Mesh Governance**: Managing the consensus between local and remote nodes.

## Key Files
- `ki_brain.py`: The decision engine. [UPDATED v9.2] Integrated Lead-Lag Binance validation and strict 10s latency threshold.
- `sovereign_arbitrator.py`: Final gate for trade approval.
- `trinity_governor.py`: Mesh status and synchronization.
- `batam_ghost_agent.py`: System self-analysis.
