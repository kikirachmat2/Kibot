# KiBot (Kiki "punya" Bot)

Autonomous, safety-first cryptocurrency trading agent system.

---

## 📁 Repository Structure

This repository is structured into two main evolutions:

```text
KiBot/
├── KiBot V1/          # [Archive / Reference] Production-tested V1 system
└── KiBot V2/          # [Active Workspace] Next-Gen rebuild starting fresh
```

---

### 1. `KiBot V1/` (Legacy Architecture & Core References)
The complete initial implementation of the sovereign autonomous trading agent:
* **Market Scanner**: Small-cap momentum detection, Binance-to-Indodax lead-lag, anti tick-trap filtering.
* **Sovereign Council**: Multi-agent deliberative governance (`MasterNode.py`) with AI scouting & deterministic fallbacks.
* **Safety & Risk Gates**: 18% overall drawdown circuit breaker, 3% daily loss cap, pre-trade orderbook simulation, and idempotency protection.
* **Multi-Variant Paper Learning**: 6 concurrent variants (`Baseline`, `Aggressive`, `Conservative`, `AI Assisted`, `AI Ranker`, `APPROVED`) with rigorous 5-criteria live readiness audit.
* **Infrastructure**: Dual-server distributed operation (SG1 primary node, SG2 external watchdog with 30s probing & 2h mirror backups, and Batam cloud provisioning hunter).
* **Documentation**: See [`KiBot V1/README.md`](./KiBot%20V1/README.md) and [`KiBot V1/docs/`](./KiBot%20V1/docs/).

---

### 2. `KiBot V2/` (Next-Generation Evolution)
Fresh greenfield project space:
* Starting from scratch with a modernized, simplified, and high-performance stack.
* Reusing proven core logic, safety contracts, and mathematical models calibrated in V1 without legacy debt.

---

## 🛡️ License & Disclaimers
Experimental software for research and autonomous agent development. Real-money live trading requires explicit gates.
