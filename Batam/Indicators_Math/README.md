# [Module] Indicators & Math (The Foundation)

This module contains the "Hard Math" that powers KiBot. It is pure, deterministic logic used to calculate volatility, confidence, and position sizes.

## Key Files

### 1. `ki_stats.py` (The Calculator)
- **Role**: Statistical utility library.
- **Responsibilities**:
    - Calculates **Z-Scores** (Standard Deviations) to detect price anomalies.
    - Computes moving averages, volatility (ATR), and relative strength.
- **Usage**: Imported by almost every other module to perform math checks.

### 2. `ki_capital_engine.py` (The Accountant)
- **Role**: Position sizing and risk manager.
- **Responsibilities**:
    - Calculates the exact IDR amount to buy based on confidence scores.
    - Implements **Adaptive Trailing Stops** and **Partial Take-Profit (TP)** logic.
    - Enforces "Hard Stop" guards to prevent catastrophic daily losses.
- **Usage**: Used by the Manager to determine the "Weight" of an entry.

### 3. `ki_math_v2.py`
- **Role**: Legacy and refined math functions.
- **Responsibilities**:
    - Fast calculations for orderbook depth and slippage estimation.

## Why this is critical
If the math here is wrong, the bot will either over-leverage and blow the account, or trade with such small sizes that it never makes a profit. This is the most stable and "distrustful" part of the code—it doesn't care about news, only numbers.
