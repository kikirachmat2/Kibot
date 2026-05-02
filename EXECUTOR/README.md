# [EXECUTOR] The Tactical Hands

This directory contains the high-performance execution layer. While the Brain (Batam) decides "what" to trade, the EXECUTOR handles the "how" and "when" at the micro-level.

## Sub-components

### 1. [Kotlin_Engine](file:///Users/kiki/Documents/Web%20Develop/KiBot/EXECUTOR/Kotlin_Engine/)
A Kotlin-based daemon optimized for low-latency execution on macOS.
- **Runtime**: Core execution loops, circuit breakers, and autonomous trade reviews.
- **Config**: Tuning parameters for "Barbarian" vs "Passive" modes.
- **State**: Persistent local storage for trade history and learning snapshots.

### 2. [Local_State](file:///Users/kiki/Documents/Web%20Develop/KiBot/EXECUTOR/Local_State/)
Execution-specific logs and snapshots.
- `trade_log.jsonl`: Real-time record of all fills and order submissions.

### 3. [Binaries](file:///Users/kiki/Documents/Web%20Develop/KiBot/EXECUTOR/Binaries/)
Compiled artifacts (JARs) for the execution engine.

### 4. [Infrastructure](file:///Users/kiki/Documents/Web%20Develop/KiBot/EXECUTOR/Infrastructure/)
Deployment scripts and SSH credentials for execution nodes.

## Audit Observation: Monolithic Risk
The `MacEngineDaemon.kt` file is extremely large (15k lines). This presents a critical stability risk; a failure in any sub-component (e.g., notification) could theoretically stall the entire execution thread. Future refactoring should decouple the notification and state-management layers from the core execution loop.
