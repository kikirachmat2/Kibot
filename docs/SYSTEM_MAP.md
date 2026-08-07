# KiBot System Map — Living Architecture Reference

> **Purpose**: Single reference document for understanding the full KiBot system architecture.
> Anyone (including a new AI session) should be able to read this and understand what every file does, how data flows, and what has been fixed.
>
> **Last Updated**: 2026-08-07 02:00 WIB

---

## Table of Contents

1. [Data Flow Diagram](#1-data-flow-diagram)
2. [File Inventory](#2-file-inventory)
3. [Priority Audit Backlog](#3-priority-audit-backlog)
4. [Known Issues / Recently Fixed](#4-known-issues--recently-fixed)
5. [Key Constants & SSOT](#5-key-constants--ssot)

---

## 1. Data Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        MasterNode.py (Entrypoint)                           │
│   Bootstraps all subsystems, runs main async loop, schedules periodic tasks │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │ spawns
               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  STAGE 1 — SIGNAL ACQUISITION                               │
│                                                                              │
│  Core/Scanner/engine.py :: ScannerEngine._build_scanners()                  │
│    ├─ IndodaxMarketScanner  (Core/Scanner/indodax_market_scanner.py)         │
│    │   └─ Scans 180+ Indodax IDR pairs, detects pumps/volume spikes         │
│    │   └─ Embeds Binance lead-lag via indodax_binance_leadlag_scanner.py     │
│    ├─ IndodaxSmallCapScanner (Core/Scanner/ki_indodax_smallcap_scanner.py)   │
│    │   └─ Fallback if MarketScanner fails; targets micro/smallcap pairs     │
│    └─ UniversalLeadLagScanner (Core/Scanner/ki_universal_leadlag_scanner.py) │
│        └─ Global lead-lag across 18+ sources (disabled by default)          │
│                                                                              │
│  Core/Intelligence/leadlag_alpha.py :: LeadLagAlphaEngine                   │
│    └─ Compares Binance BTC/ETH/SOL/XRP vs Indodax follower prices           │
│    └─ Generates LEADLAG_ALPHA opportunities when leader move > 1.2%         │
│                                                                              │
│  engine.py._scan_one() stamps exchange="INDODAX" from scanner.exchange      │
│  engine.py filters: only exchange="INDODAX" candidates pass to pipeline     │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │ raw candidates
               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  STAGE 2 — SIGNAL QUALITY & ENRICHMENT                      │
│                                                                              │
│  Core/Intelligence/signal_quality.py :: SignalQualityEvaluator              │
│    └─ Grades candidates: STRONG / MODERATE / WEAK / REJECT                  │
│    └─ Checks: spread_pct, volume_ratio, daily_volatility_pct, data_age     │
│    └─ _IndodaxSummariesFetcher: 10s TTL cache enrichment for               │
│       LEADLAG_ALPHA candidates missing microstructure fields                │
│    └─ Fail-safe: enrichment failure → candidate stays REJECT               │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │ graded candidates
               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  STAGE 3 — STRATEGY EVALUATION                              │
│                                                                              │
│  Core/Intelligence/strategy_scorecard.py :: StrategyScorecard               │
│    └─ Composite score from signal_quality + market_regime + strategy_stats   │
│    └─ Thresholds: APPROVE ≥ 0.62 | PAPER ≥ 0.42 | REJECT < 0.42           │
│                                                                              │
│  Core/Intelligence/expected_value.py :: compute_ev()                        │
│    └─ EV = P(win) × net_win - P(loss) × net_loss                           │
│    └─ Gates: EV > 0, R:R ≥ 1.50, Kelly > 0                                │
│    └─ Default friction: fee 0.31%/leg + slippage 0.10%/leg                 │
│                                                                              │
│  Core/Intelligence/strategy_stats.py :: StrategyStatsAggregator             │
│    └─ Tracks per-strategy win_rate, avg_profit, avg_loss, sample_size       │
│    └─ Minimum 20 samples required for strategy graduation                  │
│                                                                              │
│  Core/Intelligence/autonomous_director.py :: AutonomousDirector             │
│    └─ Orchestrates full pipeline: scan → quality → scorecard → EV → verdict │
│    └─ Outputs: APPROVED / PAPER_ONLY / REJECT                              │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │ verdict
               ├─── APPROVED ──────────────────────────┐
               │                                        ▼
               │                     ┌──────────────────────────────────────┐
               │                     │  STAGE 4a — LIVE EXECUTION           │
               │                     │                                      │
               │                     │  Core/sovereign_council.py            │
               │                     │    └─ Council-of-advisors evaluation  │
               │                     │                                      │
               │                     │  Core/risk_gate.py :: RiskGate       │
               │                     │    └─ Validates notional min (Rp10k) │
               │                     │    └─ Daily drawdown cap (1.5%)      │
               │                     │    └─ Capital Governor reconciled?   │
               │                     │                                      │
               │                     │  Core/Trading/autonomous_sizing.py   │
               │                     │    └─ Calculates budget_idr          │
               │                     │    └─ Min trade Rp10,000             │
               │                     │                                      │
               │                     │  Core/Executors/Indodax/              │
               │                     │    indodax_executor.py                │
               │                     │    └─ Sends BUY order to Indodax API │
               │                     │    └─ Manages exit (TP/SL/max_hold) │
               │                     │    └─ Fee: 0.61% roundtrip (SSOT)   │
               │                     │                                      │
               │                     │  Core/Exchange/indodax.py             │
               │                     │    └─ Low-level Indodax REST API     │
               │                     └──────────────────────────────────────┘
               │
               └─── PAPER_ONLY ────────────────────────┐
                                                        ▼
                                     ┌──────────────────────────────────────┐
                                     │  STAGE 4b — PAPER TRADING            │
                                     │                                      │
                                     │  Core/Intelligence/                   │
                                     │    paper_trade_tracker.py             │
                                     │    └─ Opens virtual trades            │
                                     │    └─ Enforces net R:R ≥ 1.60 gate  │
                                     │    └─ TP=+3.5% / SL=-1.0%           │
                                     │    └─ Fee: 0.61% roundtrip (SSOT)   │
                                     │    └─ Dynamic trailing stop          │
                                     │    └─ Feeds learning engine on close │
                                     └──────────────────────────────────────┘

                                                        │
                                                        ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  STAGE 5 — TREASURY & RECONCILIATION                        │
│                                                                              │
│  Core/Treasury/capital_governor.py :: CapitalGovernor                       │
│    └─ Tracks daily PnL, equity anchors, drawdown caps                       │
│    └─ Writes state/capital_governor.json (must be RECONCILED & < 90s old)   │
│    └─ Per-venue ledger tracking via venue_ledger.py                         │
│                                                                              │
│  Core/Treasury/live_truth_manager.py                                        │
│    └─ Fetches real Indodax balance, writes state/live_truth.json            │
│                                                                              │
│  Core/Intelligence/order_tracker.py                                         │
│    └─ Phase 5 order lifecycle: PENDING → FILLED → EXIT → CLOSED            │
│                                                                              │
│  Core/Intelligence/exit_plan.py :: ExitPlanEngine                           │
│    └─ Manages exit strategies: TP, SL, trailing stop, max_hold             │
│    └─ Fee: 0.61% roundtrip (SSOT)                                          │
│                                                                              │
│  Core/Intelligence/kibot_learning_engine.py                                 │
│    └─ Learns from closed trades, updates strategy confidence                │
│    └─ Feeds back into strategy_stats for graduation system                  │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  STAGE 6 — REPORTING & NOTIFICATIONS                        │
│                                                                              │
│  Core/sovereign_notifier.py                                                  │
│    └─ Telegram notifications (trade opens, closes, daily reports)            │
│                                                                              │
│  Core/Support/telegram_throttle.py                                           │
│    └─ Rate-limits Telegram sends to prevent flooding                         │
│                                                                              │
│  Core/Support/workflow_supervisor.py                                         │
│    └─ Orchestrates daily reset, health checks, reconciliation cycles         │
│                                                                              │
│  Core/Intelligence/kibot_dashboard.py                                        │
│    └─ Rich HTML dashboard (2121 lines, reads state from many modules)        │
│                                                                              │
│  Core/ki_brain.py                                                            │
│    └─ Telegram command handler (/status, /doctor, /profit, etc.)             │
│    └─ 2392 lines — routes user commands to appropriate subsystems            │
└──────────────────────────────────────────────────────────────────────────────┘

                    ┌────────────────────────────────┐
                    │  OPERATOR TOOLING               │
                    │                                  │
                    │  bin/kibotctl (462 lines, bash)  │
                    │    └─ status, doctor, restart    │
                    │    └─ model sync, deposit-notify │
                    │                                  │
                    │  Core/Support/ki_config.py       │
                    │    └─ All constants & SSOT       │
                    │    └─ Fee constants, canary mode │
                    │    └─ Feature flags              │
                    └────────────────────────────────┘
```

---

## 2. File Inventory

### Legend
- **ACTIVE**: Called in production pipeline, registered in a scanner/controller registry
- **CONFIRMED DEAD**: Confirmed duplicate or unreferenced file (retained for safety, superseded by production version)
- **INDIRECT / SCRIPTS**: Referenced by audit scripts / state generators only, not in hotpath
- **TESTS ONLY**: Only referenced by unit tests
- **FEATURE-FLAGGED**: Active only when specific feature flag enabled (e.g. `SCANNER_ENABLE_UNIVERSAL`)
- **PARTIAL**: Imported somewhere but rarely triggered in current production flow

### Core/Scanner/ — Signal Acquisition Layer

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/engine.py) | 471 | Scanner orchestrator; builds scanners, dispatches `collect_signals()`, stamps `exchange` field | **ACTIVE** | 2026-06-06 |
| [indodax_market_scanner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/indodax_market_scanner.py) | 481 | Primary Indodax scanner; scans 180+ pairs for volume/pump signals | **ACTIVE** | 2026-08-05 |
| [ki_indodax_smallcap_scanner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/ki_indodax_smallcap_scanner.py) | 771 | Fallback smallcap scanner; targets micro/low-cap Indodax pairs | **PARTIAL** (fallback only) | 2026-05-15 |
| [ki_universal_leadlag_scanner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/ki_universal_leadlag_scanner.py) | 128 | Global lead-lag scanner across 18+ sources (disabled by default via `SCANNER_ENABLE_UNIVERSAL`) | **FEATURE-FLAGGED** | 2026-08-05 |
| [indodax_binance_leadlag_scanner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/indodax_binance_leadlag_scanner.py) | 711 | Embedded lead-lag detection within IndodaxMarketScanner | **ACTIVE** (used internally) | 2026-05-21 |
| [scanner_executor_contract.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/scanner_executor_contract.py) | 137 | Validates that scanner output matches expected contract schema | **ACTIVE** | 2026-06-06 |
| [scanner_health.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/scanner_health.py) | 35 | Scanner health metrics writer | **PARTIAL** | 2026-05-20 |
| [scanner_health_runner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/scanner_health_runner.py) | 28 | Runner wrapper for scanner health checks | **PARTIAL** | 2026-05-20 |
| [source_proof.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/source_proof.py) | 80 | Logs provenance/proof of signal data source | **PARTIAL** | 2026-05-20 |

### Core/Intelligence/ — Evaluation & Decision Layer

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [signal_quality.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/signal_quality.py) | 320 | Grades candidates by microstructure quality (spread, volume, volatility) with Indodax enrichment | **ACTIVE** | 2026-08-05 |
| [strategy_scorecard.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/strategy_scorecard.py) | 132 | Composite score: signal_quality + regime + strategy_stats → APPROVE/PAPER/REJECT | **ACTIVE** | 2026-07-29 |
| [expected_value.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/expected_value.py) | 174 | Computes EV, R:R ratio, Kelly fraction; gates approval on EV>0 & R:R≥1.50 | **ACTIVE** | 2026-08-05 |
| [strategy_stats.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/strategy_stats.py) | 296 | Per-strategy win_rate/avg_profit/avg_loss aggregator; 20-sample graduation | **ACTIVE** | 2026-08-05 |
| [autonomous_director.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/autonomous_director.py) | 202 | Pipeline orchestrator: scan → quality → scorecard → EV → verdict | **ACTIVE** | 2026-07-29 |
| [leadlag_alpha.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/leadlag_alpha.py) | 220 | Binance vs Indodax lead-lag alpha engine for BTC/ETH/SOL/XRP | **ACTIVE** | 2026-08-05 |
| [paper_trade_tracker.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/paper_trade_tracker.py) | 356 | Virtual paper trade lifecycle (open/evaluate/close), R:R gate, trailing stop | **ACTIVE** | 2026-08-05 |
| [exit_plan.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/exit_plan.py) | 323 | Exit strategy engine (TP, SL, trailing stop, max_hold, breakeven logic) | **ACTIVE** | 2026-08-05 |
| [order_tracker.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/order_tracker.py) | 635 | Phase 5 order lifecycle state machine: PENDING → FILLED → EXIT → CLOSED | **ACTIVE** | 2026-07-29 |
| [pair_quarantine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/pair_quarantine.py) | 173 | Quarantines underperforming pairs, blocks re-entry for cooldown period | **ACTIVE** | 2026-07-29 |
| [kibot_learning_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_learning_engine.py) | 700 | Learns from closed trades, adjusts strategy confidence, feeds strategy_stats | **ACTIVE** | 2026-08-05 |
| [indodax_microstructure.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/indodax_microstructure.py) | 128 | Analyzes orderbook depth, spread quality, taker fee impact | **ACTIVE** | 2026-08-05 |
| [pre_trade_simulator.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/pre_trade_simulator.py) | 189 | Pre-trade simulation: expected slippage, breakeven, net yield | **ACTIVE** | 2026-08-05 |
| [aggregator.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/aggregator.py) | 411 | Aggregates signals from multiple scanners into unified candidate list | **ACTIVE** | 2026-06-06 |
| [kibot_dashboard.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_dashboard.py) | 2121 | Rich HTML dashboard rendering (reads all state files) | **ACTIVE** | 2026-08-04 |
| [kibot_ai_coordinator.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_coordinator.py) | 1511 | LLM-based AI coordinator for market analysis; uses Ollama gateway | **PARTIAL** (depends on Ollama availability) | 2026-06-06 |
| [kibot_ai_scout.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_scout.py) | 672 | AI-powered market scouting agent | **PARTIAL** (depends on Ollama availability) | 2026-06-06 |
| [kibot_ai_search.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_search.py) | 433 | AI-powered search for market intelligence | **PARTIAL** (depends on Ollama availability) | 2026-05-20 |
| [daily_context.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/daily_context.py) | 242 | Builds daily market context summary for decision-making | **ACTIVE** | 2026-05-20 |
| [daily_report.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/daily_report.py) | 148 | Generates daily performance report for Telegram | **ACTIVE** | 2026-06-06 |
| [decision_journal.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/decision_journal.py) | 225 | Logs every trade decision with rationale for audit trail | **ACTIVE** | 2026-05-20 |
| [trade_history.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/trade_history.py) | 288 | Reads/writes trade history JSONL files | **ACTIVE** | 2026-06-06 |
| [coin_category.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/coin_category.py) | 138 | Categorizes coins by market cap tier (mega/large/mid/small/micro) | **ACTIVE** | 2026-05-15 |
| [probability_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/probability_engine.py) | 117 | Bayesian probability estimates for trade outcomes | **PARTIAL** | 2026-05-15 |
| [punishment_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/punishment_engine.py) | 227 | Penalizes strategies with consecutive losses | **ACTIVE** | 2026-05-18 |
| [market_heatmap.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/market_heatmap.py) | 114 | Generates market sector heatmap | **PARTIAL** | 2026-05-15 |
| [market_rotation.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/market_rotation.py) | 97 | Detects sector rotation patterns | **PARTIAL** | 2026-06-06 |
| [kibot_whatif_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_whatif_engine.py) | 339 | What-if scenario simulator for hypothetical trades | **PARTIAL** | 2026-05-15 |
| [_deprecated/Intelligence/kibot_ollama_gateway.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/_deprecated/Intelligence/kibot_ollama_gateway.py) | 257 | Unreferenced Ollama gateway wrapper | **CONFIRMED DEAD** (moved to `Core/_deprecated/` on 2026-08-08) | 2026-05-13 |
| [_deprecated/Intelligence/kibot_rag.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/_deprecated/Intelligence/kibot_rag.py) | 96 | Unreferenced market knowledge RAG | **CONFIRMED DEAD** (moved to `Core/_deprecated/` on 2026-08-08) | 2026-05-11 |
| [no_idle_director.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/no_idle_director.py) | 34 | Thin wrapper to prevent idle loops in director | **ACTIVE** | 2026-05-19 |
| [_deprecated/Intelligence/strategy/deadline_profit_enforcer.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/_deprecated/Intelligence/strategy/deadline_profit_enforcer.py) | 108 | Legacy profit enforcer | **CONFIRMED DEAD** (moved to `Core/_deprecated/` on 2026-08-07) | 2026-05-19 |

### Core/Decision/ — Decision & Trading Brain Layer

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [decision_authority.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/decision_authority.py) | 294 | Central decision authority for trade approval/rejection | **ACTIVE** | 2026-05-20 |
| [deterministic_decision_gate.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/deterministic_decision_gate.py) | 106 | Hard deterministic gate: checks all conditions before live trade | **ACTIVE** | 2026-06-02 |
| [live_opportunity_tier.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/live_opportunity_tier.py) | 159 | Tiers opportunities by quality for live trading prioritization | **ACTIVE** | 2026-06-02 |
| [live_order_dispatcher.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/live_order_dispatcher.py) | 282 | Dispatches approved orders to exchange executor | **ACTIVE** | 2026-06-06 |
| [autonomous_trading_brain.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/autonomous_trading_brain.py) | 265 | Autonomous trading brain coordinating sizing + decision | **ACTIVE** | 2026-08-04 |
| [deadline_profit_enforcer.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/deadline_profit_enforcer.py) | 224 | Enforces profit targets with time-based escalation & paper bypass | **ACTIVE** | 2026-08-05 |
| [daily_reset_coordinator.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/daily_reset_coordinator.py) | 267 | Daily state reset at WIB midnight boundary | **ACTIVE** | 2026-05-27 |
| [indodax_target_board.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/indodax_target_board.py) | 269 | Target price board for Indodax positions | **PARTIAL** | 2026-05-27 |
| [indodax_live_brain.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/indodax_live_brain.py) | 150 | Indodax-specific live trading brain wrapper | **PARTIAL** | 2026-08-04 |
| [indodax_no_idle_loop.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/indodax_no_idle_loop.py) | 96 | Anti-idle loop for Indodax scanning | **TESTS ONLY** (referenced only in `tests/test_indodax_no_idle_loop.py`) | 2026-05-21 |
| [_deprecated/Decision/no_idle_script_director.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/_deprecated/Decision/no_idle_script_director.py) | 152 | Script-based no-idle director | **CONFIRMED DEAD** (moved to `Core/_deprecated/` on 2026-08-07) | 2026-06-06 |
| [script_adaptation_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/script_adaptation_engine.py) | 116 | Adapts trading scripts dynamically | **INDIRECT / SCRIPTS** (referenced in docstrings & review test) | 2026-05-19 |
| [target_board_runner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/target_board_runner.py) | 94 | Runner for target board updates | **PARTIAL** | 2026-06-06 |
| [engine_independence.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Decision/engine_independence.py) | 45 | Engine independence assertion helper | **PARTIAL** | 2026-06-06 |

### Core/Executors/ — Exchange Execution Layer

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [Indodax/indodax_executor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Executors/Indodax/indodax_executor.py) | 2427 | **Main live executor**: order placement, fill tracking, exit management, PnL accounting | **ACTIVE** | 2026-08-05 |

### Core/Exchange/ — Low-Level API Layer

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [indodax.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Exchange/indodax.py) | 368 | Indodax REST API wrapper (auth, order, balance, ticker) | **ACTIVE** | 2026-08-05 |

### Core/Treasury/ — Capital & Accounting Layer

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [capital_governor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/capital_governor.py) | 1243 | Capital governor: daily PnL, equity anchors, drawdown enforcement, deposit events | **ACTIVE** | 2026-08-05 |
| [live_truth_manager.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/live_truth_manager.py) | 290 | Fetches real Indodax balance, writes state/live_truth.json | **ACTIVE** | 2026-06-06 |
| [venue_ledger.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/venue_ledger.py) | 124 | Per-venue ledger for multi-exchange PnL tracking | **ACTIVE** | 2026-06-06 |
| [pnl_reconciliation.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/pnl_reconciliation.py) | 200 | Reconciles computed PnL vs actual exchange balance | **ACTIVE** | 2026-06-06 |
| [deposit_event_manager.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/deposit_event_manager.py) | 111 | Handles deposit-notify events from operator CLI | **ACTIVE** | 2026-07-29 |
| [accounting_truth.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/accounting_truth.py) | 133 | Source-of-truth accounting state validation | **ACTIVE** | 2026-06-06 |
| [allocation_policy.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/allocation_policy.py) | 17 | Hardcoded allocation ratio helper (`{"indodax": 0.85, "reserve": 0.15}`) | **PARTIAL / TREASURY INIT** (imported in `Core/Treasury/__init__.py` & `capital_governor.py`, static helper) | 2026-06-06 |
| [capital_commander.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/capital_commander.py) | 75 | Capital deployment commander | **PARTIAL** | 2026-06-06 |

### Core/Trading/ — Position Sizing

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [autonomous_sizing.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Trading/autonomous_sizing.py) | 202 | Determines trade budget based on capital state, risk, liquidity, and quality scores | **ACTIVE** | 2026-08-04 |

### Core/Support/ — Utilities & Infrastructure

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [ki_config.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_config.py) | 233 | **SSOT**: All constants, fee rates, feature flags, canary mode settings | **ACTIVE** | 2026-08-05 |
| [workflow_supervisor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/workflow_supervisor.py) | 559 | Orchestrates daily reset, health checks, reconciliation cycles | **ACTIVE** | 2026-07-29 |
| [telegram_throttle.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/telegram_throttle.py) | 437 | Rate-limits Telegram API calls to avoid flooding | **ACTIVE** | 2026-06-05 |
| [system_commander.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/system_commander.py) | 575 | System-level commands: restart, pause, status, reconfigure | **ACTIVE** | 2026-06-06 |
| [growth_audit.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/growth_audit.py) | 452 | Capital growth audit & metrics tracking | **ACTIVE** | 2026-06-06 |
| [money_movement_audit.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/money_movement_audit.py) | 389 | Audits all money movements (deposits, withdrawals, PnL) | **ACTIVE** | 2026-06-06 |
| [risk_truth_reconciler.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/risk_truth_reconciler.py) | 262 | Reconciles risk state vs capital governor vs live truth | **ACTIVE** | 2026-07-29 |
| [round_trip_accounting.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/round_trip_accounting.py) | 230 | Tracks round-trip trade accounting (entry → exit) | **ACTIVE** | 2026-06-02 |
| [no_trade_forensics.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/no_trade_forensics.py) | 134 | Diagnoses why no trades are happening | **ACTIVE** | 2026-06-06 |
| [runtime_mode_guard.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/runtime_mode_guard.py) | 70 | Guards runtime mode (paper vs live) assertions | **ACTIVE** | 2026-06-06 |
| [ki_vault.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_vault.py) | 82 | Loads encrypted secrets from sovereign vault | **ACTIVE** | 2026-05-13 |
| [ki_vault_cli.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_vault_cli.py) | 97 | CLI for vault operations (encrypt, decrypt, rotate) | **PARTIAL** | 2026-05-11 |
| [ki_utils.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_utils.py) | 93 | Utility helpers (timestamp, formatting, etc.) | **ACTIVE** | 2026-05-12 |
| [ki_storage.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_storage.py) | 26 | Simple JSON file read/write wrapper | **ACTIVE** | 2026-08-05 |
| [deposit_cli.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/deposit_cli.py) | 40 | CLI interface for deposit-notify command | **ACTIVE** | 2026-07-29 |
| [dynamic_config.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/dynamic_config.py) | 73 | Runtime-reloadable config from JSON files | **ACTIVE** | 2026-08-05 |
| [server_telemetry.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/server_telemetry.py) | 102 | Server hardware & systemd service telemetry (CPU, RAM, disk, services) | **ACTIVE** | 2026-06-06 |
| [server_telemetry_runner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/server_telemetry_runner.py) | 26 | Runner wrapper for telemetry | **PARTIAL** | 2026-05-20 |
| [perf.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/perf.py) | 113 | Performance measurement decorators | **PARTIAL** | 2026-05-17 |
| [populate_intelligence.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/populate_intelligence.py) | 46 | Initial intelligence state population helper | **PARTIAL** | 2026-05-11 |
| [sovereign_janitor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/sovereign_janitor.py) | 83 | Cleans up stale state files | **PARTIAL** | 2026-05-12 |
| [strategy_control_actions.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/strategy_control_actions.py) | 70 | Manual strategy control actions (pause/resume/reset) | **PARTIAL** | 2026-06-06 |
| [churn_guard.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/churn_guard.py) | 58 | Guards against excessive trade churn | **ACTIVE** | 2026-06-02 |
| [recovery_mode_policy.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/recovery_mode_policy.py) | 52 | Policy engine for recovery mode activation | **ACTIVE** | 2026-06-02 |
| [recovery_reset_plan.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/recovery_reset_plan.py) | 78 | Recovery plan after consecutive losses | **ACTIVE** | 2026-06-02 |

### Core/Notifications/ — Telegram Notifications

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [telegram_exception_notifier.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Notifications/telegram_exception_notifier.py) | 161 | Sends exception stack traces to operator via Telegram | **ACTIVE** | 2026-06-06 |

### Core/Security/

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [kibot_security.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Security/kibot_security.py) | 174 | Security hardening, input validation, API key protection | **PARTIAL** | 2026-05-11 |
| [_deprecated/Security/kibot_sentinel.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/_deprecated/Security/kibot_sentinel.py) | 92 | Sentinel monitoring for unauthorized access attempts | **CONFIRMED DEAD** (moved to `Core/_deprecated/` on 2026-08-07) | 2026-05-11 |

### Core/Research/ — Backtesting (Offline)

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [backtest_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Research/backtest_engine.py) | 240 | Offline backtesting engine for strategy evaluation | **TESTS ONLY** (referenced by `walk_forward.py` and unit tests) | 2026-05-18 |
| [walk_forward.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Research/walk_forward.py) | 201 | Walk-forward optimization framework | **TESTS ONLY** (referenced by `test_walk_forward.py`) | 2026-05-18 |

### Core/Runtime/

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [_deprecated/Runtime/server_telemetry.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/_deprecated/Runtime/server_telemetry.py) | 68 | Legacy server telemetry | **CONFIRMED DEAD** (moved to `Core/_deprecated/` on 2026-08-07) | 2026-05-20 |

### Core Root — Top-Level Modules

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [ki_brain.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/ki_brain.py) | 2392 | Telegram bot command handler (/status, /doctor, /profit, etc.) | **ACTIVE** | 2026-08-05 |
| [sovereign_council.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/sovereign_council.py) | 1840 | Council-of-advisors pattern for trade approval (multiple evaluators) | **ACTIVE** | 2026-06-06 |
| [sovereign_notifier.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/sovereign_notifier.py) | 278 | Telegram notification sender (trade alerts, daily reports) | **ACTIVE** | 2026-06-06 |
| [sovereign_state.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/sovereign_state.py) | 242 | Loads/saves sovereign state (strategy config, urgency flags) | **ACTIVE** | 2026-08-05 |
| [risk_gate.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/risk_gate.py) | 395 | RiskGate: notional checks, daily drawdown cap, venue validation | **ACTIVE** | 2026-08-06 |
| [sovereign_disk_cleaner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/sovereign_disk_cleaner.py) | 545 | Disk space cleanup for log/state file rotation | **PARTIAL** | 2026-05-12 |
| [circuit_breaker.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/circuit_breaker.py) | 66 | Circuit breaker for cascading failure prevention | **ACTIVE** | 2026-05-11 |

### Entrypoint & Operator Tools

| File | Lines | Function | Status | Last Modified |
|------|-------|----------|--------|---------------|
| [MasterNode.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/MasterNode.py) | 929 | **Main entrypoint**: bootstraps all subsystems, runs async loop | **ACTIVE** | 2026-08-05 |
| [bin/kibotctl](file:///Users/kiki/Documents/Web%20Develop/KiBot/bin/kibotctl) | 462 | Operator CLI: status, doctor, restart, deposit-notify, model sync | **ACTIVE** | 2026-08-05 |

---

## 3. Priority Audit Backlog

Files with **>300 lines**, status **ACTIVE**, and **NOT YET fully audited** in previous sessions:

| Priority | File | Lines | Reason |
|----------|------|-------|--------|
| **P1** | [sovereign_council.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/sovereign_council.py) | 1840 | Council-of-advisors logic never fully audited; core approval path |
| **P1** | [ki_brain.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/ki_brain.py) | 2392 | Telegram command handler; large codebase, potential stale commands |
| **P1** | [indodax_executor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Executors/Indodax/indodax_executor.py) | 2427 | Partially audited (fee refactored), but exit/reconciliation paths not reviewed |
| **P1** | [capital_governor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Treasury/capital_governor.py) | 1243 | Partially audited (equity anchor fix), but full reconciliation logic not reviewed |
| **P2** | [kibot_dashboard.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_dashboard.py) | 2121 | Dashboard rendering; reads from many state files, potential stale references |
| **P2** | [kibot_ai_coordinator.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_coordinator.py) | 1511 | LLM coordination logic; depends on Ollama which may not be running |
| **P2** | [ki_indodax_smallcap_scanner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/ki_indodax_smallcap_scanner.py) | 771 | Fallback scanner; 771 lines never reviewed |
| **P2** | [indodax_binance_leadlag_scanner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Scanner/indodax_binance_leadlag_scanner.py) | 711 | Embedded in MarketScanner, 711 lines never reviewed |
| **P2** | [kibot_learning_engine.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_learning_engine.py) | 700 | Partially audited (fee constants), but learning logic not fully reviewed |
| **P3** | [kibot_ai_scout.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/kibot_ai_scout.py) | 672 | AI scout; depends on Ollama |
| **P3** | [order_tracker.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Intelligence/order_tracker.py) | 635 | Phase 5 state machine; not audited |
| **P3** | [system_commander.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/system_commander.py) | 575 | System commands; not audited |
| **P3** | [workflow_supervisor.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/workflow_supervisor.py) | 559 | Workflow orchestrator; partially known from reconciliation context |
| **P3** | [sovereign_disk_cleaner.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/sovereign_disk_cleaner.py) | 545 | Disk cleaner; not audited |
| **P3** | [MasterNode.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/MasterNode.py) | 929 | Entrypoint; partially known but bootstrap/scheduling logic not fully reviewed |

---

## 4. Known Issues / Recently Fixed

### Critical Fixes Applied (August 2026)

| # | Issue | Root Cause | Fix | Commit | Impact |
|---|-------|-----------|-----|--------|--------|
| 1 | **Scanner Exchange Field Missing** | `IndodaxMarketScanner.__init__()` lacked `self.exchange = "INDODAX"`, causing all 177+ candidates/cycle to be tagged `"UNKNOWN"` and silently discarded by `engine.py._scan_one()` | Added `self.exchange = "INDODAX"` in `__init__` | `198b4ef` | IndodaxMarketScanner candidates now reach Council (was 0% → now 99.6% of all signals) |
| 2 | **Fee Overestimate (1.02% → 0.61%)** | `indodax_executor.py`, `exit_plan.py`, `pre_trade_simulator.py` used hardcoded 1.02% fee (2× overestimate of actual 0.61% taker roundtrip) | Unified all fee references to `KiConfig` SSOT with verified Indodax official rates | `7a1087b` | Breakeven calculations now accurate; EV gate no longer rejects profitable trades |
| 3 | **LEADLAG_ALPHA Metadata Unknown** | LEADLAG_ALPHA candidates lacked microstructure fields (`spread_pct`, `volume_ratio`, `daily_volatility_pct`), causing signal_quality to grade them all as REJECT | Implemented `_IndodaxSummariesFetcher` with 10s TTL cache in `signal_quality.py` for real-time enrichment | `ed8d01f` | LEADLAG_ALPHA candidates can now be properly graded instead of blanket REJECT |
| 4 | **Paper Trade TP/SL Deadlock** | With correct 0.61% fee, old TP=+3.0%/SL=-1.0% params yielded net R:R=1.34, below MIN_NET_RR_BUFFER=1.60, blocking ALL new paper trades | Recalibrated defaults to TP=+3.5%/SL=-1.0% → net R:R=1.63 ≥ 1.60 | `3b5796d` | Paper trades can open again with fee-accurate parameters |
| 5 | **18 Bare-Except Statements** | 9 files had bare `except:` catching SystemExit/KeyboardInterrupt | Replaced all 18 with explicit exception types | `f458588` | Clean exception handling across codebase |
| 6 | **RiskGate Hardcoded 1.02 Fee Fallback** | `risk_gate.py` line 261 used hardcoded `1.02` fallback when signal dictionary omitted `fee_roundtrip_pct` | Refactored fallback to `KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT * 100.0` (0.61%) | Local edit | Aligned RiskGate fee fallback with KiConfig SSOT |

### Previously Identified Issues (July 2026)

| # | Issue | Root Cause | Fix | Status |
|---|-------|-----------|-----|--------|
| 7 | **EV Gate Permanently Dead** | `collect_signals()` returned `[]` instead of actual signals from `detect_pump()` | Fixed to return `self.detected_signals` | Fixed (prior session) |
| 8 | **Equity Anchor Stale** | Capital governor equity anchor not refreshing on new day boundary | Fixed stale-date check logic in capital_governor.py | Fixed (prior session) |

### Architectural Observations (Not Bugs, For Awareness)

| # | Observation | Notes |
|---|------------|-------|
| A | LEADLAG_ALPHA covers only 4 pairs (BTC/ETH/SOL/XRP); by design it is a momentum confirmation supplement, not the primary signal source | IndodaxMarketScanner is the primary source (180+ pairs, 99.6% of signals) |
| B | Confirmed duplicate: `Core/Intelligence/strategy/deadline_profit_enforcer.py` (108 lines) vs `Core/Decision/deadline_profit_enforcer.py` (224 lines) | Confirmed `Core/Decision/` is the active production version; `Core/Intelligence/` version is dead |
| C | Confirmed duplicate: `Core/Runtime/server_telemetry.py` (68 lines) vs `Core/Support/server_telemetry.py` (102 lines) | Confirmed `Core/Support/` is the active production version; `Core/Runtime/` version is dead |
| D | `kibot_sentinel.py` and `no_idle_script_director.py` are confirmed dead (0 references across repo) | Retained for safety; candidate for cleanup |

---

## 5. Key Constants & SSOT

All canonical values live in [Core/Support/ki_config.py](file:///Users/kiki/Documents/Web%20Develop/KiBot/Core/Support/ki_config.py):

### Fee Constants (Indodax Official IDR Market)
| Constant | Value | Source |
|----------|-------|--------|
| `INDODAX_TAKER_BUY_FEE_PCT` | 0.0031 (0.31%) | [Indodax Detailed Fees](https://help.indodax.com/hc/en-us/articles/4416646599705) |
| `INDODAX_TAKER_SELL_FEE_PCT` | 0.0030 (0.30%) | Same |
| `INDODAX_MAKER_BUY_FEE_PCT` | 0.0021 (0.21%) | Same |
| `INDODAX_MAKER_SELL_FEE_PCT` | 0.0020 (0.20%) | Same |
| `KIBOT_TAKER_FEE_ROUNDTRIP_PCT` | 0.0061 (0.61%) | Buy + Sell taker |
| `KIBOT_MAKER_FEE_ROUNDTRIP_PCT` | 0.0041 (0.41%) | Buy + Sell maker |
| `KIBOT_DEFAULT_SLIPPAGE_PCT` | 0.0010 (0.10%) | Estimated |

### Scoring Thresholds
| Constant | Value | Location |
|----------|-------|----------|
| `APPROVE_THRESHOLD` | 0.62 | strategy_scorecard.py |
| `PAPER_THRESHOLD` | 0.42 | strategy_scorecard.py |
| `MIN_RR_RATIO` | 1.50 | expected_value.py |
| `MIN_NET_RR_BUFFER` | 1.60 | paper_trade_tracker.py |
| `MIN_SAMPLE_SIZE` | 20 | strategy_stats.py (graduation) |

### Safety Gates
| Gate | Value | Location |
|------|-------|----------|
| `min_order_notional_idr` | Rp 10,000 | risk_gate.py |
| `KIBOT_MIN_TRADE_IDR` | Rp 10,000 | autonomous_sizing.py |
| `MAX_DAILY_LOSS_PERCENT` | 1.5% | ki_config.py |
| `CANARY_MAX_DAILY_LOSS_IDR` | Per config | ki_config.py |

### Paper Trade Defaults
| Parameter | Value | Location |
|-----------|-------|----------|
| Default TP | +3.5% | paper_trade_tracker.py |
| Default SL | -1.0% | paper_trade_tracker.py |
| Default Roundtrip Fee | 0.61% | paper_trade_tracker.py via KiConfig |
| Max Hold | 7200s (2h) | paper_trade_tracker.py |
| Net R:R with defaults | 1.63 | Computed |

---

## File Statistics Summary

| Category | Files | Total Lines | ACTIVE | PARTIAL / FEATURE / STUB | CONFIRMED DEAD / TESTS / INDIRECT |
|----------|-------|-------------|--------|--------------------------|-----------------------------------|
| Core/Scanner/ | 9 | 2,941 | 4 | 4 | 1 |
| Core/Intelligence/ | 28 | 10,206 | 20 | 5 | 3 |
| Core/Decision/ | 13 | 2,535 | 7 | 3 | 3 |
| Core/Executors/ | 1 | 2,427 | 1 | 0 | 0 |
| Core/Exchange/ | 1 | 368 | 1 | 0 | 0 |
| Core/Treasury/ | 8 | 2,213 | 6 | 2 | 0 |
| Core/Trading/ | 1 | 202 | 1 | 0 | 0 |
| Core/Support/ | 24 | 3,996 | 17 | 7 | 0 |
| Core/Notifications/ | 1 | 161 | 1 | 0 | 0 |
| Core/Security/ | 2 | 266 | 0 | 1 | 1 |
| Core/Research/ | 2 | 441 | 0 | 0 | 2 |
| Core/Runtime/ | 1 | 68 | 0 | 0 | 1 |
| Core Root | 6 | 5,573 | 5 | 1 | 0 |
| Entrypoint+Tools | 2 | 1,391 | 2 | 0 | 0 |
| **TOTAL** | **99** | **32,788** | **65** | **23** | **11** |
