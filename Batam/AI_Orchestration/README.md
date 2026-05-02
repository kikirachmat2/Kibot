# [Module] AI Orchestration (Intelligence Integration)

This module bridges the gap between technical signals and real-world intelligence. It uses Large Language Models (LLMs) and specialized search engines to validate market movements.

> [!IMPORTANT]
> **INTELLIGENCE RESTORED (May 2026)**: The system was previously "blind" due to expired Tavily/Serper keys. We have discovered and integrated **Jina AI (Search)** and **Groq (Llama-3.1)** to restore real-time market research capabilities.

## Key Files

### 1. `kibot_ai_coordinator.py` (The Translator)
- **Role**: Manages multi-provider AI interactions.
- **Providers**: 
    - **Groq** (Primary for speed): `llama-3.1-8b-instant`.
    - **Gemini** (Primary for depth): `gemini-1.5-flash`.
- **Responsibilities**:
    - Defines structured prompt templates for Veto, Summary, and Validation.
    - Handles model fallback logic.

### 2. `kibot_ai_scout.py` (The Detective)
- **Role**: Autonomous news and catalyst validator.
- **Primary Tool**: **Jina AI Reader API**.
- **Responsibilities**:
    - Periodically (or on-demand) searches for "the WHY" behind price movements.
    - Validates if a pump is news-driven or purely technical.

### 3. `kibot_ai_search.py` (The Library)
- **Role**: Unified search interface.
- **Restored Engine**: **Jina AI Search**.
- **Fallback Engines**: DuckDuckGo, GDELT, Finnhub.

## Why this exists?
To prevent "Rug Pulls" and "Fake Pumps." The **AI Scout** provides a critical "Veto" power over technical signals by finding real-world catalysts (or the lack thereof).
