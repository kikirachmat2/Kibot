# KiBot Executor (Lobotomized Version)

## Overview
This is a **Reactive Execution Service** designed to operate under the absolute control of the **Batam Control Plane**. All autonomous decision-making logic, strategy orchestrators, and local AI modules have been removed to prevent strategy conflicts and ensure centralized intelligence.

## Core Principles
1. **No Local Strategy**: This service does not analyze markets or decide when to buy/sell. It only executes commands received from Batam.
2. **Idempotent Execution**: Every command uses a unique `ClientOrderId` derived from the Batam Command ID to prevent accidental double-execution.
3. **Multi-Exchange Support**: Native support for **Indodax** (CEX) and **Polymarket** (DEX/CLOB) via unified `ExecutionPlan`.
4. **Fast Reaction**: Command polling interval is set to 1 second for high-responsiveness.

## Command Protocol (JSON Payload)
The Batam Control Plane sends commands with the following JSON structure:
```json
{
  "exchange": "INDODAX | POLYMARKET",
  "pair": "btc_idr | market_slug",
  "side": "BUY | SELL",
  "amount": 1.5,
  "price": 500000.0,
  "type": "MARKET | LIMIT",
  "slippage": 0.01,
  "marketId": "optional_token_id_for_polymarket"
}
```

## Infrastructure
- **MacEngineDaemon.kt**: The main entry point that polls for commands and routes them to the Exchange Gateway.
- **Shared Library**: Provides the underlying connectivity to Supabase (Control Plane) and Exchanges.

## Health Monitoring
The service reports a heartbeat every 15 seconds. If the heartbeat stops, Batam will consider this node offline and stop sending commands.
