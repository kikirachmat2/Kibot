# 🧠 [Module] AI Orchestration (Intelligence Fleet)

This module is the "Brain" of KiBot. It transforms raw data into actionable trade signals through a redundant fleet of AI agents.

## Core Agents

### 1. `kibot_ai_coordinator.py` (The Admiral)
- **Role**: Manages 25+ AI providers (Groq, Gemini, DeepSeek, etc).
- **V9.1 Update**: Enhanced rate-limit handling and async provider switching.

### 2. `kibot_ollama_gateway.py` (The Local Shield)
- **Role**: Jumps to local **DeepSeek-Coder-V2** when internet/API limits fail.
- **Privacy**: Ensures sensitive trading configurations stay local during code-healing.

### 3. `kibot_ai_scout.py` (The Hunter)
- **Role**: 5-minute global research loops. Focuses on Indodax premiums and Polymarket sentiment.

### 4. `kibot_ai_search.py` (The Librarian)
- **Unified Retrieval**: Integrates Jina AI, Brave Search, and CryptoPanic for a unified market truth.

### 5. `Dify` workflow bridge
- **Role**: Optional decision-engine layer for Batam strategy and ops prompts.
- **Setup**: `SERVER_BATAM/Support/dify_bypass_setup.py` can check Dify reachability, configure the local Ollama provider, and invoke a workflow endpoint when `DIFY_API_KEY` and `DIFY_WORKFLOW_ID` are set.

## Integration: KiBot Manager & Trinity Mesh
The AI fleet is tightly integrated into the `kibot_manager.py` operational daemon. 
- **Scout Loop**: `kibot_ai_scout.py` is now run as a persistent background thread within the `kibot_manager.py` daemon, eliminating the need for standalone systemd services for scouting and ensuring tight integration with manager logic.
- **Search Support**: Added `duckduckgo-search` to expand open-web retrieval capabilities in `kibot_ai_search.py`.
- **Reasoning Upgrade**: The Local Shield now supports Chain of Thought (CoT) reasoning via Ollama (`KIBOT_OLLAMA_THINK_LEVEL=true`) for deep market and security research.
- **Trinity Monitor**: The entire fleet's operational health and connectivity to Scanner and Executor nodes are overseen by `trinity_monitor.py` running natively as `kibot-monitor.service`.

## Integration: Trinity Healer
The AI fleet is directly hooked into `trinity_healer.py`. When a crash is detected, the **Admiral** assigns a local LLM to diagnose and patch the source code automatically.

## State Management
- `world_model.json`: Persistent intelligence matrix.
- `ai_search_cache.json`: Optimized search results to reduce API costs.
