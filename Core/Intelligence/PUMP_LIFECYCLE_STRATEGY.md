# KiBot Sovereign Pump Lifecycle Strategy
> Status: LOCKED by operator agreement
> Purpose: strategic contract for Council, Scanner, Risk Gate, Executor, and dashboard docs.

This document defines KiBot's preferred trading intelligence path for Indodax pump-riding and fallback profit seeking. It does not promise daily profit. It defines how the system should maximize probability, protect realized green PnL, and avoid repeating low-quality pump traps.

---

## 1. Core Objective

KiBot's daily objective is **GREEN**, not a fixed numeric target.

- If daily PnL is red, the system should seek only high-quality recovery opportunities.
- If daily PnL is flat, the system may probe carefully and wait for clean setups.
- If daily PnL is green, the system should protect green first and only continue trading when the remaining edge is clearly strong.
- If a position is strongly trending while green, the system may stay in it with trailing protection instead of exiting too early.

The system must be brave enough to act, but never blind enough to buy a coin just because it is already up.

---

## 2. Pump Lifecycle Model

Every candidate coin should be classified into one lifecycle stage before a buy mandate can be considered.

| Stage | Meaning | Default Action |
|---|---|---|
| IGNITION | Early volume/price expansion with enough liquidity | Best entry zone if confirmed |
| CONFIRMATION | Pump validated by volume, bid depth, and clean structure | Normal entry zone |
| RIDE | Pump already moving but still has momentum and exit liquidity | Smaller entry, tighter trailing |
| DISTRIBUTION | Sellers absorbing buyers, spread widening, bid support weakening | Reject or exit |
| TRAP | Tick trap, flat-history spike, thin orderbook, hard to resell | Hard reject |

The system should prefer `IGNITION` and `CONFIRMATION`, allow controlled `RIDE`, and reject `DISTRIBUTION`/`TRAP`.

---

## 3. Mandatory Buy Preconditions

A coin may only be bought when all of these pass:

1. **Exit Simulation Passes**
   - The planned position must be sellable above Indodax minimum order rules.
   - Orderbook depth must be enough to exit with acceptable slippage.
   - Spread must not be too wide for the expected profit window.

2. **Anti-Buy-Top Passes**
   - Reject if 24h change is high but momentum is already weakening.
   - Reject if the last move is mostly one thin tick jump.
   - Reject if chart history is mostly flat with one artificial spike.
   - Reject if price increment is too large relative to price.

3. **Liquidity Passes**
   - Bid-side support must be strong enough for exit.
   - 24h volume must be real enough, not just a tiny illiquid print.
   - Open orderbook must not be dominated by sellers immediately above current price.

4. **Council Confidence Passes**
   - Hunter sees upside.
   - Risk Officer sees survivable downside.
   - Exit Planner confirms a realistic exit path.
   - Antagonist fails to prove the setup is a trap.
   - Allocator assigns a size that can be exited cleanly.

---

## 4. Entry Sizing Rules

KiBot must not hardcode a single nominal buy amount.

Position size should be chosen by:

- available IDR cash,
- Indodax minimum order rules,
- exit liquidity,
- current daily PnL color,
- lifecycle stage,
- pair reputation,
- expected slippage,
- number of open positions.

Recommended sizing behavior:

| Daily State | Setup Quality | Sizing |
|---|---|---|
| RED | Only exceptional setups | Small recovery size |
| FLAT | Clean setup | Normal probe size |
| GREEN | Strong setup only | Smaller continuation size unless already in winning position |
| GREEN near midnight | Very selective | Protect-first sizing |

For tiny accounts, the system must avoid dust positions that cannot be sold cleanly.

---

## 5. Exit Strategy

Every entry must create an exit plan at the moment of buy.

Required fields:

- `hard_stop_pct`
- `breakeven_after_pct`
- `partial_take_profit_pct`
- `partial_take_profit_fraction`
- `trailing_profit_schedule`
- `max_hold_minutes`
- `distribution_exit_rules`

Recommended behavior:

- After price covers fees plus buffer, move stop toward breakeven.
- At first meaningful profit, partially take profit to secure green.
- Let the remainder ride only while momentum, volume, and bid depth remain healthy.
- Tighten trailing when daily state is already green or deadline is near.
- Exit immediately when distribution risk becomes high.

---

## 6. Trailing Profit Logic

Trailing must adapt to pump strength.

Example policy:

| Unrealized Profit | Action |
|---|---|
| Below fee buffer | Normal hard stop |
| Above fee buffer | Move stop to breakeven zone |
| +1.2% to +2.0% | Enable tight trailing |
| +2.0% to +4.0% | Partial TP may trigger |
| +4.0% to +8.0% | Trail wider if momentum remains strong |
| Above +8.0% | Protect aggressively while allowing final runner |

The goal is not to exit every small green instantly. The goal is to prevent a green day from turning red while still allowing strong pumps to run.

---

## 7. Non-Pump Fallback Strategy

If no high-quality pump exists, KiBot should switch to **Controlled Green Builder Mode**.

This mode searches for lower-volatility opportunities with cleaner structure:

- reclaim of short-term support,
- tight spread,
- reliable volume,
- known liquid pair,
- positive micro-momentum,
- orderbook with stable bids,
- low probability of tick-trap behavior.

Controlled Green Builder entries should be smaller, slower, and easier to exit than pump entries.

Allowed fallback types:

1. **Liquidity Scalps**
   - Take small, high-probability moves on liquid IDR pairs.
   - Require very clean spread and orderbook.

2. **Support Reclaim**
   - Buy when price recovers a short-term level with volume confirmation.
   - Hard stop below reclaimed area.

3. **Momentum Continuation**
   - Buy when trend is steady, not explosive.
   - Use tighter position sizing and trailing.

4. **Learning Probe**
   - Very small trade only if the system needs data and risk is tightly bounded.
   - Disabled when daily state is green near deadline unless edge is strong.

Fallback mode must stay ready to switch back to pump mode immediately when a better pump candidate appears.

---

## 8. Pump Switchback Rules

When in Controlled Green Builder Mode, the system must keep scanning for pump candidates.

Switch back to Pump Lifecycle Mode when:

- a candidate reaches `IGNITION` or `CONFIRMATION`,
- exit simulation passes,
- liquidity is better than current fallback position,
- expected value is higher after slippage and fees,
- current fallback position can be exited safely or held without blocking capital.

If capital is already deployed, the Council must compare:

- expected remaining value of current position,
- opportunity cost of missing the pump,
- exit cost of current position,
- risk of entering the pump late.

---

## 9. Daily Green Protection

The daily state should influence aggressiveness:

### RED
- Recovery allowed, but only with strict quality gates.
- Avoid revenge trading.
- Prefer setups with clean exit liquidity.

### FLAT
- Normal hunting.
- Pump entries allowed if lifecycle and exit simulation pass.
- Fallback green-builder entries allowed.

### GREEN
- Protect-first mode.
- New entries require higher confidence.
- Existing winners may keep running with trailing stop.
- Partial TP becomes more important.

### GREEN + Deadline Near
- No low-quality new entries.
- Tighten trailing.
- Prefer securing realized green.
- Only take a new trade if the edge is exceptional and exit is obvious.

---

## 10. Deadline Discipline

The midnight WIB deadline is a pressure clock, not an excuse to force bad trades.

Rules:

- Deadline awareness must always be visible to Council and dashboard.
- As midnight approaches, the system must become more selective if already green.
- If still red, it may hunt recovery, but cannot bypass hard stop, exit simulation, or anti-trap rules.
- If no acceptable trade exists, the system should report why it did not force a trade.
- A forced bad trade is worse than a disciplined no-trade day.

The system's duty is to pursue green aggressively within rules, not to manufacture fake activity.

---

## 11. Deadline Intelligence Layer

Deadline awareness must be embedded into the intelligence pipeline, not treated as a passive dashboard timer.

Every major decision path should receive a shared `daily_context` payload:

```json
{
  "wib_time": "HH:MM",
  "minutes_to_midnight": 0,
  "daily_color": "RED | FLAT | GREEN",
  "realized_pnl_idr": 0,
  "unrealized_pnl_idr": 0,
  "combined_equity_idr": 0,
  "available_cash_idr": 0,
  "current_positions": [],
  "market_regime": "BULLISH | NEUTRAL | BEARISH | MIXED",
  "urgency_level": "LOW | NORMAL | HIGH | CRITICAL",
  "allowed_risk_mode": "WAIT | PROBE | NORMAL | RECOVERY | PROTECT",
  "required_trade_quality": "NORMAL | HIGH | EXCEPTIONAL",
  "exit_strictness": "NORMAL | TIGHT | LOCK_GREEN"
}
```

This context must influence:

- scanner scoring,
- Council deliberation,
- antagonist review,
- allocator sizing,
- risk gate permission,
- executor exit plan,
- trailing stop strictness,
- what-if ranking,
- Telegram reporting,
- dashboard state.

### 11.1 Time-Based Behavior

| WIB Window | Behavior |
|---|---|
| Morning / early day | Patient hunting; wait for clean setups |
| Midday / afternoon | Normal pump and green-builder search |
| Evening | Prefer setups that can resolve faster |
| Near midnight | Protect green first; recovery only on very clean edge |

### 11.2 Daily Color + Deadline Matrix

| Daily State | Time Pressure | Required Behavior |
|---|---|---|
| RED | Low | Search recovery, but do not revenge trade |
| RED | High | Only take exceptional recovery with clean exit |
| FLAT | Low | Hunt best setup patiently |
| FLAT | High | Use controlled green-builder if no pump exists |
| GREEN | Low | Continue strong winners with trailing protection |
| GREEN | High | Lock green, tighten trailing, reject weak new trades |

### 11.3 Deadline Must Not Create Panic

Deadline is a thinking pressure, not a panic trigger.

The system must not:

- bypass hard stop,
- bypass anti-trap checks,
- buy unsellable dust,
- open low-quality trades purely for activity,
- average down a bad position without a valid recovery edge,
- turn a green day red because of overtrading.

The system must:

- keep searching,
- keep evaluating alternatives,
- explain no-trade decisions,
- protect realized green,
- escalate only when edge quality supports it.

### 11.4 Agent Responsibilities Under Deadline

Each Council role must interpret the same deadline context differently:

- **Hunter**: find the best remaining opportunity before deadline.
- **Risk Officer**: prevent forced bad trades.
- **Exit Planner**: ensure the trade can resolve within the available time.
- **Antagonist**: argue whether deadline pressure is biasing the system into a trap.
- **Allocator**: reduce size as uncertainty or deadline pressure increases.
- **Deadline Keeper**: decide whether the current mode should be `PROBE`, `RECOVERY`, or `PROTECT`.

The final decision should explicitly include the deadline reason:

```json
{
  "decision_state": "ENTER | WAIT | EXIT",
  "deadline_mode": "PATIENT | ACTIVE | URGENT | LOCK_GREEN",
  "reason": "why this action is appropriate for the remaining WIB day"
}
```

---

## 12. Pair Memory

Each pair should build a reputation score from:

- realized PnL,
- slippage,
- successful exits,
- failed exits,
- dust/minimum-order problems,
- trap detections,
- repeated flat-history spikes,
- pump continuation success.

Pairs with repeated trap behavior should require higher confidence or be temporarily blocked.

Pairs with clean pump history and easy exits can receive a confidence bonus.

---

## 12.1 Long-Horizon Coin Track Record

Pair Memory is not enough by itself. KiBot must also understand the broader market history of a coin before buying it.

For each candidate pair, the Historian role should build a long-horizon track record when data is available:

- how long the coin has traded,
- whether the pair spends most of its time flat,
- historical pump frequency,
- historical pump size,
- historical pump continuation after first breakout,
- average retracement after pump,
- whether old pumps usually return to the same price range,
- whether liquidity disappears after spikes,
- whether the pair has long dead periods,
- whether the coin has external exchange/global market relevance,
- whether recent movement is unusual compared to its own history.

Example question:

```text
Before buying PEPE/IDR, has PEPE historically produced real continuation,
or is this pair mostly stuck and only making tiny local spikes?
```

### 12.1.1 Required Long-Horizon Features

The system should prefer a structured coin profile:

```json
{
  "pair": "pepe_idr",
  "lookback_days": 365,
  "available_history_days": 0,
  "flatness_score": 0.0,
  "pump_frequency_score": 0.0,
  "pump_continuation_score": 0.0,
  "retracement_risk_score": 0.0,
  "liquidity_decay_score": 0.0,
  "global_relevance_score": 0.0,
  "local_indodax_quality_score": 0.0,
  "historian_verdict": "GOOD | MIXED | DEAD | TRAP_PRONE | UNKNOWN",
  "summary": "short reason"
}
```

### 12.1.2 Data Sources

Long-horizon track record should use the best available sources:

- Indodax OHLC/history for local IDR behavior,
- Indodax 24h ticker and volume history snapshots,
- CoinGecko/CoinMarketCap-style public history when available,
- exchange/global pair history from external APIs,
- local KiBot pair memory,
- Council decision history,
- online search evidence for catalysts and historical relevance.

If only short Indodax history is available, the system must mark the profile as `UNKNOWN` or `LOCAL_ONLY`, not pretend it knows five years of behavior.

### 12.1.3 How Track Record Affects Decisions

Long-horizon history should adjust confidence:

| Track Record | Effect |
|---|---|
| Clean repeated pump continuation | Confidence bonus |
| Pump then full retracement pattern | Confidence penalty |
| Long dead/flat history | Reject or require exceptional live evidence |
| High liquidity but volatile | Allow with stricter trailing |
| Low liquidity and tick-trap history | Hard reject |
| Unknown history | Smaller size and higher evidence requirement |

The system may still buy a historically weak coin only if live evidence is exceptional and exit simulation is clean.

### 12.1.4 Historian Must Separate Two Memories

KiBot must separate:

1. **KiBot Memory**
   - What happened when KiBot traded or rejected this pair.

2. **Market Memory**
   - What the coin/pair has historically done before KiBot touched it.

Both should feed the Council, but they answer different questions.

KiBot Memory asks:

```text
Have we personally been good at trading this pair?
```

Market Memory asks:

```text
Is this coin structurally worth trading at all?
```

---

## 12.2 Local-Only Pump Handling

Some Indodax pumps may be local-only events: the coin may not have strong global confirmation, but local price, volume, and orderbook behavior may still create a short-lived opportunity.

Example:

```text
GXC/IDR pumps +100% locally with fast chart expansion and sudden volume.
```

The system must not reject all local-only pumps automatically. It must classify them as high-risk, short-window opportunities.

### 12.2.1 Local Pump Classification

Local-only pump candidates should be classified separately:

| Class | Meaning | Default Behavior |
|---|---|---|
| LOCAL_IGNITION | Local volume and price just started expanding | Allow small entry if exit liquidity is clean |
| LOCAL_CONFIRMATION | Local pump persists with bid depth and repeated trades | Allow controlled entry |
| LOCAL_BLOWOFF | Price already vertical, spread widening, sellers emerging | Avoid new entry, monitor only |
| LOCAL_TRAP | One-tick jump, weak depth, no continuation, hard to resell | Hard reject |

### 12.2.2 Local Pump Buy Requirements

A local-only pump may be bought only when:

- local orderbook has enough bid depth for the planned exit,
- spread is acceptable for the expected scalp window,
- repeated trades confirm movement, not just one print,
- candle structure shows continuation, not a single wick,
- price is not blocked by large sell walls immediately above,
- minimum sellable size is satisfied,
- the position can be exited quickly if momentum fails,
- daily state and deadline allow the risk.

### 12.2.3 Local Pump Risk Rules

Local-only pumps require stricter execution:

- smaller size than globally confirmed pumps,
- faster breakeven lock,
- tighter initial hard stop,
- earlier partial take profit,
- shorter max hold time,
- stronger distribution exit trigger,
- no averaging down unless a new clean confirmation appears.

Recommended default behavior:

```text
local-only pump = scalp / ride short window,
not long conviction hold.
```

### 12.2.4 When Local Pump Can Override Weak Long-Horizon History

A coin with weak or unknown long-term track record may still be traded if live local evidence is exceptional.

Required override conditions:

- lifecycle is `LOCAL_IGNITION` or `LOCAL_CONFIRMATION`,
- exit simulation passes cleanly,
- bid depth is strong enough,
- spread is not abusive,
- live momentum is repeated across multiple checks,
- no tick-trap or flat-history rejection,
- allocation is reduced,
- exit plan is aggressive.

If any of these fail, the system should not treat the +100% headline as edge.

### 12.2.5 Local Pump Council Question

Before buying a local-only pump, Council must answer:

```text
Is this a tradable short-window local imbalance,
or are we becoming exit liquidity for someone else?
```

The Antagonist and Liquidity Engineer have veto power on this scenario.

---

## 13. Council Roles

Council should not think in one direction. It should maintain internal disagreement.

Required roles:

- **Hunter**: finds upside and momentum.
- **Risk Officer**: identifies loss paths.
- **Exit Planner**: validates whether the position can be sold cleanly.
- **Antagonist**: argues why the trade is a trap.
- **Allocator**: chooses position size.
- **Deadline Keeper**: adjusts aggressiveness based on WIB deadline and daily color.

A buy mandate should only happen when the disagreement process still leaves a positive edge.

---

## 13.1 Final Council Role Map

The long-term Council should include the following roles.

| Role | Core Question | Main Responsibility |
|---|---|---|
| Hunter | Where is the upside? | Finds momentum, pump continuation, reclaim, and high-edge opportunity |
| Risk Officer | What can go wrong? | Blocks bad downside, revenge trading, overexposure, and weak setups |
| Liquidity Engineer | Can we exit cleanly? | Checks spread, bid depth, min order, tick size, slippage, and dust risk |
| Exit Planner | How do we get out? | Builds hard stop, breakeven, partial TP, trailing, and max-hold plan |
| Antagonist | Why is this a trap? | Challenges optimistic assumptions and detects fake pumps |
| Historian | What does memory say? | Reads pair reputation, prior traps, prior slippage, and KiBot outcomes |
| Regime Analyst | What is the market climate? | Checks BTC/global regime, Indodax-wide breadth, sector/news context |
| Deadline Keeper | What does the WIB day require? | Adjusts urgency, risk mode, and green-protection based on daily context |
| Allocator | How much should we risk? | Chooses size based on cash, sellability, edge, daily color, and open slots |
| Auditor / Judge | Is the final decision coherent? | Verifies all gates, votes, exit plan, sizing, and rule compliance before order |

### 13.2 Fast Council vs Deep Council

To keep the system responsive without becoming shallow, Council should run in two modes.

#### Fast Council

Used for first-pass filtering and frequent scanner loops:

- Hunter
- Risk Officer
- Liquidity Engineer
- Deadline Keeper

Fast Council should answer:

```text
Is this candidate even worth deep thinking?
```

#### Deep Council

Used before any real-money buy mandate:

- Exit Planner
- Antagonist
- Historian
- Regime Analyst
- Allocator
- Auditor / Judge

Deep Council should answer:

```text
Given all available context, should KiBot enter, wait, or reject?
```

The final buy decision should only be emitted after Deep Council has produced:

- lifecycle verdict,
- exit feasibility,
- trap risk,
- memory/reputation score,
- deadline mode,
- allocation size,
- final audit pass/fail.

### 13.3 Ollama Model Binding Plan

Model binding should balance speed, reasoning depth, and server capacity.

The server should keep small local models for continuous loops and reserve larger/deeper models for final decisions or complex what-if checks.

| Role | Preferred Model Class | Recommended Local Model | Notes |
|---|---|---|---|
| Hunter | Fast market pattern model | `qwen2.5:1.5b` or `qwen2.5:3b` | Needs fast ranking, not long prose |
| Risk Officer | Careful but fast reasoning | `qwen2.5:3b` | Should be stricter than Hunter |
| Liquidity Engineer | Deterministic + small model | deterministic code + `qwen2.5:1.5b` | Most checks should be code-first |
| Exit Planner | Structured reasoning | `qwen2.5:3b` | Converts signal into exit plan |
| Antagonist | Strong adversarial reasoning | `deepseek-r1:7b` if disk/RAM allows, fallback `qwen2.5:3b` | Best candidate for deeper model |
| Historian | Retrieval + concise reasoning | deterministic memory + `qwen2.5:1.5b` | Should read local pair memory/RAG |
| Regime Analyst | Summarizer + evidence ranker | `llama3.2:3b` or `qwen2.5:3b` | Good for news/search/regime synthesis |
| Deadline Keeper | Deterministic + small model | deterministic code + `qwen2.5:1.5b` | Time/color rules should be code-first |
| Allocator | Deterministic risk sizing | deterministic code + `qwen2.5:1.5b` | Sizing must be auditable |
| Auditor / Judge | Final structured reasoning | `qwen2.5:3b`, optional `deepseek-r1:7b` for disputed cases | Must output machine-readable verdict |

### 13.4 Model Installation Priority

If disk allows, install/preserve models in this priority order:

1. `qwen2.5:1.5b` — always-on fast agent work.
2. `qwen2.5:3b` — default Council reasoning and exit planning.
3. `llama3.2:3b` — regime/news/sentiment synthesis.
4. `deepseek-r1:7b` — antagonist, disputed trades, and deeper what-if.

Current principle:

- Code handles deterministic safety and exchange math.
- Small models handle fast role summaries.
- Larger models are used sparingly for ambiguous, high-impact decisions.
- No model may override hard rules: sellability, hard stop, deadline protection, or live-trading gate.

### 13.5 Fallback Behavior

If a preferred model is unavailable:

- Fall back to `qwen2.5:1.5b` for fast roles.
- Fall back to deterministic rules for Liquidity Engineer, Deadline Keeper, and Allocator.
- If Auditor / Judge cannot run, default to `WAIT`, not `ENTER`.
- If Antagonist cannot run, raise required confidence before buy.

---

## 14. Implementation Contract

Future code changes should map this strategy into:

- scanner fields for lifecycle, exit liquidity, anti-top risk, and pair quality,
- Council scoring that combines pump and fallback modes,
- executor exit plans stored per trade,
- dynamic hard stop and trailing logic,
- partial TP support,
- pair memory state,
- shared deadline intelligence context,
- deadline-aware risk mode and exit strictness,
- dashboard visibility for lifecycle, reason, deadline, and daily color.

This document is the strategic north star for KiBot's pump and fallback trading behavior.

---

## 15. Intelligence Upgrade Direction

KiBot should evolve from a signal-following trading bot into a situational autonomous investment system.

The target intelligence flow is:

```text
daily brain context
  -> scanner candidates
  -> pair memory and reputation
  -> what-if simulation
  -> Council debate
  -> allocator sizing
  -> executor with exit plan
  -> live reconciliation
  -> learning memory update
```

### 15.1 Situational Brain Layer

All agents must share one current reality:

- WIB time and deadline pressure,
- daily color,
- realized and unrealized PnL,
- available cash,
- active positions,
- market regime,
- server health,
- current risk mode,
- whether the day requires `HUNT`, `RECOVERY`, `PROTECT`, or `LOCK_GREEN`.

Without this shared context, each subsystem may optimize for a different mission. With this context, Council, scanner, executor, risk gate, dashboard, and Telegram speak the same language.

### 15.2 Decision Memory

KiBot must remember decisions, not only outcomes.

Every accepted or rejected signal should record:

- candidate pair,
- lifecycle stage,
- confidence,
- score breakdown,
- spread,
- orderbook state,
- exit simulation result,
- web/news evidence if used,
- Council role votes,
- final decision,
- result after trade or rejection.

Rejected signals are as important as executed trades because they teach the system what it avoided.

### 15.3 What-If Engine As Mandatory Pre-Trade Intelligence

What-if should become a required gate before any real order:

- What happens if price drops one tick?
- What happens if spread widens?
- Can the position be sold above minimum order rules?
- Is exit depth enough for planned size?
- What if another better pump appears?
- What if the system is already green?
- What if deadline is near?

The executor should not receive a buy mandate without a concrete exit-aware scenario.

### 15.4 Execution Intelligence

Executor intelligence must include:

- adaptive sizing,
- partial take profit,
- dynamic hard stop,
- dynamic trailing stop,
- breakeven protection after fees,
- pending order lifecycle,
- dust prevention,
- live wallet reconciliation,
- emergency exit handling.

Good Council decisions are useless if execution cannot enter and exit cleanly.

### 15.5 Market Intelligence Layer

External information should improve confidence, not replace market structure.

Useful sources:

- Indodax live ticker/orderbook,
- pair history,
- volume leaderboard,
- news/search evidence,
- global crypto regime,
- Polymarket markets,
- pair reputation,
- previous KiBot outcomes.

Web evidence should be treated as supporting context, not as a standalone buy trigger.

### 15.5.1 Online Evidence Layer

KiBot should not merely have online tools installed. It should route, score, cache, and explain online evidence before the Council uses it.

Target flow:

```text
candidate pair
  -> evidence router
  -> source fetch
  -> evidence scoring
  -> evidence packet
  -> Council debate
  -> confidence adjustment
```

#### Evidence Router

The router decides which sources are worth querying for the current candidate and situation.

| Source | Preferred Use |
|---|---|
| Indodax | Source of truth for ticker, orderbook, volume, pair rules |
| Polymarket | Event/sentiment context and cross-market probability clues |
| Tavily | Deep search for catalysts and broader context |
| Serper | Google-style confirmation and alternative SERP coverage |
| DuckDuckGo | Free fallback search |
| Jina | Clean page extraction / semantic scraping |
| Finnhub | Institutional-style market/news context |
| GDELT | Global news/event context |
| Local RAG | KiBot rules, prior decisions, and operating knowledge |
| Pair Memory | Local historical KiBot behavior for the specific pair |

#### Evidence Scoring

Every external evidence item should be scored before it can affect confidence:

- recency,
- relevance to the pair,
- source reliability,
- bullish/bearish direction,
- catalyst strength,
- conflict with market structure,
- whether it confirms or contradicts the pump thesis.

Evidence should produce a structured packet:

```json
{
  "pair": "coin_idr",
  "sources_checked": [],
  "bullish_evidence": [],
  "bearish_evidence": [],
  "conflicts": [],
  "source_health": {},
  "confidence_delta": 0.0,
  "summary": "short explanation for Council"
}
```

#### Anti-Hallucination Rule

Online evidence must never be the only reason to buy.

A buy still requires:

- valid price action,
- enough volume,
- acceptable spread,
- exit simulation pass,
- lifecycle stage pass,
- risk gate pass.

Online evidence may raise or lower confidence, but it cannot override deterministic safety rules.

#### Source Health

The system should track online source health:

- active,
- rate-limited,
- invalid key,
- timeout,
- stale,
- disabled,
- fallback used.

When a source fails, the system should use fallback sources and record the failure. It should not spam Telegram unless the failure materially degrades trading intelligence and cannot be self-recovered.

#### Cache and Throttle

Online search must be cached and throttled:

- global market regime cache,
- per-pair evidence cache,
- source failure cooldown,
- no-repeat queries for the same pair inside short windows,
- longer cache when market is quiet,
- shorter cache during active pump candidates.

This keeps decisions fast, avoids rate limits, and prevents noisy/expensive evidence collection.

### 15.6 Self-Maintenance Intelligence

Full autonomy requires the system to monitor itself:

- services,
- ports,
- disk,
- RAM,
- CPU,
- Ollama,
- Redis,
- provider failures,
- Telegram delivery,
- stale dashboard data,
- scanner/executor heartbeat.

Recoverable problems should be fixed automatically. Only unrecoverable problems should alert the operator.

---

## 16. Next Intelligence Contracts

The following upgrades complete the strategic direction of KiBot as a situational autonomous trading system.

These are not optional cosmetic features. They are intelligence contracts that should eventually become runtime modules, state files, dashboards, and Council inputs.

---

## 16.1 Capital State Machine

KiBot must understand capital condition before choosing size, slot count, and risk mode.

Capital states:

| State | Meaning | Behavior |
|---|---|---|
| MICRO | Very small balance; minimum order rules dominate | Avoid dust, one clean position at a time, strict sellability |
| SMALL | Limited balance; each mistake matters | Low slot count, smaller probes, avoid illiquid pairs |
| NORMAL | Enough balance for multiple controlled positions | Standard sizing and diversification |
| LARGE | More capital than immediate pump liquidity | Stronger liquidity simulation, avoid moving the market |

Capital state should consider:

- IDR cash,
- total equity,
- active positions,
- pending orders,
- sellable amount per holding,
- minimum base order,
- minimum coin amount,
- current daily color,
- current deadline mode.

Target payload:

```json
{
  "capital_state": "MICRO | SMALL | NORMAL | LARGE",
  "cash_idr": 0,
  "equity_idr": 0,
  "active_slots": 0,
  "max_allowed_slots": 0,
  "dust_positions": [],
  "pending_orders": [],
  "sizing_mode": "ONE_SHOT | PROBE | NORMAL | REDUCED | PROTECT"
}
```

Rule:

```text
Capital state must override greed. A tiny account cannot trade like a large account.
```

---

## 16.2 Order Lifecycle Intelligence

KiBot must separate order submission from confirmed execution.

Order lifecycle states:

| State | Meaning |
|---|---|
| CREATED | Decision emitted but no exchange order yet |
| SUBMITTED | Order sent to exchange |
| ACCEPTED | Exchange accepted order |
| PARTIAL_FILL | Some quantity filled |
| FILLED | Wallet/open-order state confirms fill |
| STALE | Order not filled within expected time |
| CANCEL_REQUESTED | Cancel submitted |
| CANCELLED | Exchange confirms cancel |
| RECONCILED | Wallet state matches KiBot state |
| FAILED | Exchange rejected or state cannot be verified |

Rules:

- Never assume `ACCEPTED` means `FILLED`.
- Wallet balance delta and/or open-order state must confirm fills.
- Pending orders must be visible to Council and dashboard.
- Stale orders should trigger cancel/reprice logic.
- Exit orders must not remove active trade until fill is verified.

Target state:

```json
{
  "order_id": "string",
  "pair": "coin_idr",
  "side": "buy | sell",
  "state": "SUBMITTED",
  "price": 0,
  "amount": 0,
  "created_at": 0,
  "last_checked_at": 0,
  "fill_confirmed": false,
  "wallet_delta_confirmed": false,
  "reason": "entry | partial_tp | trailing_exit | hard_stop"
}
```

---

## 16.3 Missed Opportunity Learning

KiBot must learn from rejected or skipped coins.

A rejected signal should be tracked after rejection:

- max gain after reject,
- max drawdown after reject,
- time to pump,
- whether rejection reason was valid,
- whether liquidity improved later,
- whether risk gate was too strict,
- whether scanner was too early/late.

Target state:

```json
{
  "pair": "coin_idr",
  "rejected_at": 0,
  "reject_reason": "spread_too_wide",
  "reject_confidence": 0.0,
  "price_at_reject": 0,
  "max_gain_after_reject_pct": 0.0,
  "max_drawdown_after_reject_pct": 0.0,
  "review_after_minutes": 30,
  "verdict": "GOOD_REJECT | FALSE_NEGATIVE | STILL_RISKY | UNKNOWN"
}
```

Rule:

```text
Risk gates must learn from false negatives, not only false positives.
```

---

## 16.4 False Positive / False Negative Review

Every trading day should classify decision quality:

- **True Positive**: bought and profit followed.
- **False Positive**: bought and became trap/loss.
- **True Negative**: rejected and avoided loss.
- **False Negative**: rejected and missed valid pump.

This review should update:

- scanner thresholds,
- pair memory,
- Council confidence calibration,
- risk gate strictness,
- local pump handling.

Target daily review:

```json
{
  "date_wib": "YYYY-MM-DD",
  "true_positive": [],
  "false_positive": [],
  "true_negative": [],
  "false_negative": [],
  "threshold_adjustments": [],
  "lessons": []
}
```

---

## 16.5 Market Breadth / Indodax Heatmap

Regime Analyst must understand Indodax-wide behavior, not just one pair.

Required heatmap features:

- number of green IDR pairs,
- number of red IDR pairs,
- number of pairs above +5%, +10%, +20%,
- total IDR market turnover,
- top volume movers,
- top price movers,
- pump cluster by sector/theme if known,
- whether volume is broad or isolated,
- BTC/IDR direction,
- large-cap vs small-cap participation.

Target payload:

```json
{
  "green_pairs": 0,
  "red_pairs": 0,
  "pump_count_5pct": 0,
  "pump_count_10pct": 0,
  "pump_count_20pct": 0,
  "top_movers": [],
  "top_volume": [],
  "market_breadth": "BROAD_RISK_ON | SELECTIVE | ISOLATED_PUMP | RISK_OFF",
  "summary": "short regime reason"
}
```

Rule:

```text
An isolated pump requires stricter liquidity checks than a broad pump regime.
```

---

## 16.6 Opportunity Ranking

If multiple candidates appear, KiBot must rank them instead of taking the first signal.

Ranking factors:

- lifecycle stage,
- expected edge after fees,
- exit quality,
- spread,
- bid depth,
- volume persistence,
- local/global confirmation,
- pair memory,
- long-horizon track record,
- deadline fit,
- daily color fit,
- capital fit,
- conflict with existing positions.

Target ranking:

```json
{
  "rank": 1,
  "pair": "coin_idr",
  "opportunity_score": 0.0,
  "entry_quality": "A | B | C | D | F",
  "exit_quality": "A | B | C | D | F",
  "reason": "why this outranks others"
}
```

Rule:

```text
Best candidate wins. First candidate does not.
```

---

## 16.7 Position Replacement Logic

When capital is already deployed and a better opportunity appears, Council must decide whether to hold, exit, partially exit, or rotate.

Replacement analysis should compare:

- expected remaining value of current position,
- current unrealized PnL,
- exit cost/slippage,
- new opportunity score,
- deadline mode,
- daily color,
- capital locked,
- risk of entering new pump late.

Possible actions:

| Action | Meaning |
|---|---|
| HOLD_CURRENT | Existing position remains better |
| PARTIAL_ROTATE | Take partial profit/loss and enter better candidate |
| FULL_ROTATE | Exit current and switch |
| SKIP_NEW | New opportunity not worth disruption |
| EMERGENCY_EXIT | Current position became dangerous regardless of replacement |

Rule:

```text
Rotation must increase expected value after exit costs, not just chase a shinier pump.
```

---

## 16.8 Confidence Explainability

Confidence must not be a magic number.

Every decision should include a score breakdown:

```json
{
  "confidence": 0.78,
  "breakdown": {
    "volume_spike": 0.18,
    "lifecycle_stage": 0.14,
    "orderbook_depth": 0.12,
    "spread_quality": 0.08,
    "track_record": 0.06,
    "deadline_fit": 0.05,
    "online_evidence": 0.04,
    "trap_penalty": -0.09,
    "liquidity_penalty": -0.04
  },
  "summary": "why the system is or is not brave enough"
}
```

Rules:

- Dashboard should show the top positive and negative reasons.
- Telegram midnight report should summarize major confidence drivers.
- Auditor / Judge should reject decisions with missing score explanation.

---

## 16.9 Trade Grade System

Each opportunity should receive a grade.

| Grade | Meaning | Trading Permission |
|---|---|---|
| A | Clean high-quality edge | Normal entry allowed |
| B | Good but not perfect | Controlled entry allowed |
| C | Probe only | Small size only |
| D | Weak setup | Reject for live trading |
| F | Trap / invalid | Hard reject |

Grades should combine:

- opportunity score,
- exit quality,
- lifecycle,
- pair memory,
- track record,
- deadline fit,
- capital fit.

Rule:

```text
Live trading should normally require A or B. C is only for controlled probes. D/F never enter.
```

---

## 16.10 Human-Readable Daily Postmortem

Midnight Telegram report should explain the day, not only report balance.

Required sections:

- starting equity,
- ending equity,
- realized PnL,
- unrealized PnL,
- daily color,
- trades taken,
- trades rejected,
- best missed opportunity,
- worst avoided trap,
- strongest Council reason,
- weakest system behavior,
- lessons learned,
- recommended mode for tomorrow.

Target output style:

```text
KiBot Daily Report — YYYY-MM-DD WIB
State: GREEN
Equity: Rp X -> Rp Y
Realized: Rp Z
Best trade: ...
Missed opportunity: ...
Lesson: ...
Tomorrow posture: CONTROLLED_AGGRESSIVE / PROTECT / RECOVERY
```

Telegram remains scarce. This report should be once per day unless critical failure requires escalation.

---

## 16.11 Polymarket-Specific Strategy

Polymarket must not be treated like Indodax.

Polymarket intelligence should evaluate:

- event probability,
- odds mispricing,
- market liquidity,
- spread,
- expiry date,
- catalyst calendar,
- resolution risk,
- position size,
- yes/no side asymmetry,
- time decay,
- exit before resolution,
- cross-check with news/search evidence.

Possible Polymarket modes:

| Mode | Meaning |
|---|---|
| EVENT_MISPRICE | Odds appear wrong vs evidence |
| CATALYST_RIDE | Expected catalyst may move odds |
| LIQUIDITY_WAIT | Thesis good but market too illiquid |
| EXPIRY_RISK | Too close/unclear resolution |
| NO_EDGE | No position |

Rule:

```text
Polymarket trades require event reasoning, not chart pump reasoning.
```

---

## 16.12 Emergency Protocol

System autonomy requires clear degraded modes.

Health states:

| State | Meaning | Behavior |
|---|---|---|
| NORMAL | Everything healthy | Full operation |
| DEGRADED | Some source/provider issue | Continue with guardrails |
| SAFE_MODE | Trading intelligence compromised | No new entries, manage exits |
| HUMAN_REQUIRED | Cannot self-recover safely | Alert operator |

Triggers:

- Indodax API error,
- order stuck,
- executor cannot sell,
- stale price feed,
- Redis down,
- Ollama down,
- disk critical,
- dashboard stale,
- Telegram failing,
- scanner heartbeat missing,
- risk state corrupted.

Rule:

```text
If entry intelligence is degraded, stop new entries. If exit intelligence works, continue managing existing positions.
```

---

## 16.13 Model Disagreement Policy

Council disagreement must have deterministic resolution rules.

Veto powers:

- Liquidity Engineer vetoes unsellable setups.
- Auditor / Judge vetoes rule violations.
- Antagonist vetoes high trap-risk setups.
- Deadline Keeper vetoes weak new entries during `LOCK_GREEN`.
- Risk Officer vetoes position size that can break daily protection.

Decision policy:

| Condition | Result |
|---|---|
| Hard rule violated | WAIT / REJECT |
| Liquidity veto | REJECT |
| Auditor missing or failed | WAIT |
| Antagonist unavailable | Raise confidence threshold |
| Roles disagree but no veto | Reduce size or probe only |
| Strong agreement + clean exit | ENTER allowed |

Rule:

```text
AI disagreement should reduce risk, not disappear into a vague average.
```

---

## 16.14 Data Freshness Rule

Every decision must know whether its data is fresh enough.

Freshness targets:

| Data | Max Age |
|---|---|
| Balance before order | 5 seconds |
| Orderbook for pump entry | 10 seconds |
| Ticker for pump entry | 10 seconds |
| Scanner candidate | 30 seconds |
| World model | 60 minutes |
| Online catalyst evidence | 30 minutes |
| Pair memory | Long-lived |
| Long-horizon track record | Daily refresh |
| Risk state | 10 seconds before order |

Rule:

```text
Stale critical data means WAIT, not ENTER.
```

---

## 16.15 Shadow Backtest / Replay

KiBot should be able to replay recent decisions.

Replay should answer:

- If current strategy ran yesterday, what would happen?
- Which rejected candidates became winners?
- Which accepted trades were false positives?
- Would tighter trailing have protected more PnL?
- Would looser risk gate have captured missed pump?
- Which rule caused the biggest opportunity cost?

Replay modes:

| Mode | Purpose |
|---|---|
| DAILY_REPLAY | Review the last WIB day |
| SIGNAL_REPLAY | Replay rejected/accepted candidates |
| EXIT_REPLAY | Test alternate trailing/TP behavior |
| RISK_GATE_REPLAY | Compare strict vs adaptive gates |

Rule:

```text
Strategy upgrades should be informed by replay, not vibes alone.
```

---

## 17. Scanner Upgrade Contract

The scanner must evolve from a basic pump detector into an opportunity intelligence collector.

Current direction:

```text
all market pairs
  -> heatmap
  -> lifecycle classification
  -> liquidity / exit feasibility
  -> historian profile
  -> opportunity ranking
  -> Council evidence packet
```

### 17.1 Required Scanner Capabilities

The scanner should eventually provide:

- market-wide Indodax heatmap,
- pump lifecycle classification,
- local-only pump classification,
- non-pump green-builder candidate detection,
- long-horizon coin track record,
- pair memory integration,
- liquidity and exit feasibility score,
- data freshness markers,
- opportunity ranking,
- confidence breakdown,
- missed opportunity tracking.

### 17.2 Lifecycle Output

Every candidate should expose:

```json
{
  "pair": "coin_idr",
  "lifecycle": "IGNITION | CONFIRMATION | RIDE | DISTRIBUTION | TRAP | LOCAL_IGNITION | LOCAL_CONFIRMATION | LOCAL_BLOWOFF | LOCAL_TRAP",
  "opportunity_score": 0.0,
  "entry_quality": "A | B | C | D | F",
  "exit_quality": "A | B | C | D | F",
  "confidence_breakdown": {},
  "market_quality": {},
  "historian_profile": {},
  "freshness": {}
}
```

### 17.3 Scanner Must Be Exit-Aware

Scanner should not only ask:

```text
Can this coin go up?
```

It must also ask:

```text
If KiBot buys now, can KiBot exit cleanly?
```

This includes:

- spread,
- bid depth,
- sell walls,
- expected slippage,
- minimum sellable amount,
- tick-size trap risk,
- stale orderbook risk.

### 17.4 Scanner Must Support Green-Builder Mode

If no high-quality pump exists, scanner should search for:

- liquidity scalps,
- support reclaim,
- steady momentum,
- controlled learning probes.

These candidates should be clearly tagged as fallback mode, not mixed with pump signals.

### 17.5 Scanner Must Learn From Misses

Rejected candidates should be tracked after rejection so the scanner can learn:

- which gates were too strict,
- which rejection reasons were valid,
- which false negatives became strong pumps,
- which local-only pumps deserved earlier attention.

Scanner learning should tune future candidate scoring, not silently rewrite hard safety rules.

---

## 18. Executor Upgrade Contract

The executor must evolve from an order sender into an execution intelligence and position risk manager.

Target flow:

```text
audited mandate
  -> fresh balance/orderbook validation
  -> sellability validation
  -> execution style selection
  -> order submission
  -> fill confirmation
  -> position state with exit plan
  -> live monitoring
  -> partial TP / trailing / hard stop / distribution exit
  -> wallet reconciliation
  -> PnL attribution
  -> learning update
```

### 18.1 Mandate Validation

Executor should only accept audited mandates.

Required mandate fields:

- pair,
- side,
- intended size,
- lifecycle stage,
- trade grade,
- confidence breakdown,
- deadline mode,
- capital state,
- exit plan,
- Council approval,
- Auditor / Judge pass,
- freshness proof.

If any critical field is missing, executor should default to `WAIT`, not guess.

### 18.2 Fresh Pre-Order Checks

Immediately before order submission, executor must refresh:

- balance,
- ticker,
- orderbook,
- pair rules,
- risk state,
- active positions,
- open orders.

Rules:

- stale balance means no entry,
- stale orderbook means no entry,
- unsellable planned amount means no entry,
- minimum order violation means no entry,
- existing pending order conflict means no entry.

### 18.3 Execution Style Selection

Executor should choose execution style based on liquidity and urgency:

| Style | Use Case |
|---|---|
| PASSIVE_LIMIT | Non-urgent entry with tight spread |
| AGGRESSIVE_LIMIT | Pump entry where missing fill is costly but market order is risky |
| SPLIT_ORDER | Larger capital where one order would move price |
| CANCEL_REPRICE | Order stale but thesis still valid |
| NO_TRADE | Fill quality would be too poor |

For tiny accounts, executor should avoid complex splitting unless required by liquidity or minimum-order rules.

### 18.4 Fill Confirmation

Executor must never assume accepted order equals filled order.

Fill confirmation should use:

- wallet balance delta,
- open order status,
- trade history if available,
- reconciled amount,
- timestamp and order id.

Entry should create an active position only after fill is verified or clearly marked as pending.

Exit should remove or reduce a position only after fill is verified.

### 18.5 Position State With Exit Plan

Every position must include an exit plan from the moment it is created.

Target position state:

```json
{
  "pair": "coin_idr",
  "entry_price": 0,
  "entry_amount": 0,
  "entry_value_idr": 0,
  "entry_fee_estimate_idr": 0,
  "entry_reason": "LOCAL_CONFIRMATION",
  "entry_grade": "A | B | C",
  "deadline_mode": "PATIENT | ACTIVE | URGENT | LOCK_GREEN",
  "capital_state": "MICRO | SMALL | NORMAL | LARGE",
  "hard_stop_price": 0,
  "breakeven_price": 0,
  "partial_tp_done": false,
  "partial_tp_price": 0,
  "partial_tp_fraction": 0.0,
  "trailing_active": false,
  "trail_stop_price": 0,
  "max_hold_minutes": 0,
  "distribution_exit_rules": {},
  "pnl_unrealized_idr": 0,
  "pnl_unrealized_pct": 0,
  "current_exit_reason": "HOLD"
}
```

### 18.6 Partial Take Profit

Partial take profit is required for green protection.

Rules:

- Trigger partial TP when profit exceeds fee buffer and target threshold.
- Partial TP should be earlier for local-only pumps.
- Partial TP should be more aggressive near midnight if daily state is green.
- Remaining runner should keep a trailing stop.
- Partial TP must respect minimum sellable amount.

If partial sell would create unsellable dust, executor should either skip partial TP or exit fully depending on exit plan.

### 18.7 Dynamic Hard Stop and Trailing

Stops must adapt to context.

Inputs:

- lifecycle stage,
- local/global pump classification,
- volatility,
- spread,
- bid depth,
- unrealized profit,
- daily color,
- deadline mode,
- position age,
- market breadth.

Behavior:

- local-only pump: tighter initial stop and faster breakeven,
- high-quality broad pump: allow wider runner trail,
- green day near deadline: tighter trailing and profit protection,
- red day recovery: avoid oversized loss and no revenge averaging,
- weak liquidity: exit earlier.

### 18.8 Distribution Exit

Executor must exit when structure deteriorates, even before hard stop.

Distribution triggers:

- bid depth collapses,
- spread widens beyond plan,
- sell wall appears near price,
- volume dries up,
- price loses local support,
- momentum flips,
- orderbook imbalance turns sell-side,
- candidate lifecycle degrades to `DISTRIBUTION`, `LOCAL_BLOWOFF`, or `TRAP`.

This prevents the system from waiting for a price-only stop when liquidity has already disappeared.

### 18.9 Order Replacement and Stale Orders

Pending orders must be managed actively.

Actions:

- wait,
- cancel,
- reprice,
- reduce size,
- convert to more aggressive limit,
- abandon trade,
- emergency exit if already exposed.

Rules:

- stale entry order should not remain forever,
- stale exit order should escalate faster,
- if thesis changes while order is pending, cancel first,
- never stack duplicate orders without explicit plan.

### 18.10 Capital-Aware Execution

Executor must respect account size.

For MICRO/SMALL capital:

- avoid dust,
- avoid too many tiny slots,
- prefer one clean position,
- avoid partial TP if it creates unsellable remnants,
- confirm exit path before entry,
- do not use nominal fixed buys blindly.

For NORMAL/LARGE capital:

- simulate slippage more strictly,
- split orders if required,
- avoid moving local orderbook,
- diversify only when quality supports it.

### 18.11 Position Replacement Execution

When Council chooses rotation, executor must safely perform it.

Supported actions:

- hold current,
- partial rotate,
- full rotate,
- skip new opportunity,
- emergency exit.

Rules:

- do not rotate unless expected value improves after exit cost,
- do not sell a green runner just to chase a weaker pump,
- do not keep a bad position only because it is uncomfortable to realize loss,
- protect daily green during rotation.

### 18.12 PnL Attribution

Every trade must track:

- entry price,
- exit price,
- amount,
- gross PnL,
- fee estimate,
- slippage estimate,
- realized PnL,
- unrealized PnL,
- exit reason,
- initial trade grade,
- final outcome class,
- whether exit followed the plan.

Target result:

```json
{
  "pair": "coin_idr",
  "entry_price": 0,
  "exit_price": 0,
  "amount": 0,
  "gross_pnl_idr": 0,
  "fee_estimate_idr": 0,
  "slippage_idr": 0,
  "realized_pnl_idr": 0,
  "realized_pnl_pct": 0,
  "exit_reason": "PARTIAL_TP | TRAILING_STOP | HARD_STOP | DISTRIBUTION_EXIT | ROTATION | MANUAL",
  "outcome_class": "TRUE_POSITIVE | FALSE_POSITIVE | CONTROLLED_LOSS | UNKNOWN"
}
```

### 18.13 Safety Mode Behavior

If system intelligence is degraded:

- stop new entries,
- keep managing existing exits,
- cancel stale orders,
- protect active positions,
- alert only if self-recovery fails.

Executor must distinguish:

```text
Cannot safely enter
```

from:

```text
Cannot safely manage exits
```

The second case is more severe and may require operator escalation.

### 18.14 Execution Audit Trail

Every executor action should be explainable:

- why buy,
- why sell,
- why hold,
- why cancel,
- why partial TP,
- why trailing changed,
- why hard stop changed,
- why order was abandoned.

Executor logs should be concise but structured enough for dashboard, daily postmortem, replay, and Council learning.

---

## 19. Final Trading-System Hardening Contracts

This section finalizes the trading-system strategy after reviewing exchange API constraints and systematic trading design principles.

Core conclusion:

```text
KiBot's edge should come from candidate quality, exit-aware execution, adaptive risk, and post-trade learning.
It must not rely on AI confidence alone.
```

### 19.1 Exchange Constraint Awareness

Trading strategy must be exchange-aware.

Indodax-specific constraints:

- balances must come from authenticated `getInfo`,
- entries/exits must be reconciled with order and wallet state,
- order status must be checked through `openOrders`, `orderHistory`, or `getOrder`,
- trade history should be used for realized fill/PnL reconstruction when available,
- accepted order response is not enough to prove final fill,
- minimum order and pair rules must be checked before entry and before partial exit.

Polymarket-specific constraints:

- CLOB orders are signed and matched off-chain with settlement on Polygon,
- API credential and wallet health are part of trading readiness,
- orderbook/liquidity must be evaluated per market,
- event markets require expiry/resolution/catalyst reasoning,
- Polymarket strategy must not reuse Indodax pump logic.

Rule:

```text
Strategy must adapt to the venue. No single trading logic should blindly span Indodax and Polymarket.
```

### 19.2 Pre-Trade Simulation Gate

Before any real-money order, KiBot should simulate the trade.

The simulation must estimate:

- expected entry fill price,
- expected exit fill price,
- spread cost,
- fee cost,
- slippage,
- minimum sellable amount,
- orderbook depth required,
- worst-case one-tick loss,
- break-even price,
- required price move to reach green after fees,
- whether partial TP is feasible.

Target payload:

```json
{
  "pair": "coin_idr",
  "planned_value_idr": 0,
  "entry_price_est": 0,
  "exit_price_est": 0,
  "spread_cost_pct": 0.0,
  "fee_cost_pct": 0.0,
  "slippage_pct": 0.0,
  "breakeven_price": 0,
  "one_tick_loss_pct": 0.0,
  "min_sellable_pass": true,
  "partial_tp_feasible": true,
  "simulation_verdict": "PASS | REDUCE_SIZE | REJECT"
}
```

Rule:

```text
No simulation pass, no real entry.
```

### 19.3 Calibration Engine

Thresholds should be calibrated from outcomes, not hand-tuned forever.

Calibration inputs:

- accepted trades,
- rejected candidates,
- missed opportunity review,
- false positive review,
- false negative review,
- slippage,
- fill quality,
- trailing outcome,
- deadline mode.

Calibration outputs:

- lifecycle score weights,
- confidence floor,
- spread tolerance,
- volume spike requirement,
- local pump sizing factor,
- trailing schedule,
- partial TP threshold,
- risk gate loosen/tighten recommendation.

Rule:

```text
Calibration may recommend changes. Auditor / Judge must approve changes before runtime use.
```

### 19.4 Exploration vs Exploitation Policy

KiBot must balance learning and profit protection.

Modes:

| Mode | Meaning | Behavior |
|---|---|---|
| EXPLOIT | Known good edge | Normal size, standard controls |
| EXPLORE | Uncertain but useful data | Tiny probe only |
| PROTECT | Green day or degraded system | Avoid weak new entries |
| RECOVERY | Red day with valid setup | Small controlled recovery |

Rules:

- exploration must never violate sellability,
- exploration size must be smaller than normal,
- no exploration in `LOCK_GREEN` unless exceptional edge,
- exploration results must feed memory.

### 19.5 Portfolio Exposure Policy

Even with small capital, KiBot needs portfolio-level awareness.

Exposure should consider:

- total IDR cash at risk,
- number of open positions,
- correlated coins,
- local pump concentration,
- Polymarket event concentration,
- daily drawdown,
- deadline mode.

Rule:

```text
One strong clean position is better than many tiny unmanageable positions.
```

### 19.6 Latency and Freshness Budget

Pump trading is sensitive to stale data.

KiBot should define a latency budget:

| Step | Target |
|---|---|
| ticker/orderbook refresh | seconds |
| scanner candidate age | under 30 seconds |
| Council fast filter | seconds |
| Deep Council | bounded timeout |
| pre-trade simulation | immediately before order |
| balance refresh | immediately before order |
| order status reconcile | repeated until resolved |

Rule:

```text
If the decision takes too long, the candidate must be revalidated before execution.
```

### 19.7 Kill Switch and Resume Protocol

KiBot must have explicit stop/resume states.

Stop triggers:

- repeated failed exits,
- stale price feed,
- wallet mismatch,
- risk state corruption,
- daily loss breach,
- exchange API inconsistency,
- unresolved open order conflict,
- critical server health issue.

Resume requirements:

- wallet reconciled,
- open orders known,
- services healthy,
- risk state valid,
- dashboard not stale,
- Telegram health known,
- operator not required unless state was `HUMAN_REQUIRED`.

Rule:

```text
Safe resume is as important as safe stop.
```

### 19.8 Decision Replay as a Required Development Tool

Every future trading upgrade should be evaluated with replay when possible.

Replay should compare:

- old vs new scanner scoring,
- old vs new trailing,
- strict vs adaptive risk gate,
- buy/skip decisions,
- partial TP schedules,
- local pump classification.

Rule:

```text
Runtime changes should be promoted after evidence, not after one lucky trade.
```

### 19.9 Final Architecture Target

The final trading intelligence loop should be:

```text
daily context
  -> capital state
  -> market heatmap
  -> scanner candidates
  -> long-horizon track record
  -> online evidence packet
  -> opportunity ranking
  -> pre-trade simulation
  -> fast Council
  -> deep Council
  -> Auditor / Judge
  -> executor
  -> position manager
  -> daily postmortem
  -> calibration / replay
```

### 19.10 Final Trading Philosophy

KiBot's trading intelligence should follow this hierarchy:

1. Survive and remain operational.
2. Protect sellability and avoid dust traps.
3. Preserve daily green once achieved.
4. Take high-quality pump opportunities.
5. Use green-builder mode when no pump is clean.
6. Learn from both traded and missed opportunities.
7. Increase bravery only when evidence quality improves.

Final rule:

```text
KiBot should be aggressive in searching, selective in entering, adaptive in managing, and ruthless in exiting when the thesis breaks.
```

---

## 20. Probability, Data, and Unknown Scenario Contract

No trading strategy can cover every market possibility or guarantee daily profit.

KiBot's goal is not perfection. KiBot's goal is to continuously increase the probability of a green day through better data, better calibration, safer execution, and faster learning.

### 20.1 What-If Coverage Philosophy

The system must distinguish:

1. **Known Scenarios**
   - Conditions already modeled in code and strategy.
   - Example: spread too wide, stale orderbook, local pump, failed exit.

2. **Known Unknowns**
   - Conditions the system knows may happen but cannot fully predict.
   - Example: sudden whale dump, API degradation, catalyst reversal, spoofed orderbook.

3. **Unknown Unknowns**
   - New failure modes the system has never seen.
   - Example: unusual exchange behavior, unexpected pair rule change, novel pump pattern.

Rule:

```text
KiBot must not pretend it knows all possibilities.
It must detect anomalies, reduce risk, record evidence, and learn.
```

### 20.2 Worst-Case / Best-Case Scenario Modeling

Every high-impact candidate should include scenario analysis:

```json
{
  "best_case": {
    "expected_gain_pct": 0.0,
    "path": "pump continuation / reclaim / catalyst"
  },
  "base_case": {
    "expected_gain_pct": 0.0,
    "path": "normal expected movement"
  },
  "bad_case": {
    "expected_loss_pct": 0.0,
    "path": "failed breakout / spread widening"
  },
  "worst_case": {
    "expected_loss_pct": 0.0,
    "path": "liquidity disappears / hard stop slip"
  },
  "scenario_verdict": "FAVORABLE | MIXED | UNFAVORABLE"
}
```

The system should enter only when:

- best/base case reward is worth the risk,
- bad case is survivable,
- worst case has a defined response,
- exit path exists before entry.

### 20.3 Data Capture Requirements

KiBot must collect data from both action and inaction.

Required datasets:

- scanner candidates,
- rejected candidates,
- accepted trades,
- skipped opportunities,
- orderbook snapshots,
- ticker snapshots,
- OHLC snapshots,
- online evidence packets,
- Council role votes,
- confidence breakdowns,
- pre-trade simulations,
- order lifecycle events,
- entry/exit fills,
- wallet reconciliations,
- realized/unrealized PnL,
- daily postmortems,
- replay/calibration outputs.

Rule:

```text
No decision should vanish. Every decision is training data.
```

### 20.4 Data Quality Requirements

Bad data creates fake intelligence.

Every data record should include:

- timestamp,
- source,
- freshness age,
- pair/market id,
- confidence in source,
- whether data was complete,
- whether fallback source was used,
- whether data was stale,
- whether data was used for a real-money decision.

Critical data freshness:

- stale balance blocks entry,
- stale orderbook blocks entry,
- stale risk state blocks entry,
- stale online evidence may reduce confidence but should not block by itself,
- stale pair memory is allowed but should be marked old.

### 20.5 Probability Estimation

KiBot should estimate green-day probability, but only with humility.

Early probability estimates must be treated as weak until enough data exists.

Suggested maturity:

| Sample Size | Probability Trust |
|---|---|
| 0-10 trades | Very weak; descriptive only |
| 10-50 trades | Early directional signal |
| 50-100 trades | Usable but cautious |
| 100+ trades | Better calibration possible |

Target output:

```json
{
  "estimated_green_probability": 0.0,
  "confidence_quality": "WEAK | DEVELOPING | USABLE | STRONG",
  "positive_drivers": [],
  "negative_drivers": [],
  "sample_size": 0,
  "calibration_warning": "not enough data"
}
```

Rule:

```text
Probability estimates must include evidence quality and sample size.
```

### 20.6 Confidence Calibration

Council confidence must be tested against reality.

Questions:

- Did trades with confidence 0.80 actually win around 80% of the time?
- Did grade-A trades outperform grade-B trades?
- Did local pump confidence overestimate continuation?
- Did Antagonist vetoes prevent losses?
- Did Liquidity Engineer vetoes prevent unsellable positions?

Calibration output:

```json
{
  "confidence_bucket": "0.70-0.80",
  "sample_size": 0,
  "actual_win_rate": 0.0,
  "average_pnl_pct": 0.0,
  "calibration_error": 0.0,
  "recommended_adjustment": "raise_threshold | lower_threshold | keep"
}
```

Rule:

```text
Confidence is not probability until calibrated.
```

### 20.7 Daily Probability Drivers

Daily green probability should consider:

- market breadth,
- number of grade-A/B candidates,
- current capital state,
- current daily color,
- deadline pressure,
- active position quality,
- scanner signal quality,
- executor health,
- source health,
- recent false positive/negative rate,
- pair memory,
- available liquidity,
- Polymarket opportunity quality.

Example:

```text
Estimated green probability: 62%
Positive:
- 3 grade-B Indodax candidates
- broad pump regime
- executor healthy
Negative:
- no grade-A setup
- capital state MICRO
- deadline pressure rising
```

### 20.8 Anomaly Detection

Unknown scenarios should be handled through anomaly detection.

Anomalies include:

- price moves without matching volume,
- orderbook changes too fast,
- sudden disappearance of bid depth,
- ticker/orderbook mismatch,
- exchange response inconsistent with wallet,
- PnL mismatch between dashboard and wallet,
- repeated model/provider disagreement,
- sudden source outage during active position,
- coin behavior outside historical profile.

Default anomaly behavior:

- reduce size,
- tighten exit,
- block new entries if critical,
- record anomaly,
- alert only if self-recovery fails.

### 20.9 Profit Probability vs Profit Maximization

KiBot must distinguish:

- maximizing expected return,
- maximizing probability of green day,
- protecting capital,
- learning from exploration.

These goals can conflict.

Rule hierarchy:

1. Safety and sellability.
2. Daily green probability.
3. Expected return.
4. Exploration/learning.

This means KiBot may skip a high-upside trade if it risks turning a green day red near deadline.

### 20.10 Final Probability Principle

The strategy document is not a profit guarantee.

The document is a structure for:

- better decisions,
- fewer repeated mistakes,
- stronger recovery,
- clearer audit trails,
- smarter confidence,
- more adaptive risk.

Final rule:

```text
KiBot should never claim perfect prediction.
KiBot should continuously improve the odds and explain why each risk was worth taking or rejecting.
```

---

## 21. Telegram Daily Report Contract

Telegram is a scarce operator channel. It should provide high-signal daily intelligence, not noisy runtime spam.

Default behavior:

- one required daily report at midnight WIB,
- emergency alerts only when the system cannot self-recover,
- no repeated low-value status messages,
- dedupe and throttle all non-midnight notifications.

### 21.1 Midnight Report Purpose

The midnight report should answer:

```text
Did KiBot end the day green?
How did it get there?
What did it avoid?
What did it miss?
What did it learn?
What is tomorrow's posture?
Does the operator need to do anything?
```

### 21.2 Daily Report Template

Recommended Telegram format:

```text
KiBot Daily Report — YYYY-MM-DD WIB

STATE
Daily Color: GREEN / FLAT / RED
Start Equity: Rp ...
End Equity: Rp ...
Realized PnL: Rp ... (...%)
Unrealized PnL: Rp ... (...%)
Combined Equity: Rp ...

CAPITAL
Cash IDR: Rp ...
Coin Holdings: Rp ...
Polymarket: $... / Rp ...
Capital State: MICRO / SMALL / NORMAL / LARGE

TRADING SUMMARY
Trades Taken: ...
Wins / Losses: ...
Best Trade: PAIR +...% / Rp ...
Worst Trade: PAIR -...% / Rp ...
Open Positions: ...
Exit Quality: OK / WARNING / ISSUE

DECISION QUALITY
Grade A/B/C Candidates: ...
Rejected Candidates: ...
Best Missed Opportunity: PAIR +...% after reject
Worst Avoided Trap: PAIR reason...
False Positive Count: ...
False Negative Count: ...

INTELLIGENCE
Market Regime: BROAD_RISK_ON / SELECTIVE / ISOLATED_PUMP / RISK_OFF
Top Council Reason: ...
Top Risk Reason: ...
Deadline Mode Used: PATIENT / ACTIVE / URGENT / LOCK_GREEN
Estimated Green Probability Today: ...% (quality: WEAK / DEVELOPING / USABLE / STRONG)

LEARNING
Lesson Learned: ...
Calibration Note: ...
Pair Memory Update: ...
Tomorrow Posture: CONTROLLED_AGGRESSIVE / GREEN_BUILDER / PROTECT / RECOVERY

SYSTEM HEALTH
Services: OK / DEGRADED / SAFE_MODE / HUMAN_REQUIRED
Disk/RAM/CPU: OK / WARN / CRITICAL
Data Freshness: OK / STALE
Online Sources: OK / PARTIAL / FAILED

OPERATOR ACTION
None / Action required: ...
```

### 21.3 Report Compression Rules

The report must stay readable.

Rules:

- include only top 1-3 examples per section,
- hide noisy raw logs,
- show reasons, not stack traces,
- show exact action required only if needed,
- if no trades happened, explain why in one concise line,
- if no action is required, say `Operator Action: None`.

### 21.4 Emergency Alert Policy

Emergency Telegram alerts are allowed only when:

- system enters `HUMAN_REQUIRED`,
- executor cannot safely manage exits,
- Indodax/Polymarket wallet mismatch cannot self-recover,
- daily risk state is corrupted,
- disk/server health threatens runtime,
- Telegram daily report failed repeatedly,
- live trading gate is inconsistent with runtime state,
- open order conflict cannot be resolved.

Emergency alert template:

```text
KiBot Emergency — HUMAN_REQUIRED
Issue: ...
Impact: entry blocked / exit blocked / system degraded
Self-recovery tried: ...
Operator action needed: ...
Last safe state: ...
```

### 21.5 Non-Emergency Suppression

Do not Telegram spam for:

- ordinary scanner candidates,
- every Council WAIT,
- routine service restarts that self-recover,
- temporary provider cooldowns,
- normal market no-trade periods,
- small expected PnL fluctuations,
- repeated known warning inside cooldown window.

These should go to dashboard/event journal, not Telegram.

### 21.6 Optional Midday Digest

Optional, disabled by default unless operator enables it.

Purpose:

- summarize day progress without spam,
- useful only if the operator wants one checkpoint before midnight.

Recommended schedule:

- 12:00 WIB midday digest,
- 00:00 WIB daily final report.

Midday digest should be much shorter:

```text
KiBot Midday Snapshot
Color: ...
Equity: ...
Open Positions: ...
Best Candidate: ...
Risk Mode: ...
Action Needed: None
```

### 21.7 Report Data Sources

The daily report should be generated from structured state, not raw logs:

- daily context,
- portfolio snapshot,
- active trades,
- realized PnL state,
- order lifecycle journal,
- decision journal,
- missed opportunity tracker,
- pair memory,
- market heatmap,
- online source health,
- service health,
- replay/calibration summary.

If a source is missing, the report should say `UNKNOWN` rather than hallucinate.

### 21.8 Final Telegram Rule

Telegram should make the operator feel informed, not interrupted.

Final rule:

```text
One rich daily report beats fifty noisy alerts.
Only wake the operator when KiBot cannot safely handle the situation alone.
```

---

## 22. Dashboard Strategy Alignment Contract

The dashboard must evolve with the trading intelligence strategy.

It should not only show whether services are active. It should show whether KiBot is thinking correctly, trading safely, and learning from its decisions.

### 22.1 Dashboard Purpose

The dashboard should answer:

```text
What is KiBot trying to do right now?
Why is it waiting or entering?
What candidates exist?
What risk mode is active?
What is the daily green probability?
What positions are open and how are they protected?
Is the data fresh?
Is the system healthy?
What will be reported at midnight?
```

### 22.2 Required Top-Level Widgets

Header should include:

- daily color,
- combined equity,
- realized PnL,
- unrealized PnL,
- estimated green probability,
- deadline mode,
- capital state,
- server clock WIB,
- live trading gate state.

Recommended compact header:

```text
FLAT | Rp 85.762 | Realized Rp 0 | Unrealized Rp 0 | Green Prob 62% WEAK | ACTIVE | MICRO | Live ON
```

### 22.3 Agent Canvas Must Reflect Strategy Roles

The visual agent canvas should show the actual intelligence roles:

- Operator,
- Council Director,
- Scanner,
- AI Brain,
- Indodax Executor,
- Polymarket Executor,
- Verifier,
- Janitor,
- Hunter,
- Risk Officer,
- Liquidity Engineer,
- Exit Planner,
- Antagonist,
- Historian,
- Regime Analyst,
- Deadline Keeper,
- Allocator,
- Auditor / Judge.

Fast Council and Deep Council should be visually separated:

```text
Fast Council: Hunter + Risk Officer + Liquidity Engineer + Deadline Keeper
Deep Council: Exit Planner + Antagonist + Historian + Regime Analyst + Allocator + Auditor
```

The canvas should show status per role:

- ACTIVE,
- WAITING,
- THINKING,
- VETO,
- PASSED,
- DEGRADED,
- UNKNOWN.

### 22.4 Candidate Ranking Panel

Dashboard must expose top opportunities before they become trades.

Each candidate row should show:

- rank,
- pair,
- lifecycle,
- grade,
- opportunity score,
- exit quality,
- spread,
- volume signal,
- track record verdict,
- local/global pump tag,
- deadline fit,
- reason for enter/wait/reject.

Example:

```text
1. GXC/IDR | LOCAL_CONFIRMATION | B | score 0.81 | exit A | WAIT: spread widened
2. PEPE/IDR | RIDE | C | score 0.66 | exit B | PROBE only
3. XYZ/IDR | LOCAL_TRAP | F | REJECT: one-tick pump
```

### 22.5 Position Protection Panel

Open positions should show protection state, not only amount/value.

Required fields:

- pair,
- entry price,
- current price,
- realized/unrealized PnL,
- trade grade,
- hard stop,
- breakeven price,
- trailing active,
- trail stop,
- partial TP status,
- max hold remaining,
- exit reason if triggered,
- liquidity status.

This lets the operator see whether KiBot is protecting the day.

### 22.6 Council Vote / Reason Panel

Dashboard should show the latest role votes:

```text
Hunter: BUY, momentum strong
Risk Officer: CAUTION, spread elevated
Liquidity Engineer: PASS, exit depth enough
Antagonist: WARNING, local-only pump
Historian: MIXED, weak long history
Auditor: WAIT, need fresh orderbook
```

This is more useful than a single opaque confidence number.

### 22.7 Data Freshness and Source Health Panel

Dashboard must show whether data is fresh enough for decisions:

- balance age,
- orderbook age,
- ticker age,
- scanner age,
- world model age,
- online evidence age,
- pair memory freshness,
- source health for Tavily/Serper/DDGS/Jina/Finnhub/GDELT/Polymarket/Indodax.

If critical data is stale, dashboard should show:

```text
ENTRY BLOCKED: stale orderbook
```

### 22.8 Probability and Calibration Panel

Dashboard should display:

- estimated green probability,
- confidence quality,
- sample size,
- positive drivers,
- negative drivers,
- calibration warning,
- false positive/false negative counts.

This prevents the operator from mistaking an early weak estimate for certainty.

### 22.9 Daily Report Preview

Dashboard should preview what Telegram will send at midnight:

- current daily color,
- expected report status,
- known missing data,
- operator action status,
- whether report can be generated from structured state.

This ensures Telegram reporting is not a surprise.

### 22.10 Dashboard Anti-Noise Rule

Dashboard may show detailed events. Telegram should not.

Rule:

```text
Dashboard is for rich observability.
Telegram is for daily intelligence and emergencies.
```

### 22.11 Dashboard Final Rule

The dashboard must make KiBot's thinking visible.

Final rule:

```text
If KiBot waits, the dashboard must explain why.
If KiBot enters, the dashboard must show the evidence, risk, and exit plan.
If KiBot exits, the dashboard must show whether the exit followed the plan.
```

---

## 23. Fallback Category Intelligence and Unit Price Law

When no clean pump is available, KiBot must not become blind or idle. It should
switch into a fallback hunting mode, but still obey hard execution safety.

### 23.1 Absolute Unit Price Law

This rule is non-negotiable:

```text
For every Indodax BUY, the price of 1 full coin must be strictly below current total account balance/equity.
If price_idr >= total_equity_idr, the trade is rejected.
```

Rationale:

- The operator wants KiBot to avoid expensive unit-price assets while the account is small.
- Fractional buying may be technically possible, but it can create trapped dust, sell-minimum issues, and poor learning data.
- This rule is enforced twice: first by `RiskGate`, then by `IndodaxExecutor` immediately before order placement.

Runtime fields:

```json
{
  "unit_price_rule": {
    "must_be_below_total_equity": true,
    "basis": "total_equity_idr",
    "enforced_by": ["RiskGate", "IndodaxExecutor"]
  }
}
```

### 23.2 Fallback Category Priority

If no pump is worth riding, KiBot may search for green-builder trades in this
order:

1. `HIGH_LIQUIDITY_MAJOR` — BTC/ETH/SOL/XRP/TRX/LINK style assets with clean exit depth.
2. `BTC_ETH_BETA` — assets that historically rotate with BTC/ETH or major L1/L2 momentum.
3. `AI_BIG_DATA` — AI/data coins only when world model and web intelligence support the narrative.
4. `RWA_DEFI` — sector rotation candidates when liquidity and trend confirm.
5. `MEME_ROTATION` — meme coins only for short scalp, never passive holding.
6. `LOCAL_MOMENTUM` — Indodax-only/local movers, short window only, evidence must be strong.
7. `AVOID_STABLE` / `UNKNOWN` — do not use for alpha unless manually reclassified later.

Fallback mode is not a permission to force bad trades. It is a structured way to
keep looking for good asymmetric opportunities when the market is quiet.

### 23.3 Category-Specific Behavior

`HIGH_LIQUIDITY_MAJOR`

- Purpose: slow green-builder when no pump is clean.
- Requires: spread clean, orderbook healthy, market regime not panic.
- Holding style: may hold longer if trailing profit remains strong.

`BTC_ETH_BETA`

- Purpose: capture rotation after BTC/ETH strength.
- Requires: BTC/ETH trend alignment and fresh volume.
- Holding style: medium-short, exit if BTC/ETH weakens.

`AI_BIG_DATA`

- Purpose: narrative trade if AI sector is being validated by web/news/heatmap.
- Requires: online evidence or sector breadth.
- Holding style: do not chase if only one isolated candle.

`MEME_ROTATION`

- Purpose: ride hype only when liquidity proves it.
- Requires: high volume persistence, clean spread, exit simulation pass.
- Holding style: short scalp, trailing profit strict, no averaging down.

`LOCAL_MOMENTUM`

- Purpose: catch local exchange-specific moves like sudden GXC-style pumps.
- Requires: strong local volume, distinct price levels, healthy sell path.
- Holding style: very short. If it stalls, leave.

### 23.4 Scanner and Council Contract

Scanner must attach:

```json
{
  "fallback_category": "MEME_ROTATION",
  "category_policy": {
    "fallback_priority": 5,
    "allowed_for_green_builder": true,
    "default_mode": "short_scalp_only",
    "unit_price_must_be_below_total_equity": true
  },
  "category_score_adjustment": -0.015
}
```

Council must preserve category fields into the mandate so Executor can log the
reason and active trade state can later be audited.

### 23.5 What-If for No Pump Day

If no pump candidate passes:

1. Switch to green-builder category scan.
2. Prefer liquid majors and BTC/ETH beta.
3. Allow small probe only if exit simulation passes and unit price law passes.
4. Keep the daily objective as GREEN, not arbitrary trade count.
5. If deadline pressure is high, lower confidence only after data quality,
   exit path, and hard stop remain acceptable.

### 23.6 Anti-Dead-Coin Rule

KiBot must avoid coins whose historical behavior shows:

- repeated same-price churn,
- too few distinct price levels,
- low/no real candle diversity,
- thin orderbook,
- pump history that fails to continue,
- sell-minimum trap risk.

These are not learning opportunities. They are noisy traps.
