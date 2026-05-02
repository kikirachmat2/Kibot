# [Module] AI Orchestration (Intelligence Integration)

This module bridges the gap between technical signals and real-world intelligence. It uses Large Language Models (LLMs) and specialized search engines to validate market movements.

## Key Files

### 1. `kibot_ai_coordinator.py` (The Translator)
- **Role**: Manages multi-provider AI interactions (Gemini, OpenAI, Ollama).
- **Responsibilities**:
    - Defines structured prompt templates for different tasks (Veto, Summary, Targeted Validation).
    - Handles model fallback logic and error handling for AI requests.
- **Usage**: Used by other modules (Brain/Scout) to perform structured AI reasoning.

### 2. `kibot_ai_scout.py` (The Detective)
- **Role**: Autonomous news and catalyst validator.
- **Responsibilities**:
    - Periodically (or on-demand) searches for "the WHY" behind a price pump.
    - Uses search APIs to find specific news (e.g., "Why is $BONK pumping?").
    - Validates if a pump is "Legitimate" (News-driven) or "Fake" (Technical-only).
- **Usage**: Automatically triggered by the Manager when a high-confidence technical signal arrives.

### 3. `kibot_ai_search.py` (The Library)
- **Role**: Low-level search API wrapper.
- **Responsibilities**:
    - Integrates Tavily, Serper, Finnhub, and GDELT.
    - Provides a unified interface for fetching real-time web results.
- **Usage**: Utility module for `kibot_ai_scout.py`.

## Critical Dependency
This module relies heavily on API keys defined in the shared `.env`. Without valid keys for **Tavily** or **Gemini**, the AI remains "blind" to current events.

## Why this exists?
To prevent "Rug Pulls" and "Fake Pumps." Even if the technical charts look good, the AI Scout might find a negative news catalyst that saves the system from a bad entry.
