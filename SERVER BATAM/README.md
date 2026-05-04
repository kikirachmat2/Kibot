# Batam Control Plane (The Brain)

## Overview
Batam is the **Single Source of Truth** and the sole decision-maker in the KiBot ecosystem. It follows a centralized intelligence architecture where all scanners report raw data here, and all executors wait for commands from here.

## Responsibilities
1. **Intelligence & Analysis**: Processes raw sensory data from global scanners.
2. **Strategy Orchestration**: Decides when to enter/exit markets based on consolidated signals, news, and risk management.
3. **Command Issuance**: Sends cryptographically signed execution payloads to Executor nodes via the `pending_commands` table.
4. **Risk Management**: Monitors global exposure, PnL, and balance across all exchanges.

## Architecture
- **Control Plane**: The central logic hub.
- **Command Dispatcher**: Manages the lifecycle of commands (Pending -> Executed/Failed).
- **Audit Logger**: Collects and centralizes execution logs from all remote nodes.

## Connection Points
- **Inbound**: UDP Sensory Stream (Port 9999) from Scanners.
- **Outbound**: Command Polling API/Supabase for Executors.
- **Management**: Dashboard for human monitoring and manual overrides.
