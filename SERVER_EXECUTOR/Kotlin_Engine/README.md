# ⚡ [Module] Kotlin Engine (Tactical Execution)

High-performance trade execution layer built on Kotlin/JVM for sub-millisecond tactical response.

## Core Modules

### 1. `MacEngineDaemon.kt` (The Pilot)
- **Role**: Main loop for command polling and order submission.
- **V9.1 Update**: Standardized for **Indodax Spot** and **Polymarket CLOB** execution.
- **Security**: Uses cryptographically signed `ClientOrderId` for idempotent operations.

### 2. `MacStateRepository.kt` (Memory)
- **Role**: Handles persistence of local trading state and fill-tracking.
- **Persistence**: Maps to `Local_State/` directory.

### 3. `ExecutionStyle` (Barbarian Engine)
- **Mode**: "Barbarian" (Aggressive Taker) vs "Passive" (Maker) styles, dynamically toggled by Batam's `ExecutionPlan`.

## Build & Deployment
This project uses **Gradle** and the `shadow` plugin to generate a standalone fat JAR.
- **Build Command**: `./gradlew shadowJar`
- **Output**: `Binaries/mac-engine-all.jar`
- **Runtime**: Managed via `kibot-executor-engine.service`.

## Performance Policy
- **Polling Latency**: 1s (standard) / 200ms (high-volatility burst).
- **Execution Overhead**: < 500μs (excluding network RTT).
