# ⚡ SERVER_EXECUTOR (Reactive Hands) - Trinity v9.1

## Overview
This is a **Reactive Execution Service** designed for absolute control by the **Batam Control Plane**. It acts as the "Hands" of the system, performing high-speed trade execution across multiple venues.

## Core Principles
1. **Reactive Only**: No local decision-making. It purely executes `ExecutionPlan` payloads from Batam.
2. **Atomic Execution**: Uses `ClientOrderId` mapping to ensure trades are never double-executed.
3. **Multi-Venue**: Native support for **Indodax** (Spot) and **Polymarket** (Prediction/CLOB).
4. **Kotlin-Powered**: Built on the JVM for multi-threaded performance and safety.

## Key Modules
- **Kotlin_Engine/mac-engine**: Source code for the core reactive engine.
- **Binaries/mac-engine-all.jar**: The production-ready fat JAR for deployment.
- **Infrastructure/systemd**: Service files for low-latency execution.

## Deployment & systemd
- `kibot-executor-engine.service`: Manages Indodax spot execution.
- `kibot-polymarket.service`: Specialized executor for Polymarket positions.

> [!NOTE]
> **Optimization Update**: Legacy services (`kibot-engine.service` and `kibot-manager.service`) have been removed to prevent port conflicts and optimize memory usage.

## Command Polling
- **Interval**: 1 second polling from `pending_commands` table.
- **Heartbeat**: Nodes report health state every 15s to Batam.
