# KiBot Core Logic: The Sovereign Trading Council

This directory contains the "Intelligence & Governance" layer of KiBot. While the bot's execution engine handles the raw speed of trading, the **Trading Council** provides the wisdom, auditing, and strategic oversight required for sovereign, long-term profitability.

## 🏛️ Architecture Overview

The Trading Council operates as a multi-tier auditing and decision-making system. It ensures that every action (or inaction) by the bot is recorded, analyzed, and debated to improve future performance.

### 1. `fast_path_logger.py` (The Auditor)
The first layer of accountability. It records every single signal evaluated by the bot's Fast Path.
- **Responsibility**: Logs `APPROVED`, `VETOED`, and `MATH_SKIP` decisions.
- **Data Capture**: Symbol, Price, Decision, and the specific reason (e.g., "Vetoed: RSI Overbought").
- **Storage**: `SERVER_BATAM/Logs/fast_path_signals.jsonl`.

### 2. `what_if_tracker.py` (The Opportunity Scout)
Monitors the "Path Not Taken." This component watches rejected signals to see if they would have been profitable.
- **Responsibility**: Tracks rejected coins for up to 12 hours, fetching real-time price updates.
- **Metrics**: Calculates `max_gain_pct` and `max_drawdown` for hypothetical trades.
- **Storage**: `SERVER_BATAM/Logs/what_if_analysis.json`.

### 3. `council_data_aggregator.py` (The Librarian)
Synthesizes data from across the system to provide a high-fidelity context for the AI agents.
- **Responsibility**: Aggregates Portfolio State, Market Mood, Rejection Logs, What-If results, and Pair History.
- **Context Awareness**: Connects to the `LearningEngine` to fetch historical stats (Win Rate, Profit Factor) for every coin under debate.

### 4. `trading_council.py` (The High Court)
Orchestrates automated AI debates using specialized personas.
- **Personas**:
    - 🦅 **MomentumHawk**: Aggressive, focuses on "Missed Bags" and high-momentum opportunities.
    - 🛡️ **RiskSentinel**: Conservative, focuses on capital preservation and drawdown prevention.
    - 🕵️ **OpportunityScout**: Balanced, looks for hidden gems and analyzes the "What-If" data to find patterns.
- **Output**: Generates `council_directives.json`, which sets the bot's "Risk Level" and "Global Bias" for the next cycle.

---

## 🔄 The Data Lifecycle

1. **Signal Ingress**: A signal hits the Fast Path.
2. **Decision & Log**: `FastPathLogger` records the outcome. If rejected, it signals `WhatIfTracker`.
3. **Background Audit**: `WhatIfTracker` watches the coin price for hours.
4. **Periodic Sync (Every 4h)**: `CouncilDataAggregator` builds a "Debate Context."
5. **Council Debate**: The 3 AI Agents debate the context.
6. **Directive Issuance**: A unified directive is sent to the bot and reported to Telegram.

## 🛠️ Manual Testing & Tools

### Aggregator Test
To verify the data being fed to the council:
```bash
python3 SERVER_BATAM/scratch/test_aggregator.py
```

### Logs Directory
All persistent data is stored in `SERVER_BATAM/Logs/`:
- `fast_path_signals.jsonl`: Raw signal logs.
- `what_if_analysis.json`: Hypo-PnL analysis.
- `council_directives.json`: Strategic history.

---

## 📜 Council Philosophy
*"Sedikit demi sedikit, lama-lama jadi Bukit"* (Little by little, eventually it becomes a hill).
The council prioritizes **Capital Preservation** and **High-Probability Entries** over high-frequency gambling.
