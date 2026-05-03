# 🧠 [Module] AI Orchestration (Intelligence Fleet)

This module is the "Brain" of KiBot. It transforms raw internet data into actionable trade signals through a high-performance, redundant fleet of AI models.

> [!IMPORTANT]
> **HIGH-PERFORMANCE UPGRADE (May 2026)**: The system has been scaled from a simple validator to a **Multi-Agent Autonomous Fleet** with 25+ AI providers, specialized Indodax/Polymarket research, and a "Strategic Debate" engine to eliminate hallucinations.

## Key Components

### 1. [Coordinator] `kibot_ai_coordinator.py` (The Admiral)
- **Role**: Manages the rotation of 25+ AI providers to ensure zero-touch operation.
- **Providers**: Groq, Gemini, DeepSeek, Together AI, Mistral, Perplexity, Cloudflare, etc.
- **Redundancy**: If one provider hits a rate limit, the Admiral immediately swaps to the next candidate.
- **Agentic Debate**: Implements `query_ai_debate` where multiple models cross-verify trade "Theses" against "Critiques".

### 2. [Scout] `kibot_ai_scout.py` (The Hunter)
- **Role**: Continuous 5-minute global research missions.
- **Specialization**:
    - **Indodax Intel**: Dedicated mining for IDR premiums and local Indonesian listing rumors.
    - **Polymarket Intel**: Correlation of high-volume prediction shifts with crypto assets.
- **Possibility Matrix**: Generates a persistent matrix of actionable trade ideas in `world_model.json`.

### 3. [Search] `kibot_ai_search.py` (The Library)
- **Unified Retrieval**: Integrates **Jina AI**, **Brave Search**, **CryptoPanic**, and **Finnhub**.
- **Market Consensus**: Combines multiple independent search indices into a single unified truth for the AI to analyze.

## 🕵️ Celah (Gap) Audit
We have conducted a deep audit of technical and logical weaknesses.
- [celah_audit.md](file:///Users/kiki/Documents/Web Develop/KiBot/Batam/AI_Orchestration/celah_audit.md): Detailed report on latency, bias, and rate-limit fixes.

## 🚀 Deployment Status
- **Redundancy**: 25+ Provider logic implemented.
- **Validation**: Multi-agent debate active.
- **Autonomy**: Zero-touch 5-minute loop enabled.

## Why this exists?
To prevent "Rug Pulls" and "Fake Pumps." The **AI Scout** provides a critical "Veto" power over technical signals by finding real-world catalysts (or the lack thereof).
