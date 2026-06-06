# KiBot Indodax Trading Strategy

## Objective
Trade Indodax spot only when a candidate has measurable edge after fees, spread, slippage, liquidity, and exit feasibility.

## Preferred Setups
- Liquid continuation with volume persistence.
- Pullback reclaim after healthy support test.
- Controlled breakout with orderbook confirmation.
- Liquidity scalp where exit depth is clearly sufficient.

## Avoid
- Flat-history spikes.
- One-candle pumps with weak bid depth.
- Spread above configured threshold.
- Coins that fail minimum sellable checks.
- Repeated loser pairs inside quarantine.
- Stale signals or stale orderbook.

## Required Gates
1. Runtime and wallet reconciliation are healthy.
2. EV is approved from real evidence.
3. Expected net edge remains positive after all costs.
4. Pre-trade simulator passes spread, slippage, min sellable, and exit depth checks.
5. Risk gate allows size.
6. Exit plan exists before entry.

## Exit Discipline
- Use actual entry fill for breakeven and stop calculations.
- Profit targets must exceed round-trip fee plus spread/slippage buffer.
- Trailing logic should use realistic sell-side price, not optimistic last trade.
- Stale orders must be cancelled.
- Every close must write gross PnL, fees, and net PnL.

## AI Role
AI can critique, diagnose, summarize, and suggest parameter changes. AI cannot approve trades, override gates, or increase size.
