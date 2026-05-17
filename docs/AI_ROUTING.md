# AI / Ollama Routing & Guardrail Policy

This document establishes the official routing rules, model bindings, and safety guardrails for Artificial Intelligence (specifically localized Ollama running Qwen2.5) within the KiBot trading engine.

## 1. Architectural Philosophy

To ensure absolute safety, deterministic reliability, and high-frequency execution compatibility, KiBot operates on a split-brain model:

```mermaid
graph TD
    MarketData[Market Microstructure & Lead-Lag Signals] --> Scanner[High-Frequency Scanner Loop]
    Scanner --> EVEngine[Expected Value Engine]
    EVEngine --> StrategyScorecard[Strategy Scorecard]
    
    subgraph Deterministic Core (Python Engine)
        Scanner
        EVEngine
        StrategyScorecard
        Executor[Trade Executor]
    end
    
    subgraph Advisory Layer (Localized LLM / Ollama)
        Ollama[Ollama - Qwen2.5 7B/14B]
    end
    
    StrategyScorecard -- Deterministic Score --> Executor
    Ollama -. Advisory Macro Sentiment & Post-Audit .-> StrategyScorecard
    Executor -- Execution Logs --> Ollama
```

### 1.1 The Golden Rules of KiBot AI
1. **Zero Execution Authority**: No LLM, agent, or neural model is permitted to execute trades, place orders, swap assets, trigger bridges, or authorize withdrawals.
2. **Zero Key Access**: Active API keys, private keys, seed phrases, and credential configurations MUST NEVER be exposed to or ingested by the advisory LLM.
3. **Deterministic Superiority**: The execution pathways (Expected Value Engine, Strategy Scorecard, Punishment Engine) are strictly deterministic mathematical models. Advisory scores from the LLM are heavily capped, treated as auxiliary inputs, and can be overridden by hardcoded guards at any time.

---

## 2. LLM / Ollama Routing Map

All AI integrations are routed through local endpoints only (defaulting to `http://127.0.0.1:11434` for Ollama). Under no circumstances are remote proprietary LLM APIs used in production trading loops to prevent latency spikes and privacy leaks.

### 2.1 Model Assignments & System Prompts

| Role | Target Model | Max Context | Latency Budget | Responsibility |
| :--- | :--- | :--- | :--- | :--- |
| **Market Regime Advisory** | `qwen2.5:7b-instruct` | 4,096 | < 800ms | Analyzes multi-day volatility patterns and orderbook shifts to output macro market sentiment. |
| **Strategy Post-Audit** | `qwen2.5:14b-instruct` | 8,192 | < 3,000ms | Audits past trade execution logs to identify subtle systemic slippages or execution anomalies. |

---

## 3. Strict Deterministic Guards & Fail-Closed Scenarios

AI advisory outputs are mapped to a strictly bound range `[-0.15, +0.15]` added to the deterministic strategy scoring. This ensures that even if an AI model hallucinates or outputs a maximum bullish score, it cannot override deterministic indicators showing high risk or negative expected value.

### 3.1 LLM Sanitization Pipeline

Every input vector and payload sent to local LLMs passes through the following strict filter:

1. **Secret Redaction**: Regex-based scanners inspect payload strings for private keys (`0x`, hex strings, Solana base58 keys), and Indodax/Polymarket API credentials. Any matching sequence results in an immediate fail-closed termination of the thread.
2. **Response Parsing Validation**: The AI must respond in structured JSON format matching the schema:
   ```json
   {
     "sentiment_advisory": "bullish" | "bearish" | "neutral",
     "confidence_score": 0.0,
     "rationale": "Clear string explaining rationale without executable statements"
   }
   ```
   If the JSON parser fails or the response does not adhere strictly to the schema, the confidence score defaults to `0.0` (neutral influence).

---

## 4. Compliance & Verification Logs

To verify compliance with this AI routing document:
* **Systemd Isolation**: The `kibot-scanner` service runs under systemd with restricted capability sets, preventing it from calling non-loopback network connections (except the Whitelisted Exchange endpoints).
* **Audit Command**: Run `bin/kibotctl doctor` to verify that Ollama is bound exclusively to `127.0.0.1` and that no secret keys are stored in any environment variables exposed to the Ollama process.
