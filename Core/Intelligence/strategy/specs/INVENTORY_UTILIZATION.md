# KiBot Sovereign — Inventory Utilization Matrix

> Purpose: define how every server inventory item becomes a runtime-aware asset.

---

## Utilization Fields

Every item should eventually be tracked as:

```json
{
  "name": "kibot-master",
  "kind": "systemd_service",
  "installed": true,
  "active": true,
  "used_by": ["runtime", "council"],
  "owner_module": "MasterNode.py",
  "last_verified": "YYYY-MM-DDTHH:MM:SSZ",
  "health": "OK",
  "utilization": "ACTIVE",
  "notes": "Council supervisor"
}
```

---

## Categories

### Services

- `kibot-master`
- `kibot-scanner`
- `kibot-executor`
- `kibot-executor-polymarket`
- `kibot-ai-scout`
- `kibot-dashboard`
- `kibot-janitor`
- `ollama`
- `redis-server`

### Models

- `qwen2.5:0.5b`
- `qwen2.5:1.5b`
- `qwen2.5:3b`
- `qwen2.5-coder:3b`
- `llama3.2:3b`
- `deepseek-r1:7b`
- `mistral:7b`
- `nomic-embed-text`

### APIs and Providers

- Indodax
- Polymarket CLOB/Gamma
- Telegram
- Gemini
- Groq
- Cerebras
- Mistral
- OpenRouter
- Cohere
- NVIDIA
- Tavily
- Serper
- DDGS
- Jina
- Finnhub
- GDELT
- Brave
- CryptoPanic

### Tools

- `bin/kibotctl`
- `gh`
- `aider`
- `copilot`
- `pipx`

### State

- `active_strategy.json`
- `active_trades.json`
- `risk_state.json`
- `learning_state.json`
- `telemetry_snapshot.json`
- `decision_journal/`
- `market_heatmap.json`
- `green_probability.json`
- `system_commander.json`

---

## Health Values

`OK`

- installed, reachable, fresh, and used.

`STALE`

- exists but data is old.

`BROKEN`

- installed/configured but failing.

`UNUSED`

- exists but no runtime role is assigned.

`MISSING`

- referenced by strategy/docs but absent from server.

`UNKNOWN`

- not checked yet.

---

## Target

Inventory is optimal only when:

- every item has a runtime owner,
- every item has last verification time,
- unused items are either assigned or removed,
- missing items are either installed or removed from strategy,
- dashboard shows inventory usage.

