# KiBot Inventory Utilization Matrix

## Runtime Items
Every item should be tracked with:

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
  "utilization": "ACTIVE"
}
```

## Services
- `kibot-master`
- `kibot-scanner`
- `kibot-executor`
- `kibot-live-truth`
- `kibot-capital-governor`
- `kibot-ai-scout`
- `kibot-dashboard`
- `ollama`
- `redis-server`

## Providers and Tools
- Indodax
- Telegram
- Ollama
- Gemini/Groq/OpenRouter/Cerebras/Mistral/Cohere/Jina/NVIDIA where configured
- Tavily/Serper/DDGS/Finnhub/Brave/CryptoPanic where configured
- `gh`
- `aider`
- `copilot`
- `pipx`

## State
- `live_truth.json`
- `active_trades.json`
- `risk_state.json`
- `learning_state.json`
- `decision_journal/`
- `trade_history/`
- `market_heatmap.json`
- `green_probability.json`
- `system_commander.json`
