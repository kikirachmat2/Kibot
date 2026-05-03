# KiBot Intelligence Layer (v8.0)

This directory contains the brain of KiBot, responsible for data-driven capital allocation and position optimization.

## Components

### 1. Sovereign Arbitrator (`Core_Logic/sovereign_arbitrator.py`)
The central decision engine that gates all trade entries.
- **Bayesian Allocation**: Uses historical performance (Win Rate, Profit Factor) to scale trade sizes.
- **Security Gating**: Directly integrated with `TradeSentinel` for anomaly protection.
- **Simulation Cross-Check**: Vetoes trades that fail "What-If" historical backtests.

### 2. Learning Engine (`kibot_learning_engine.py`)
The persistent memory of the system.
- **Pair Health**: Calculates a real-time health score (0.0 to 1.0) for every traded pair.
- **Kelly Sizing**: Provides optimal fractional Kelly fractions based on pair-specific volatility and performance.

### 3. Rotation Engine (`kibot_rotation_engine.py`)
The portfolio optimizer.
- **v8.0 Upgrades**:
    - **Regime Awareness**: Adjusts sensitivity based on BULL/BEAR/PANIC market states.
    - **Sector Correlation**: Prevents rotating capital between assets in the same sector during market distress.
    - **Distress Recovery**: Prioritizes swapping losing positions for "Elite" (Confidence > 85/92) signals.

## Data Flow
1. `kibot_manager` identifies a signal.
2. `SovereignArbitrator` requests stats from `LearningEngine`.
3. `SovereignArbitrator` validates price with `TradeSentinel`.
4. `SovereignArbitrator` checks `whatif_results.json` for simulation sanity.
5. Final allocation is calculated and passed back to the manager for execution.
