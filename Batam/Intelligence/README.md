# [Module] Intelligence (Learning & Optimization)

This module is responsible for the system's "Self-Evolution." It analyzes past trades to optimize future performance and manages capital rotation to maximize yield.

## Key Files

### 1. `kibot_learning_engine.py` (The Experience)
- **Role**: Statistical trade analyzer.
- **Responsibilities**:
    - Records every trade outcome (Win/Loss/PnL).
    - Detects underperforming pairs or market regimes (e.g., "Market is choppy, tighten stops").
    - Provides a "Learn Gate" that can block trades on pairs that have consistently failed recently.
- **Usage**: Automatically updated by the Manager after every trade fill.

### 2. `kibot_rotation_engine.py` (The Strategist)
- **Role**: Capital allocator and opportunity seeker.
- **Responsibilities**:
    - Monitors which asset categories (Buckets) are performing best.
    - Moves capital from slow-moving or underperforming pairs to high-velocity opportunities.
    - Implements "Round Trip" limits to prevent over-trading.
- **Usage**: Runs as a background logic loop within the Manager.

### 3. `kibot_whatif_engine.py` (The Simulator)
- **Role**: Risk/Reward validator.
- **Responsibilities**:
    - Runs "What-If" simulations on potential entries.
    - Calculates "Expected Value" (EV) based on current volatility and historical z-scores.
- **Usage**: Used as a gatekeeper in the entry pipeline.

## How to use
You don't usually run these manually. They are "internal services" that make the Brain smarter. To see the "lessons" learned, check the `state/learning_memory.json` (moved to Global_State).
