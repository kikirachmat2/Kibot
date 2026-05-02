# KiBot AI_Orchestration Guide

Welcome to the centralized AI intelligence hub for KiBot. This folder contains all the fragmented search and research capabilities unified into a resilient, autonomous ecosystem.

## 🏰 Centralized Components

### 1. `kibot_ai_coordinator.py`
The **Sovereign Router**. It manages 20+ AI providers with an automated rotation system to ensure 24/7 uptime.
- **Auto-Rotation**: If Gemini hits a rate limit, it automatically switches to Groq, then DeepSeek, Sambanova, Cerebras, etc.
- **State Management**: Tracks quota usage and cooldowns in `Batam/Global_State/ai_coordinator_providers.json`.
- **Providers Integrated**: 
  - Ollama (Local/Gateway)
  - Groq (Ultra-fast)
  - Gemini (Deep context)
  - DeepSeek, Together, SambaNova, Cerebras, Mistral, NVIDIA, OpenRouter, DeepInfra, OctoAI, Novita, Perplexity, Cohere, Jina, HuggingFace, FriendliAI, Lepton.

### 2. `kibot_ai_search.py`
The **Research Scout**. A consolidated module for all external intelligence gathering.
- **Tavily/Serper**: High-quality AI search.
- **DuckDuckGo**: Anonymous, free web search.
- **Finnhub**: Real-time crypto news.
- **GDELT**: Global event database monitoring.
- **Caching**: All searches are cached for 15-60 minutes to save API credits.

## 🛠️ How to Add New APIs

1.  **Get the Key**: Sign up for the provider (e.g., [Sambanova](https://cloud.sambanova.ai/), [Cerebras](https://cloud.cerebras.ai/)).
2.  **Add to `.env`**: Add the key to your `.env` file (e.g., `SAMBANOVA_API_KEY=xxx`).
3.  **Update Coordinator**: The coordinator is already pre-configured for 20 providers. If the key exists in `.env`, it will automatically join the rotation.

## 📡 24/7 Autonomous Patrol

Every 5 minutes, the system performs a diagnostic check. If a provider is down (429 or 500 error), the coordinator marks it for "cooldown" and moves to the next candidate. This ensures the **Governor** never stays blind.

## 📜 Motto
> "Tekan Kerugian, Maksimalkan Probabilitas Keuntungan. Sedikit demi sedikit, lama-lama jadi bukit!" 🛡️🚀📡
