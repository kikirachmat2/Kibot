# [Module] Kotlin Engine (The Tactical Execution)

This is the high-performance heart of the trade execution layer. Built in Kotlin/JVM for speed and multi-threaded reliability on macOS.

## Key Components (Source: `mac-engine`)

### 1. `MacEngineDaemon.kt` (The Pilot)
- **Role**: The main execution loop for order submission.
- **Responsibilities**:
    - Listens for `LEAD_LAG_SIGNAL` and `SMART_ENTRY` from the Brain.
    - Manages the local orderbook and connectivity to Indodax/Binance.
    - Implements the "Barbarian" (Hyper-aggressive) vs "Passive" execution styles.
    - Handles low-level trade logic like "Lead-Lag Ack" and "Trading Stall" detection.

### 2. `MacStateRepository.kt`
- **Role**: Persistent trade memory.
- **Responsibilities**:
    - Keeps track of open positions, entry prices, and partial fill states.
    - Ensures trade data survives a daemon restart.

### 3. `AdaptiveAiPolicy.kt`
- **Role**: Execution strategy tuner.
- **Responsibilities**:
    - Adjusts execution aggressiveness based on local market conditions (Slippage/Spread).

## How to Build/Run
This is a standard Gradle project.
- **Build**: `./gradlew shadowJar`
- **Run**: `java -jar build/libs/mac-engine-all.jar`

## Audit Warning
This engine is a single monolithic file (`MacEngineDaemon`). It handles far too many responsibilities (Networking, Trade Logic, Notifications). Future refactoring must extract the `TelegramNotifier` and `StateRepository` into separate threads.
