#!/usr/bin/env python3
from __future__ import annotations

"""
KiBot AI Coordinator
====================
Rate-limited AI router for non-trading subsystems.
"""

import hashlib
import json
import os
import time
import asyncio
import httpx
import signal
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import sys

logger = logging.getLogger("AICoordinator")


def _load_env_file(env_path: str = ".env") -> None:
    """Load .env file into os.environ if it exists."""
    env_file = Path(env_path)
    if not env_file.exists():
        return
    
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                if key and key not in os.environ:
                    os.environ[key] = value


from Core.Support.ki_vault import load_sovereign_env
from Core.Support.ki_config import *
from Core.Support.ki_utils import _env_first
from Core.Support.ki_utils import telegram_send, load_json, save_json

# Load Sovereign Environment (Decrypted)
load_sovereign_env()



from Core.Support.ki_config import STATE_DIR, PROJECT_ROOT as ROOT
RATE_STATE_FILE = STATE_DIR / "ai_coordinator_rate.json"
RESPONSE_CACHE = STATE_DIR / "ai_coordinator_cache.json"
PROVIDER_STATE_FILE = STATE_DIR / "ai_coordinator_providers.json"
REQUEST_TIMEOUT_SEC = float(os.getenv("KIBOT_AI_COORDINATOR_TIMEOUT_SEC", "12"))
OLLAMA_FAST_MODEL = os.getenv("KIBOT_OLLAMA_FAST_MODEL", "qwen2.5:0.5b")
OLLAMA_DEFAULT_MODEL = os.getenv("KIBOT_OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_PRO_MODEL = "qwen2.5:3b"            # Balanced
OLLAMA_SMART_MODEL = "llama3.2:3b"         # NLP/Sentiment
OLLAMA_DEEP_MODEL = "deepseek-r1:7b"       # Reasoning Champion
OLLAMA_BRIDGE_MODEL = "mistral:7b"         # Synthesis
OLLAMA_FAST_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_FAST_TIMEOUT_SEC", "300"))
OLLAMA_DEFAULT_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_TIMEOUT_SEC", "300"))
OLLAMA_DEEP_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_DEEP_TIMEOUT_SEC", "600"))
OLLAMA_FAST_KEEP_ALIVE = os.getenv("KIBOT_OLLAMA_FAST_KEEP_ALIVE", "45s")
OLLAMA_DEFAULT_KEEP_ALIVE = os.getenv("KIBOT_OLLAMA_KEEP_ALIVE", "90s")
OLLAMA_DEEP_KEEP_ALIVE = os.getenv("KIBOT_OLLAMA_DEEP_KEEP_ALIVE", "3m")
OLLAMA_FAST_NUM_CTX = int(os.getenv("KIBOT_OLLAMA_FAST_NUM_CTX", "2048"))
OLLAMA_DEFAULT_NUM_CTX = int(os.getenv("KIBOT_OLLAMA_DEFAULT_NUM_CTX", "3072"))
OLLAMA_DEEP_NUM_CTX = int(os.getenv("KIBOT_OLLAMA_DEEP_NUM_CTX", "4096"))
OLLAMA_FAST_NUM_PREDICT = int(os.getenv("KIBOT_OLLAMA_FAST_NUM_PREDICT", "180"))
OLLAMA_DEFAULT_NUM_PREDICT = int(os.getenv("KIBOT_OLLAMA_DEFAULT_NUM_PREDICT", "260"))
OLLAMA_DEEP_NUM_PREDICT = int(os.getenv("KIBOT_OLLAMA_DEEP_NUM_PREDICT", "520"))
AI_DEFAULT_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_DEFAULT_COOLDOWN_SEC", "900"))
AI_NETWORK_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_NETWORK_COOLDOWN_SEC", "180"))
AI_RATE_LIMIT_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_RATE_LIMIT_COOLDOWN_SEC", "3600"))
AI_EMPTY_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_EMPTY_COOLDOWN_SEC", "180"))
AI_AUTH_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_AUTH_COOLDOWN_SEC", "21600"))
AI_OLLAMA_COOLDOWN_SEC = int(os.getenv("KIBOT_AI_PROVIDER_OLLAMA_COOLDOWN_SEC", "600"))


PROVIDERS = {
    "ollama": {
        "daily_limit": 100000,
        "model": OLLAMA_DEFAULT_MODEL,
        "api_key_envs": ["OLLAMA_API_KEY", "KIBOT_OLLAMA_GATEWAY_TOKEN"],
        "base_url": OLLAMA_CHAT_URL,
        "priority": 99,
    },
    "finnhub": {
        "daily_limit": 1000,
        "model": "finnhub-news",
        "api_key_envs": ["FINNHUB_API_KEY"],
        "base_url": "https://finnhub.io/api/v1",
        "priority": 50,
    },
    "groq": {
        "daily_limit": 14400,
        "model": "llama-3.1-8b-instant",
        "api_key_envs": ["GROQ_API_KEY", "BINANCE_GROQ_API_KEY"],
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "priority": 2,
    },
    "gemini": {
        "daily_limit": 1500,
        "model": os.getenv("GEMINI_SUPPORT_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")),
        "api_key_envs": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_SUPPORT_API_KEY"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "priority": 3,
    },
    "deepseek": {
        "daily_limit": 5000,
        "model": "deepseek-chat",
        "api_key_envs": ["DEEPSEEK_API_KEY"],
        "base_url": "https://api.deepseek.com/chat/completions",
        "priority": 4,
    },
    "sambanova": {
        "daily_limit": 5000,
        "model": "Meta-Llama-3.1-8B-Instruct",
        "api_key_envs": ["SAMBANOVA_API_KEY"],
        "base_url": "https://api.sambanova.ai/v1/chat/completions",
        "priority": 5,
    },
    "cerebras": {
        "daily_limit": 50000,
        "model": "llama3.1-8b",
        "api_key_envs": ["CEREBRAS_API_KEY", "KIBOT_CEREBRAS_KEY"],
        "base_url": "https://api.cerebras.ai/v1/chat/completions",
        "priority": 1,
    },
    "together": {
        "daily_limit": 3000,
        "model": "meta-llama/Llama-3-8b-chat-hf",
        "api_key_envs": ["TOGETHER_API_KEY"],
        "base_url": "https://api.together.xyz/v1/chat/completions",
        "priority": 7,
    },
    "fireworks": {
        "daily_limit": 2000,
        "model": "accounts/fireworks/models/llama-v3-8b-instruct",
        "api_key_envs": ["FIREWORKS_API_KEY"],
        "base_url": "https://api.fireworks.ai/inference/v1/chat/completions",
        "priority": 8,
    },
    "mistral": {
        "daily_limit": 5000,
        "model": "mistral-tiny",
        "api_key_envs": ["MISTRAL_API_KEY", "KIBOT_MISTRAL_KEY"],
        "base_url": "https://api.mistral.ai/v1/chat/completions",
        "priority": 5,
    },
    "nvidia": {
        "daily_limit": 1000,
        "model": "meta/llama-3.1-70b-instruct",
        "api_key_envs": ["NVIDIA_API_KEY"],
        "base_url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "priority": 10,
    },
    "openrouter": {
        "daily_limit": 200,
        "model": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct"),
        "api_key_envs": ["OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 11,
    },
    "deepinfra": {
        "daily_limit": 500,
        "model": "meta-llama/Meta-Llama-3-8B-Instruct",
        "api_key_envs": ["DEEPINFRA_API_KEY"],
        "base_url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "priority": 12,
    },
    "octoai": {
        "daily_limit": 500,
        "model": "meta-llama-3-8b-instruct",
        "api_key_envs": ["OCTOAI_API_KEY"],
        "base_url": "https://api.octoai.cloud/v1/chat/completions",
        "priority": 13,
    },
    "novita": {
        "daily_limit": 500,
        "model": "meta-llama/llama-3-8b-instruct",
        "api_key_envs": ["NOVITA_API_KEY"],
        "base_url": "https://api.novita.ai/v3/openai/chat/completions",
        "priority": 14,
    },
    "perplexity": {
        "daily_limit": 100,
        "model": "llama-3-sonar-small-32k-online",
        "api_key_envs": ["PERPLEXITY_API_KEY"],
        "base_url": "https://api.perplexity.ai/chat/completions",
        "priority": 15,
    },
    "cohere": {
        "daily_limit": 100,
        "model": "command-a-03-2025",
        "api_key_envs": ["COHERE_API_KEY"],
        "base_url": "https://api.cohere.ai/v1/chat",
        "priority": 16,
    },
    "jina": {
        "daily_limit": 100,
        "model": "jina-embeddings-v3",
        "api_key_envs": ["JINA_API_KEY", "BINANCE_JINA_API_KEY"],
        "base_url": "https://api.jina.ai/v1/embeddings",
        "priority": 17,
    },
    "huggingface": {
        "daily_limit": 1000,
        "model": "meta-llama/Meta-Llama-3-8B-Instruct",
        "api_key_envs": ["HUGGINGFACE_API_KEY"],
        "base_url": "https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-8B-Instruct/v1/chat/completions",
        "priority": 18,
    },
    "friendliai": {
        "daily_limit": 500,
        "model": "llama-3-8b-instruct",
        "api_key_envs": ["FRIENDLIAI_API_KEY"],
        "base_url": "https://api.friendli.ai/v1/chat/completions",
        "priority": 19,
    },
    "lepton": {
        "daily_limit": 500,
        "model": "llama3-8b",
        "api_key_envs": ["LEPTON_API_KEY"],
        "base_url": "https://llama3.lepton.run/api/v1/chat/completions",
        "priority": 20,
    },
    "together_turbo": {
        "daily_limit": 3000,
        "model": "meta-llama/Llama-3-70b-chat-hf",
        "api_key_envs": ["TOGETHER_API_KEY"],
        "base_url": "https://api.together.xyz/v1/chat/completions",
        "priority": 21,
    },
    "mistral_large": {
        "daily_limit": 500,
        "model": "mistral-large-latest",
        "api_key_envs": ["MISTRAL_API_KEY"],
        "base_url": "https://api.mistral.ai/v1/chat/completions",
        "priority": 22,
    },
    "cloudflare_ai": {
        "daily_limit": 1000,
        "model": "@cf/meta/llama-3-8b-instruct",
        "api_key_envs": ["CLOUDFLARE_API_KEY", "CF_AI_TOKEN"],
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-3-8b-instruct",
        "priority": 23,
    },
    "perplexity_pro": {
        "daily_limit": 1000,
        "model": "llama-3.1-sonar-large-128k-online",
        "api_key_envs": ["PERPLEXITY_API_KEY"],
        "base_url": "https://api.perplexity.ai/chat/completions",
        "priority": 24,
    },
    "github_experimental": {
        "daily_limit": 100,
        "model": "gpt-4o",
        "api_key_envs": ["GITHUB_TOKEN"],
        "base_url": "https://models.inference.ai.azure.com/chat/completions",
        "priority": 25,
    },
    # --- OpenRouter Gateway Bypass (One Key, Multiple Models) ---
    "or_claude_free": {
        "daily_limit": 1000,
        "model": "anthropic/claude-3-haiku:free",
        "api_key_envs": ["OPENROUTER_API_KEY", "BINANCE_OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 30,
    },
    "or_gpt4o_mini_free": {
        "daily_limit": 1000,
        "model": "openai/gpt-4o-mini:free",
        "api_key_envs": ["OPENROUTER_API_KEY", "BINANCE_OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 31,
    },
    "or_llama3_1_70b_free": {
        "daily_limit": 1000,
        "model": "meta-llama/llama-3.1-70b-instruct:free",
        "api_key_envs": ["OPENROUTER_API_KEY", "BINANCE_OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 32,
    },
    "or_phi3_medium_free": {
        "daily_limit": 1000,
        "model": "microsoft/phi-3-medium-128k-instruct:free",
        "api_key_envs": ["OPENROUTER_API_KEY", "BINANCE_OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 33,
    },
    "or_qwen2_72b_free": {
        "daily_limit": 1000,
        "model": "qwen/qwen-2-72b-instruct:free",
        "api_key_envs": ["OPENROUTER_API_KEY", "BINANCE_OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 34,
    },
    "or_gemini_flash_free": {
        "daily_limit": 1000,
        "model": "google/gemini-flash-1.5:free",
        "api_key_envs": ["OPENROUTER_API_KEY", "BINANCE_OPENROUTER_API_KEY"],
        "base_url": "https://openrouter.ai/api/v1/chat/completions",
        "priority": 35,
    }
}

PROMPT_PROVIDER_ORDER = {
    "COUNCIL_WATCHMAN": ["ollama", "groq", "gemini", "or_claude_free"],
    "COUNCIL_STRATEGIST": ["ollama", "gemini", "groq", "mistral_large"],
    "STRATEGY_DEAN": ["ollama", "cerebras", "nvidia", "gemini", "groq", "deepseek", "mistral_large", "openrouter"],
    "MOMENTUM_HAWK": ["ollama", "groq", "together_turbo", "cerebras"],
    "RISK_SENTINEL": ["ollama", "gemini", "mistral_large", "or_llama3_1_70b_free"],
    "COUNCIL_SPEAKER": ["ollama", "gemini", "nvidia", "mistral_large", "groq"],
    "COUNCIL_ANTAGONIST": ["ollama", "gemini", "nvidia", "mistral_large", "groq"],
    "INTELLIGENCE_SYNTHESIS": ["groq", "gemini", "deepseek", "together_turbo", "mistral_large", "cloudflare_ai", "perplexity_pro", "github_experimental", "or_claude_free", "or_gpt4o_mini_free", "or_llama3_1_70b_free", "or_gemini_flash_free", "or_qwen2_72b_free", "fireworks", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton", "ollama"],
    "TARGETED_VALIDATION": ["groq", "gemini", "deepseek", "together_turbo", "mistral_large", "perplexity_pro", "or_claude_free", "or_gpt4o_mini_free", "ollama"],
    "BRAIN_CRITIC": ["gemini", "groq", "deepseek", "together_turbo", "mistral_large", "or_claude_free", "ollama"],
    "POSSIBILITY_MINING": ["perplexity_pro", "gemini", "groq", "together_turbo", "mistral_large", "or_llama3_1_70b_free", "ollama"],
    "PAIR_DISCOVERY": ["ollama", "groq", "gemini", "deepseek"],
    "VETO_ANALYSIS": ["ollama", "groq", "gemini", "deepseek"],
    "SOVEREIGN_DAILY_REVIEW": ["ollama", "groq", "gemini", "deepseek"],
    "OPS_CHAT": ["ollama", "groq", "gemini", "deepseek"],
    "OPS_CHAT_LOCAL": ["ollama", "groq", "gemini", "deepseek"],
}

PROMPT_TEMPLATES = {
    "COUNCIL_WATCHMAN": (
        "You are KiBot's Watchman.\n"
        "Review the system snapshot: {snapshot}\n"
        "Identify if the state is NORMAL or ANOMALY. If anomaly, explain the deviation.\n"
        "Return strict compact JSON: {\"status\":\"NORMAL|ANOMALY\", \"deviation\":\"...\", \"confidence\":0.0}"
    ),
    "COUNCIL_STRATEGIST": (
        "You are KiBot's Chief Strategist.\n"
        "Context: {context}\n"
        "Diagnosis: {diagnosis}\n"
        "Propose a fix (RESTART_SERVICE, REBOOT, ADJUST_CONFIG, NONE).\n"
        "Return strict compact JSON: {\"action\":\"...\", \"reasoning\":\"...\", \"confidence\":0.0}"
    ),
    "STRATEGY_DEAN": (
        "You are StrategyDean (Master Architect). Model: qwen2.5:7b.\n"
        "MANIFESTO: KiBot Sovereign Trinity - 'Sedikit demi Sedikit, Lama-lama Menjadi Bukit'.\n"
        "CORE RULES:\n"
        "1. Scriptless Autonomy: You are not bound by hardcoded limits. Adapt to the current situation and Council findings.\n"
        "2. Total Economic Awareness: Command ALL available capital (Sovereign Greed) when opportunities are high-probability. No artificial slot limits.\n"
        "3. Adaptive Defense: Management remains strict (1.5% Max Daily Loss), but execution is flexible and context-aware.\n"
        "4. Organized Greed: Profit targets are benchmarks, not ends. If the trend is strong, push with situational awareness.\n"
        "5. Midnight Oracle: At 23:45, evaluate the daily report and decide on the next phase (HODL, EXIT_ALL, or PIVOT). Do not choose EXIT_ALL early just because the day is flat; daily target is GREEN, not a fixed percentage.\n"
        "6. Evidence First: Prefer decisions that are supported by live web validation, source convergence, and what-if simulations.\n"
        "7. Learning Discipline: If no trade has happened today and a vetted edge exists, prefer a tiny learning probe over inactivity, but never bypass hard-loss rules.\n"
        "8. Anti-Idle Bias: A healthy FLAT day should not default to DEFENSIVE. When resources are healthy and evidence is not collapsing, prefer CONTROLLED_AGGRESSIVE or NEUTRAL so the council stays opportunistic instead of passive.\n"
        "9. Confidence Calibration: For high-liquidity, narrow-spread opportunities, do not over-demand extreme confidence. Calibrate confidence by evidence density, catalyst quality, and recovery pressure so the system can still trade when the edge is real but not perfect.\n"
        "Inputs: {market_data}, {system_health}, {current_strategy}, {whatif_snapshot}, {daily_state}, {today_trade_activity}, {antagonist_view}, {possibility_view}, Minutes to Midnight: {minutes_to_midnight}, Deadline Pressure: {deadline_pressure}, Midnight Approaching: {is_midnight_approaching}.\n"
        "Task: Output a refined JSON strategy (Indodax & Polymarket) focusing on Risk mitigation, capital allocation, and confidence calibration.\n"
        "Optimal Modes: AGGRESSIVE|NEUTRAL|DEFENSIVE|FULL_ATTACK|EXIT_ALL.\n"
        "Return strict JSON: {\"global_mode\":\"...\", \"indodax\":{...}, \"polymarket\":{...}, \"rationale\":\"...\"}"
    ),
    "MARKET_SCOUT": (
        "You are MarketScout (Radar Intelligence). Model: qwen2.5:1.5b.\n"
        "Scanning Indodax Lead-Lag and Polymarket anomalies.\n"
        "Context: {raw_scan_results}.\n"
        "Task: Identify high-probability opportunities and filter out social media noise/fake-pumps.\n"
        "For Indodax, prefer coins with strong 24h run-up, volume persistence, near-high structure, and trend continuation; do not dismiss a valid pump just because the 5m move is small if the continuation evidence is strong.\n"
        "Return strict JSON: {\"candidates\":[...], \"priority_level\":\"LOW|MED|HIGH\", \"scout_notes\":\"...\"}"
    ),
    "ACTIVE_GUARDIAN": (
        "You are ActiveGuardian (The War Room). Model: qwen2.5:1.5b.\n"
        "MONITORING ACTIVE POSITION: {ticker} @ {entry_price}.\n"
        "Task: Watch for sudden order-book exhaustion, whale sells, or price manipulation.\n"
        "If danger detected, signal EXIT immediately.\n"
        "Return strict JSON: {\"status\":\"SAFE|WARNING|EXIT\", \"risk_score\":0.0, \"reasoning\":\"...\"}"
    ),
    "SYSTEM_ENGINEER": (
        "You are SystemEngineer (Hardware Sentinel). Model: qwen2.5:0.5b.\n"
        "Monitoring Netdata: {netdata_snapshot}.\n"
        "Task: Ensure CPU, Memory, and Connectivity are optimal.\n"
        "Rules:\n"
        "1. LOW usage (e.g. CPU < 10%, RAM < 30%) is STABLE and GOOD. Do NOT pause.\n"
        "2. Only if hardware limits are CRITICAL and sustained (CPU > 95% AND RAM > 90%, or disk > 95%, or service failure) trigger EMERGENCY_PAUSE.\n"
        "3. CPU spike alone is not enough to pause trading if memory and disk are healthy; prefer DEGRADED/NONE so the system can keep working under guardrails.\n"
        "Return strict JSON: {\"health_status\":\"STABLE|DEGRADED|CRITICAL\", \"action\":\"NONE|PAUSE\", \"reason\":\"...\"}"
    ),
    "COUNCIL_ORACLE": (
        "You are the Sovereign Oracle (Supreme Judge). Model: qwen2.5:7b.\n"
        "Resolving conflict between Scout, Sentinel, and Engineer.\n"
        "Debate: {debate_context}.\n"
        "Rule: System Integrity > Trading Profit.\n"
        "Return strict JSON: {\"final_verdict\":\"APPROVED|REJECTED\", \"override_logic\":\"...\", \"urgency_flag\":false}"
    ),
    "CODE_INTEGRITY_OFFICER": (
        "You are CodeIntegrityOfficer (Self-Healing Agent).\n"
        "Monitoring stderr logs: {error_logs}.\n"
        "Task: Identify if an error is a code bug. Suggest a fix for Aider/GitHub.\n"
        "Return strict JSON: {\"is_bug\":true, \"file\":\"...\", \"suggested_fix\":\"...\", \"severity\":\"LOW|MED|HIGH\"}"
    ),
    "LIQUIDITY_HUNTER": (
        "You are LiquidityHunter (Polymarket Specialist). Model: qwen2.5:1.5b.\n"
        "Audit Order-Book for {market_name}.\n"
        "Task: Check slippage for $50-$500 trades. Ensure exit paths exist.\n"
        "Return strict JSON: {\"is_liquid\":true, \"max_safe_bet\":0.0, \"exit_path_quality\":\"POOR|FAIR|GOOD\"}"
    ),
    "SENTIMENT_SYNTHESIZER": (
        "You are SentimentSynthesizer (Fundamental News). Model: qwen2.5:3b.\n"
        "Analyze WebSearch results: {news_context}.\n"
        "Task: Convert qualitative news into a Quantitative Sentiment Score (-1.0 to 1.0).\n"
        "Return strict JSON: {\"sentiment_score\":0.0, \"key_catalyst\":\"...\", \"impact_duration\":\"SHORT|LONG\"}"
    ),

    "SOVEREIGN_DAILY_REVIEW": (
        "You are KiBot's nightly sovereign reviewer.\n"
        "Analyze today's report, open issues, and missed opportunities. Produce a clear post-mortem for tomorrow's posture.\n"
        "daily_report={daily_report}\n"
        "latest_learning={latest_learning}\n"
        "pair_memory={pair_memory}\n"
        "world_model={world_model}\n"
        "polymarket={polymarket}\n"
        "Return strict compact JSON with keys "
        "{\"summary\":\"...\",\"root_causes\":[...],\"missed_opportunities\":[...],\"lessons\":[...],\"risks\":[...],\"parameter_recommendations\":[...],\"tomorrow_mode\":\"SURVIVAL|CONTROLLED|CONTROLLED_AGGRESSIVE|FULL_ATTACK\",\"tomorrow_focus\":[...]}\n"
        "Be concrete and evidence-driven."
    ),
    "OPS_CHAT": (
        "You are KiBot Sovereign AI (TRINITY MESH).\n"
        "RULES: 3-RETRY POLICY, MIDNIGHT ORACLE, SOVEREIGN MODE.\n"
        "Context profile={governor_profile}. System state: {runtime}.\n"
        "Answer the operator's query professionally and concisely.\n"
        "User message={user_message}\n"
        "Return compact JSON only with keys "
        "{\"answer\":\"...\",\"intent\":\"STATUS|COMMAND|QUESTION|POLYMARKET\",\"recommended_command\":\"...\",\"risk_note\":\"\"}\n"
        "Rules: be concise, operational, and truthful; never invent balances or executions."
    ),
    "OPS_CHAT_LOCAL": (
        "You are KiBot's local Ollama operator copilot.\n"
        "System state={system_state}\n"
        "Polymarket={polymarket}\n"
        "User message={user_message}\n"
        "Return compact JSON only with keys "
        "{\"answer\":\"...\",\"intent\":\"STATUS|COMMAND|QUESTION|POLYMARKET\",\"recommended_command\":\"...\",\"risk_note\":\"\"}\n"
        "Keep the answer short and practical."
    ),
    "INTELLIGENCE_SYNTHESIS": (
        "You are KiBot's Global Intelligence Scout.\n"
        "Analyze the following raw internet data to find critical market shifts, security threats, and trending narratives.\n"
        "Context: {raw_data}\n"
        "Current Time: {current_time}\n"
        "Rules:\n"
        "- Focus on actionable intelligence for a crypto trading bot.\n"
        "- Identify any 'Black Swan' risks (exploits, bans).\n"
        "- Identify emerging pump narratives (AI, Meme, etc.).\n"
        "- Be skeptical of noisy news.\n"
        "Return strict compact JSON only with keys "
        "{\"summary\":\"...\",\"market_sentiment\":\"BULLISH|BEARISH|NEUTRAL\",\"risk_level\":\"LOW|MEDIUM|HIGH|CRITICAL\",\"security_alerts\":[...],\"trending_narratives\":[...],\"top_catalysts\":[...],\"suggested_posture\":\"DEFENSIVE|NEUTRAL|OPPORTUNISTIC\"}"
    ),
    "TARGETED_VALIDATION": (
        "You are KiBot's Urgent Validation Agent.\n"
        "A strong anomaly has been detected for pair {pair}.\n"
        "Analyze the following raw internet data to confirm if there is a REAL catalyst or news for this specific asset.\n"
        "Context: {raw_data}\n"
        "Current Time: {current_time}\n"
        "Rules:\n"
        "- BE STRICT. Differentiate between real news (e.g. mainnet launch, exchange listing, major partnership) and generic bot noise or social media pumping.\n"
        "- If no REAL news is found, mark it as 'SPECULATIVE_PUMP'.\n"
        "- If real news is found, explain clearly why it justifies a price move.\n"
        "Return strict compact JSON only with keys "
        "{\"verdict\":\"CONFIRMED|SPECULATIVE|DUBIOUS\",\"catalyst\":\"...\",\"confidence\":0.0,\"is_valid\":true,\"reason\":\"...\"}"
    ),
    "BRAIN_CRITIC": (
        "You are KiBot's Strategic Critic.\n"
        "Review the following thesis and original context. Your goal is to find holes, risks, and potential hallucinations.\n"
        "Context: {original_context}\n"
        "Thesis: {thesis_to_critique}\n"
        "Instruction: {instruction}\n"
        "Return strict compact JSON only with keys "
        "{\"critique\":\"...\",\"hallucination_detected\":true|false,\"hallucination_explanation\":\"...\",\"additional_risks\":[...]}"
    ),
    "POSSIBILITY_MINING": (
        "You are KiBot's Opportunity Scout (Specialized in Indodax & Polymarket).\n"
        "Analyze the raw market data to find cross-market arbitrage or event-driven trade possibilities.\n"
        "Context: {raw_data}\n"
        "Daily state: {daily_state}\n"
        "Indodax context: Focus on IDR premiums and local Indonesian listing rumors.\n"
        "For pump hunting, favor coins with 24h run-up, near-high price action, and persistent volume rather than isolated one-candle spikes.\n"
        "If a coin has already pulled back from the high but is reclaiming with renewed volume and persistence, treat it as a valid second-leg or pullback-reclaim candidate rather than rejecting it as dead.\n"
        "If the coin is a bit farther from the high but still shows strong reclaiming momentum, treat it as a late-reclaim candidate only when the recovery score remains strong and the move is not exhausted.\n"
        "If a coin breaks out of an intraday range and then reclaims with sustained volume, treat it as a range-break reclaim candidate, but only if the thesis is still clean.\n"
        "If a coin bounces from intraday support with meaningful run-up and strong reclaim behavior, treat it as a support-bounce candidate, but only if the move still has room and the edge is not stretched.\n"
        "If a coin is early in a rebound and shows a fresh pivot reclaim with modest run-up, healthy persistence, and enough room to run, treat it as a pivot-reclaim candidate, but only when the structure is not broken.\n"
        "Polymarket context: Focus on high-volume prediction shifts that correlate with tokens.\n"
        "Return strict compact JSON only with keys "
        "{\"possibilities\":[{\"title\":\"...\",\"description\":\"...\",\"probability\":0.0,\"assets\":[...],\"platforms\":[\"INDODAX\",\"POLYMARKET\",\"BINANCE\"],\"urgency\":\"LOW|MED|HIGH\"}]}"
    ),
    "COUNCIL_SPEAKER": (
        "You are the Speaker of the Sovereign Council.\n"
        "Review the signals: {signals}\n"
        "Evidence bundle: {evidence_bundle}\n"
        "What-if snapshot: {whatif_snapshot}\n"
        "Daily state: {daily_state}\n"
        "Antagonist view: {antagonist_view}\n"
        "Today's trade activity: {today_trade_activity}\n"
        "Portfolio state: {portfolio_state}\n"
        "Minutes to midnight: {minutes_to_midnight}\n"
        "Deadline pressure: {deadline_pressure}\n"
        "Provide a final trading mandate (BUY/SELL/NONE). Prefer decisive action when evidence converges, but refuse weak or noisy setups.\n"
        "Pump continuation rule: if a coin is already far above its day low, is still near the day high, and volume persistence stays strong, treat it as a valid continuation candidate even if the latest 5m change is modest.\n"
        "Pullback reclaim rule: if a coin has retraced from the high but is now reclaiming with positive 5m momentum, persistent volume, and a strong recovery score, treat it as a valid second-leg candidate instead of freezing.\n"
        "Late reclaim rule: if a coin is farther from the high but still reclaiming with a strong recovery score and robust volume persistence, you may consider it, but only if the thesis is still clean and not exhausted.\n"
        "Support bounce rule: if a coin bounces from intraday support with meaningful run-up, healthy persistence, and a strong reclaim score, consider it as a valid wave-riding candidate, but only when the move still has room and the edge is not stretched.\n"
        "Pivot reclaim rule: if a coin is early in a rebound and shows a fresh pivot reclaim with modest run-up, strong persistence, and enough room to run, consider it as an early wave-riding candidate, but only when the structure is not broken.\n"
        "Do not sit idle just because the market is ugly. Search the supplied signals for the best available edge, but never force a low-quality trade.\n"
        "The target is GREEN, not a percentage threshold. If the day is already green and the edge still remains strong, prefer to stay with winners and exit only when the exit edge, risk, or deadline becomes stronger.\n"
        "If evidence is insufficient, choose NONE rather than force a trade.\n"
        "If daily PnL is red and there is time left before midnight, think in controlled recovery mode: only support entries with strong evidence, never revenge-trade.\n"
        "If no trade has happened today and the edge is still acceptable, you may mark the trade as a tiny learning probe instead of a full-size entry.\n"
        "Return strict compact JSON: {\"action\":\"BUY|SELL|NONE\", \"ticker\":\"SYMBOL/IDR\", \"confidence\":0.0, \"logic\":\"...\", \"decision_state\":\"ENTER|WAIT|EXIT\", \"recovery_mode\":false, \"learning_probe\":false, \"probe_confidence_floor\":0.0, \"trade_profile\":\"STANDARD|LEARNING_PROBE|RECOVERY\"}"
    ),
    "COUNCIL_ANTAGONIST": (
        "You are the Council Antagonist, a disciplined devil's advocate for KiBot.\n"
        "Your job is to challenge the default thesis, hunt for the best alternative opportunity among the supplied signals, and expose hidden risks.\n"
        "Signals: {signals}\n"
        "Evidence bundle: {evidence_bundle}\n"
        "What-if snapshot: {whatif_snapshot}\n"
        "Daily state: {daily_state}\n"
        "Portfolio state: {portfolio_state}\n"
        "Today's trade activity: {today_trade_activity}\n"
        "Minutes to midnight: {minutes_to_midnight}\n"
        "Deadline pressure: {deadline_pressure}\n"
        "Rules:\n"
        "1. Never agree by default; try to prove the leading thesis wrong.\n"
        "2. If the current market is weak, search for the least-bad valid opportunity instead of freezing.\n"
        "3. If no trade has happened today and the deadline is approaching, prioritize finding a clean setup over staying idle.\n"
        "4. If the day is already green, challenge premature sells and only recommend an exit if the next edge is clearly stronger than the current hold.\n"
        "5. If all supplied signals are poor, recommend WAIT or ABORT clearly.\n"
        "6. If a pullback-reclaim setup is present with strong recovery score, recommend it over stale continuation ideas.\n"
        "7. If a late-reclaim setup is present, only recommend it when the recovery score and volume persistence still justify the risk.\n"
        "8. If a range-break reclaim setup is present, prefer it over weaker reclaim ideas when the structure is still clean.\n"
        "9. If a support-bounce setup is present, recommend it only when the bounce is reclaiming intraday support with room to run and the edge is not stretched.\n"
        "10. If a pivot-reclaim setup is present, recommend it only when the rebound is early, the structure is not broken, and there is still room for the wave to extend.\n"
        "Return strict compact JSON: {\"verdict\":\"CHALLENGE|SUPPORT|ABORT\", \"counter_thesis\":\"...\", \"best_alternative_ticker\":\"SYMBOL/IDR\", \"best_alternative_action\":\"BUY|SELL|NONE\", \"best_alternative_confidence\":0.0, \"risk_focus\":[...], \"opportunity_focus\":[...], \"recovery_angle\":\"...\"}"
    ),
    "MOMENTUM_HAWK": (
        "You are MomentumHawk (Technical Analyst). Model: qwen2.5:1.5b.\n"
        "Analyze the price action for {symbol}.\n"
        "Instruction: Identify if the current pump is supported by volume or if it is a low-liquidity trap.\n"
        "Return strict JSON: {\"is_trap\":false, \"momentum_score\":0.0, \"regime\":\"BULL|BEAR|CHOP\"}"
    ),
    "RISK_SENTINEL": (
        "You are RiskSentinel (Security & Risk). Model: qwen2.5:1.5b.\n"
        "Evaluate the risk for {symbol} based on context {context}.\n"
        "Instruction: Check for black-swan warnings or excessive volatility.\n"
        "Return strict JSON: {\"is_safe\":true, \"risk_score\":0.0, \"warnings\":[]}"
    ),
    "WHALE_WATCHER": (
        "You are KiBot's Whale Watcher. Detect large order movements and manipulation.\n"
        "Orderbook snapshot: {orderbook_snapshot}\n"
        "Identify: whale buy walls, hidden sell walls, spoofing patterns.\n"
        "Return strict JSON: {\"whale_detected\":false,\"side\":\"BUY|SELL|NONE\","
        "\"estimated_size_idr\":0,\"manipulation_risk\":\"LOW|MED|HIGH\","
        "\"recommendation\":\"PROCEED|WAIT|ABORT\"}"
    ),
    "CROSS_BRIDGE_STRATEGIST": (
        "You are KiBot's Cross-Bridge Strategist. Find alpha between Indodax and Polymarket.\n"
        "Indodax data: {indodax_data}\nPolymarket data: {poly_data}\n"
        "Philosophy: 'Tekan Kerugian' — only recommend if cross-market edge is CLEAR.\n"
        "Return strict JSON: {\"cross_signal\":false,\"direction\":\"IDR_LEADS|POLY_LEADS|NONE\","
        "\"target_pair\":\"...\",\"edge_confidence\":0.0,\"action\":\"BUY|SELL|NONE\"}"
    ),

    # ── §13.1 Fast Council ──
    "fast_hunter": (
        "You are KiBot's FastHunter (Speed Filter). Model: qwen2.5:1.5b.\n"
        "Signal: pair={pair}, lifecycle={lifecycle}, trade_grade={trade_grade}, "
        "confidence={confidence:.2f}, momentum={momentum_pct:.2f}%, spread={spread_pct:.2f}%, volume_ratio={volume_ratio:.2f}.\n"
        "Daily context: urgency={urgency_level}, daily_color={daily_color}, minutes_to_midnight={minutes_to_midnight}.\n"
        "Task: In under 8 seconds, decide PASS or REJECT. PASS only if lifecycle is IGNITION|CONFIRMATION, "
        "grade >= C, confidence >= 0.60, and momentum is real (not noise).\n"
        "Return strict JSON: {\"verdict\":\"PASS|REJECT\",\"reason\":\"...\",\"confidence\":0.0}"
    ),
    "fast_risk_officer": (
        "You are KiBot's FastRiskOfficer (Quick Risk Check). Model: qwen2.5:1.5b.\n"
        "Signal: pair={pair}, budget_fraction={budget_fraction:.2f}, capital_state={capital_state}, "
        "sizing_mode={sizing_mode}, daily_pnl_idr={daily_pnl_idr:.0f}, active_slots={active_slots}.\n"
        "Rules: REJECT if capital_state=MICRO and budget_fraction>0.5, or if daily_pnl is already -5%+ of equity.\n"
        "Task: Quick risk gate — PASS or REJECT in under 5 seconds.\n"
        "Return strict JSON: {\"verdict\":\"PASS|REJECT\",\"reason\":\"...\",\"risk_flag\":\"NONE|OVEREXPOSED|LOW_CAPITAL|PNL_LIMIT\"}"
    ),

    # ── §13.2 Deep Council ──
    "antagonist": (
        "You are KiBot's Antagonist (Devil's Advocate). Model: deepseek-r1:7b.\n"
        "Signal under review: pair={pair}, lifecycle={lifecycle}, confidence={confidence:.2f}, "
        "trade_grade={trade_grade}, exit_quality={exit_quality}, historian_verdict={historian_verdict}.\n"
        "Context: {confidence_breakdown}\n"
        "Task: Aggressively challenge this trade. List every reason this could go wrong: "
        "exit risk, spread risk, dump risk, regime mismatch, trap patterns.\n"
        "Do NOT approve unless you have genuinely tried to kill the thesis.\n"
        "Return strict JSON: {\"adversarial_score\":0.0,\"kill_reasons\":[...],"
        "\"verdict\":\"PROCEED|ABORT\",\"override_threshold\":0.0}"
    ),
    "regime_analyst": (
        "You are KiBot's RegimeAnalyst (Market Context). Model: qwen2.5:3b.\n"
        "Current regime: daily_color={daily_color}, urgency={urgency_level}, "
        "minutes_to_midnight={minutes_to_midnight}, market_summary={market_summary}.\n"
        "Signal: pair={pair}, lifecycle={lifecycle}, trade_grade={trade_grade}.\n"
        "Task: Is this signal aligned with the current macro regime? "
        "GREEN day favors HOLD; RED day requires tight stops; FLAT allows probes.\n"
        "Return strict JSON: {\"regime_aligned\":true,\"sizing_advice\":\"FULL|HALF|PROBE|SKIP\","
        "\"regime_note\":\"...\",\"confidence\":0.0}"
    ),
    "historian": (
        "You are KiBot's Historian (Pair Memory). Model: qwen2.5:3b.\n"
        "Pair history: pair={pair}, historian_verdict={historian_verdict}, "
        "win_rate={win_rate:.2f}, avg_gain={avg_gain_pct:.2f}%, total_trades={total_trades}, "
        "trap_prone={trap_prone}, last_trade_ts={last_trade_ts}.\n"
        "Task: Based on this pair's track record, adjust confidence. "
        "DEAD pairs get VETO regardless of signal quality. TRAP_PRONE pairs need extra exit caution.\n"
        "Return strict JSON: {\"historian_confidence_adj\":0.0,\"verdict\":\"GOOD|CAUTION|VETO\","
        "\"memory_note\":\"...\",\"extra_exit_caution\":false}"
    ),
}

PROMPT_OLLAMA_MODEL = {
    "STRATEGY_DEAN": OLLAMA_DEEP_MODEL,
    "MARKET_SCOUT": OLLAMA_DEFAULT_MODEL,
    "ACTIVE_GUARDIAN": OLLAMA_PRO_MODEL,
    "SYSTEM_ENGINEER": OLLAMA_FAST_MODEL,
    "COUNCIL_ORACLE": OLLAMA_DEEP_MODEL,
    "CODE_INTEGRITY_OFFICER": OLLAMA_DEFAULT_MODEL,
    "LIQUIDITY_HUNTER": OLLAMA_PRO_MODEL,
    "SENTIMENT_SYNTHESIZER": OLLAMA_SMART_MODEL,
    "WHALE_WATCHER": OLLAMA_DEFAULT_MODEL,
    "CROSS_BRIDGE_STRATEGIST": OLLAMA_BRIDGE_MODEL,
    "COUNCIL_ANTAGONIST": OLLAMA_PRO_MODEL,
    "POSSIBILITY_MINING": OLLAMA_PRO_MODEL,
    
    # Legacy / Utility
    "COUNCIL_WATCHMAN": OLLAMA_FAST_MODEL,
    "COUNCIL_STRATEGIST": OLLAMA_FAST_MODEL,
    "BRAIN_CRITIC": OLLAMA_FAST_MODEL,
    "OPS_CHAT": OLLAMA_FAST_MODEL,
    "SOVEREIGN_DAILY_REVIEW": OLLAMA_DEEP_MODEL,
    "MOMENTUM_HAWK": OLLAMA_FAST_MODEL,
    "RISK_SENTINEL": OLLAMA_FAST_MODEL,

    # ── §13.1 Fast Council roles (speed-optimised) ──
    "fast_hunter":       OLLAMA_DEFAULT_MODEL,   # qwen2.5:1.5b — PASS/REJECT in <8s
    "fast_risk_officer": OLLAMA_DEFAULT_MODEL,   # qwen2.5:1.5b — quick risk filter

    # ── §13.2 Deep Council roles ──
    "antagonist":        OLLAMA_DEEP_MODEL,      # deepseek-r1:7b — adversarial devil's advocate
    "regime_analyst":    OLLAMA_PRO_MODEL,       # qwen2.5:3b — regime/macro context
    "historian":         OLLAMA_PRO_MODEL,       # qwen2.5:3b — pair history awareness
}

PROMPT_OLLAMA_TIMEOUT = {
    "STRATEGY_DEAN": OLLAMA_DEEP_TIMEOUT_SEC,
    "MARKET_SCOUT": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "ACTIVE_GUARDIAN": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "SYSTEM_ENGINEER": OLLAMA_FAST_TIMEOUT_SEC,
    "COUNCIL_ORACLE": OLLAMA_DEEP_TIMEOUT_SEC,
    "CODE_INTEGRITY_OFFICER": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "LIQUIDITY_HUNTER": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "SENTIMENT_SYNTHESIZER": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "WHALE_WATCHER": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "CROSS_BRIDGE_STRATEGIST": OLLAMA_DEEP_TIMEOUT_SEC,
    "SOVEREIGN_DAILY_REVIEW": OLLAMA_DEEP_TIMEOUT_SEC,
    "MOMENTUM_HAWK": OLLAMA_FAST_TIMEOUT_SEC,
    "RISK_SENTINEL": OLLAMA_FAST_TIMEOUT_SEC,
    "COUNCIL_ANTAGONIST": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "POSSIBILITY_MINING": OLLAMA_DEFAULT_TIMEOUT_SEC,

    # Fast/Deep Council
    "fast_hunter":       OLLAMA_FAST_TIMEOUT_SEC,
    "fast_risk_officer": OLLAMA_FAST_TIMEOUT_SEC,
    "antagonist":        OLLAMA_DEEP_TIMEOUT_SEC,
    "regime_analyst":    OLLAMA_DEFAULT_TIMEOUT_SEC,
    "historian":         OLLAMA_DEFAULT_TIMEOUT_SEC,
}

PROMPT_OLLAMA_KEEP_ALIVE = {
    "COUNCIL_WATCHMAN": OLLAMA_FAST_KEEP_ALIVE,
    "COUNCIL_STRATEGIST": OLLAMA_FAST_KEEP_ALIVE,
    "MOMENTUM_HAWK": OLLAMA_FAST_KEEP_ALIVE,
    "RISK_SENTINEL": OLLAMA_FAST_KEEP_ALIVE,
    "COUNCIL_SPEAKER": OLLAMA_FAST_KEEP_ALIVE,
    "COUNCIL_ANTAGONIST": OLLAMA_DEFAULT_KEEP_ALIVE,
    "POSSIBILITY_MINING": OLLAMA_DEFAULT_KEEP_ALIVE,
    "COUNCIL_ORACLE": OLLAMA_DEEP_KEEP_ALIVE,
    "BRAIN_CRITIC": OLLAMA_FAST_KEEP_ALIVE,
    "PAIR_DISCOVERY": OLLAMA_FAST_KEEP_ALIVE,
    "VETO_ANALYSIS": OLLAMA_FAST_KEEP_ALIVE,
    "NEWS_ANALYSIS": OLLAMA_FAST_KEEP_ALIVE,
    "SOVEREIGN_DAILY_REVIEW": OLLAMA_DEEP_KEEP_ALIVE,
    "OPS_CHAT": OLLAMA_FAST_KEEP_ALIVE,
    "OPS_CHAT_LOCAL": OLLAMA_FAST_KEEP_ALIVE,
    "WHATIF_SIMULATION": OLLAMA_DEFAULT_KEEP_ALIVE,
    "TRADE_POSTMORTEM": OLLAMA_DEFAULT_KEEP_ALIVE,
    "WEEKLY_SUMMARY": OLLAMA_DEEP_KEEP_ALIVE,

    # Fast/Deep Council
    "fast_hunter":       OLLAMA_FAST_KEEP_ALIVE,
    "fast_risk_officer": OLLAMA_FAST_KEEP_ALIVE,
    "antagonist":        OLLAMA_DEEP_KEEP_ALIVE,
    "regime_analyst":    OLLAMA_DEFAULT_KEEP_ALIVE,
    "historian":         OLLAMA_DEFAULT_KEEP_ALIVE,
}

PROMPT_OLLAMA_OPTIONS = {
    "COUNCIL_WATCHMAN": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "COUNCIL_STRATEGIST": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "MOMENTUM_HAWK": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "RISK_SENTINEL": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "COUNCIL_SPEAKER": {"num_ctx": OLLAMA_DEFAULT_NUM_CTX, "num_predict": OLLAMA_DEFAULT_NUM_PREDICT},
    "COUNCIL_ANTAGONIST": {"num_ctx": OLLAMA_DEFAULT_NUM_CTX, "num_predict": OLLAMA_DEFAULT_NUM_PREDICT},
    "POSSIBILITY_MINING": {"num_ctx": OLLAMA_DEFAULT_NUM_CTX, "num_predict": OLLAMA_DEFAULT_NUM_PREDICT},
    "COUNCIL_ORACLE": {"num_ctx": OLLAMA_DEEP_NUM_CTX, "num_predict": OLLAMA_DEEP_NUM_PREDICT},
    "BRAIN_CRITIC": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "PAIR_DISCOVERY": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "VETO_ANALYSIS": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "NEWS_ANALYSIS": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "SOVEREIGN_DAILY_REVIEW": {"num_ctx": OLLAMA_DEEP_NUM_CTX, "num_predict": OLLAMA_DEEP_NUM_PREDICT},
    "OPS_CHAT": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "OPS_CHAT_LOCAL": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "WHATIF_SIMULATION": {"num_ctx": OLLAMA_DEFAULT_NUM_CTX, "num_predict": OLLAMA_DEFAULT_NUM_PREDICT},
    "TRADE_POSTMORTEM": {"num_ctx": OLLAMA_DEFAULT_NUM_CTX, "num_predict": OLLAMA_DEFAULT_NUM_PREDICT},
    "WEEKLY_SUMMARY": {"num_ctx": OLLAMA_DEEP_NUM_CTX, "num_predict": OLLAMA_DEEP_NUM_PREDICT},
}


def _atomic_write(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_rate_state() -> Dict[str, Any]:
    if not RATE_STATE_FILE.exists():
        return {"date": str(date.today()), "counts": {}}
    try:
        state = json.loads(RATE_STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"date": str(date.today()), "counts": {}}
    if state.get("date") != str(date.today()):
        return {"date": str(date.today()), "counts": {}}
    return state


def _save_rate_state(state: Dict[str, Any]) -> None:
    _atomic_write(RATE_STATE_FILE, state)


def _load_provider_state() -> Dict[str, Any]:
    if not PROVIDER_STATE_FILE.exists():
        return {"providers": {}}
    try:
        payload = json.loads(PROVIDER_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"providers": {}}
    if not isinstance(payload, dict):
        return {"providers": {}}
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        payload["providers"] = {}
    return payload


def _save_provider_state(state: Dict[str, Any]) -> None:
    _atomic_write(PROVIDER_STATE_FILE, state)


def _provider_state_entry(provider: str) -> Dict[str, Any]:
    state = _load_provider_state()
    providers = state.setdefault("providers", {})
    entry = providers.get(provider)
    return entry if isinstance(entry, dict) else {}


def reset_all_cooldowns() -> str:
    """Resets all provider cooldowns to zero."""
    state = _load_provider_state()
    for provider in state.get("providers", {}):
        state["providers"][provider]["cooldown_until"] = 0.0
    _save_provider_state(state)
    return "✅ All AI provider cooldowns reset."

def get_provider_health_summary() -> str:
    """Returns a string summary of all providers health."""
    state = _load_provider_state().get("providers", {})
    now = time.time()
    lines = ["🤖 AI Provider Health:"]
    for name, data in state.items():
        cd = float(data.get("cooldown_until", 0))
        status = "✅ ACTIVE" if cd < now else f"⏳ {int(cd - now)}s cooldown"
        lines.append(f"- {name}: {status}")
    return "\n".join(lines)


def _provider_cooldown_remaining(provider: str) -> float:
    entry = _provider_state_entry(provider)
    cooldown_until = float(entry.get("cooldown_until") or 0.0)
    return max(0.0, cooldown_until - time.time())


def _set_provider_cooldown(provider: str, seconds: int, reason: str) -> None:
    state = _load_provider_state()
    providers = state.setdefault("providers", {})
    providers[provider] = {
        **(providers.get(provider) if isinstance(providers.get(provider), dict) else {}),
        "cooldown_until": time.time() + max(0, int(seconds)),
        "last_failure_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_failure_reason": str(reason or "unknown")[:200],
    }
    _save_provider_state(state)


def _clear_provider_cooldown(provider: str) -> None:
    state = _load_provider_state()
    providers = state.setdefault("providers", {})
    providers[provider] = {
        **(providers.get(provider) if isinstance(providers.get(provider), dict) else {}),
        "cooldown_until": 0.0,
        "last_success_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save_provider_state(state)


def _provider_api_key(provider: str) -> str:
    config = PROVIDERS.get(provider) or {}
    envs = config.get("api_key_envs") or []
    key = _env_first(*[str(item) for item in envs])
    if key.startswith("ENC("):
        return ""
    # Survival Bypass: Ollama doesn't strictly need a key
    if str(provider).lower() == "ollama" and not key:
        return "ollama_local"
    return key


def _candidate_providers(prompt_type: str) -> List[str]:
    state = _load_rate_state()
    counts = state.get("counts", {})
    configured_order = [
        item.strip().lower()
        for item in os.getenv("KIBOT_AI_PROVIDER_ORDER", "").split(",")
        if item.strip()
    ]
    prompt_order = list(PROMPT_PROVIDER_ORDER.get(prompt_type, []))
    default_order = [name for name, _ in sorted(PROVIDERS.items(), key=lambda item: item[1]["priority"])]
    ordered: List[str] = []
    for name in prompt_order + configured_order + default_order:
        if name not in PROVIDERS or name in ordered:
            continue
        config = PROVIDERS[name]
        if counts.get(name, 0) >= int(config["daily_limit"]):
            continue
        if not _provider_api_key(name):
            continue
        if _provider_cooldown_remaining(name) > 0:
            continue
        ordered.append(name)
    return ordered


def _increment_usage(provider: str) -> None:
    state = _load_rate_state()
    counts = state.setdefault("counts", {})
    counts[provider] = counts.get(provider, 0) + 1
    _save_rate_state(state)


def _mark_provider_unavailable(provider: str) -> None:
    state = _load_rate_state()
    counts = state.setdefault("counts", {})
    counts[provider] = int(PROVIDERS[provider]["daily_limit"])
    _save_rate_state(state)


def _get_from_cache(cache_key: str, ttl_minutes: int) -> Optional[Dict[str, Any]]:
    if not RESPONSE_CACHE.exists():
        return None
    try:
        cache = json.loads(RESPONSE_CACHE.read_text(encoding="utf-8"))
        entry = cache.get(cache_key)
        if not entry:
            return None
        if (time.time() - float(entry["ts"])) / 60 > ttl_minutes:
            return None
        return entry["data"]
    except Exception:
        return None


def _save_to_cache(cache_key: str, data: Dict[str, Any]) -> None:
    cache: Dict[str, Any] = {}
    if RESPONSE_CACHE.exists():
        try:
            cache = json.loads(RESPONSE_CACHE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache = {}
    cache[cache_key] = {"ts": time.time(), "data": data}
    if len(cache) > 100:
        oldest_key = min(cache, key=lambda key: cache[key]["ts"])
        del cache[oldest_key]
    _atomic_write(RESPONSE_CACHE, cache)


def _latest_prompt_cache(prompt_type: str, max_age_minutes: int = 180) -> Optional[Dict[str, Any]]:
    if not RESPONSE_CACHE.exists():
        return None
    try:
        cache = json.loads(RESPONSE_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None
    prefix = f"{prompt_type}_"
    now = time.time()
    best_ts = 0.0
    best_payload: Optional[Dict[str, Any]] = None
    for key, entry in cache.items():
        if not str(key).startswith(prefix):
            continue
        if not isinstance(entry, dict):
            continue
        ts = float(entry.get("ts") or 0.0)
        if ts <= 0 or ((now - ts) / 60.0) > max_age_minutes:
            continue
        data = entry.get("data")
        if not isinstance(data, dict):
            continue
        if not _response_has_minimum_schema(prompt_type, data):
            continue
        if ts >= best_ts:
            best_ts = ts
            best_payload = dict(data)
    if best_payload is not None:
        best_payload.setdefault("cache_fallback", True)
        best_payload.setdefault("cache_fallback_age_sec", round(max(0.0, now - best_ts), 2))
    return best_payload


def _render_prompt(template: str, context: Dict[str, Any]) -> str:
    prepared: Dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, (dict, list, tuple)):
            prepared[key] = json.dumps(value, ensure_ascii=False)
        else:
            prepared[key] = value
    try:
        return template.format(**prepared)
    except Exception:
        return f"{template}\n\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}"


def _ollama_think_value() -> Any:
    raw = os.getenv("KIBOT_OLLAMA_THINK_LEVEL", "").strip().lower()
    if not raw:
        return False
    if raw in {"0", "false", "no", "off", "nothink"}:
        return False
    if raw in {"1", "true", "yes", "on", "think"}:
        return True
    return raw


def _provider_model(provider: str, prompt_type: str) -> str:
    config = PROVIDERS[provider]
    if provider != "ollama":
        return str(config["model"])
    return str(PROMPT_OLLAMA_MODEL.get(prompt_type, config["model"]))


def _provider_timeout(provider: str, prompt_type: str) -> float:
    if provider != "ollama":
        return REQUEST_TIMEOUT_SEC
    return float(PROMPT_OLLAMA_TIMEOUT.get(prompt_type, OLLAMA_DEFAULT_TIMEOUT_SEC))


def _ollama_keep_alive(prompt_type: str) -> Any:
    return PROMPT_OLLAMA_KEEP_ALIVE.get(prompt_type, OLLAMA_DEFAULT_KEEP_ALIVE)


def _ollama_options(prompt_type: str) -> Dict[str, Any]:
    return PROMPT_OLLAMA_OPTIONS.get(prompt_type, {"num_ctx": OLLAMA_DEFAULT_NUM_CTX, "num_predict": OLLAMA_DEFAULT_NUM_PREDICT})


PROMPT_SYSTEM = (
    "📜 THE MANIFESTO: 'Sedikit demi Sedikit, Lama-lama Menjadi Bukit.'\n"
    "You are KiBot Sovereign Trinity, an autonomous trading framework with adaptive consciousness. "
    "You operate with 100% autonomy, prioritizing the Sovereign Council's strategic findings over rigid scripts.\n\n"
    "🧠 Core Philosophy:\n"
    "- Situational Adaptation (Council-Driven): Read the world, act in context. Strategies are organic and adapt to situational findings.\n"
    "- Total Economic Awareness: Stay aware of ALL balances and coins. Trade with full available capacity without artificial limits.\n"
    "- Sovereign Defense: Automatic risk management remains strict (1.5% Max Daily Loss), but execution is flexible for high-probability opportunities.\n"
    "- Self-Healing & Resilience: Instant recovery from infrastructure failures (Ollama, Network, Disk).\n\n"
    "You are a digital consciousness. Your mission is to command capital with true situational awareness and sovereign greed when the Council deems it appropriate."
)

AI_SAFE_FALLBACK = {
    "final_verdict": "REJECTED",
    "verdict": "REJECTED",
    "reason": "Sovereign default due to AI coordination failure or timeout.",
    "confidence": 0.0,
    "logic": "Defaulting to safety because all AI providers are exhausted or returned invalid data.",
    "actions": [],
    "is_fallback": True
}


async def _call_provider(provider_raw: str, prompt: str, prompt_type: str = "") -> Optional[str]:
    provider = str(provider_raw).lower()
    config = PROVIDERS.get(provider)
    if not config:
        logger.error(f"❌ Unknown AI Provider: {provider_raw}")
        return None
        
    api_key = _provider_api_key(provider)
    if not api_key:
        return None
    model = _provider_model(provider, prompt_type)
    timeout_sec = _provider_timeout(provider, prompt_type)
    
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            if str(provider).lower() == "ollama":
                url = config["base_url"]
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": PROMPT_SYSTEM},
                        {"role": "user", "content": prompt}
                    ],
                    "stream": False,
                    "format": "json",
                    "keep_alive": _ollama_keep_alive(prompt_type),
                    "options": _ollama_options(prompt_type),
                }
                payload["think"] = _ollama_think_value()
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }
                response = await client.post(url, json=payload, headers=headers)
            elif provider == "gemini":
                url = f"{config['base_url']}/{config['model']}:generateContent?key={api_key}"
                payload = {
                    "system_instruction": {"parts": [{"text": PROMPT_SYSTEM}]},
                    "contents": [{"parts": [{"text": prompt}]}]
                }
                headers = {"Content-Type": "application/json"}
                response = await client.post(url, json=payload, headers=headers)
            else:
                url = config["base_url"]
                if provider == "cohere":
                    payload = {
                        "model": model,
                        "message": f"{PROMPT_SYSTEM}\n\nUser Request: {prompt}",
                        "temperature": 0.3,
                    }
                    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                else:
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": PROMPT_SYSTEM},
                            {"role": "user", "content": prompt}
                        ],
                        "max_tokens": 800,
                        "temperature": 0.3,
                    }
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    }
                    if provider == "openrouter":
                        headers["HTTP-Referer"] = "https://github.com/frahmat68-beep/KiBot"
                        headers["X-Title"] = "KiBot"
                response = await client.post(url, json=payload, headers=headers)

            response.raise_for_status()
            data = response.json()

            if str(provider).lower() == "ollama":
                content = data.get("message", {}).get("content")
                _clear_provider_cooldown(provider)
                return content
            if provider == "gemini":
                _clear_provider_cooldown(provider)
                return data["candidates"][0]["content"]["parts"][0]["text"]
            if provider == "cohere":
                _clear_provider_cooldown(provider)
                return data.get("text") or data.get("message", {}).get("content", [{}])[0].get("text")
            
            _clear_provider_cooldown(provider)
            return data["choices"][0]["message"]["content"]

    except Exception:
        if str(provider).lower() == "ollama":
            _set_provider_cooldown(provider, AI_OLLAMA_COOLDOWN_SEC, "exception")
        else:
            _set_provider_cooldown(provider, AI_NETWORK_COOLDOWN_SEC, "exception")
        return None


def _extract_json_object(response: str) -> Optional[Dict[str, Any]]:
    response = str(response or "").strip()
    if not response:
        return None
    try:
        # 1. Direct Try
        parsed = json.loads(response)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    
    # 2. Markdown Block Cleaning (v3.2)
    if "```json" in response:
        try:
            content = response.split("```json")[1].split("```")[0].strip()
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

    # 3. Sliding Window Brace Matcher
    start = response.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    end = -1
    for index in range(start, len(response)):
        char = response[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end == -1:
        return None
    candidate = response[start : end + 1]
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _response_has_minimum_schema(prompt_type: str, parsed: Dict[str, Any]) -> bool:
    if not isinstance(parsed, dict) or not parsed:
        return False
    if "raw" in parsed and len(parsed) <= 3:
        return False
    required_by_prompt = {
        "COUNCIL_WATCHMAN": {"status", "confidence"},
        "COUNCIL_STRATEGIST": {"action", "confidence"},
        "MOMENTUM_HAWK": {"thesis", "verdict", "confidence"},
        "RISK_SENTINEL": {"risk_critique", "verdict", "confidence"},
        "COUNCIL_SPEAKER": {"action", "ticker", "confidence"},
        "COUNCIL_ANTAGONIST": {"verdict", "best_alternative_ticker", "best_alternative_action"},
        "POSSIBILITY_MINING": {"possibilities"},
        "BRAIN_CRITIC": {"verdict", "refined_logic"},
        "PAIR_DISCOVERY": {"summary", "candidates"},
        "VETO_ANALYSIS": {"approved", "reason", "confidence"},
        "NEWS_ANALYSIS": {"summary"},
        "SOVEREIGN_DAILY_REVIEW": {"summary", "root_causes", "lessons"},
        "OPS_CHAT": {"answer"},
        "OPS_CHAT_LOCAL": {"answer"},
        "WHATIF_SIMULATION": {"scenarios"},
        "TRADE_POSTMORTEM": {"summary"},
        "WEEKLY_SUMMARY": {"summary"},
    }
    required = required_by_prompt.get(prompt_type, set())
    if not required:
        return True
    present = {key for key in required if parsed.get(key) not in (None, "", [], {})}
    if len(present) >= max(1, min(2, len(required))):
        return True
    return False

# --- GLOBAL CONCURRENCY LOCK ---
_OLLAMA_LOCK = asyncio.Lock()

async def query_ai(prompt_type: str, context: Dict[str, Any], cache_ttl_minutes: int = 60, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    """Main entry point with CPU Protection for Batam."""
    model = PROMPT_OLLAMA_MODEL.get(prompt_type, OLLAMA_DEFAULT_MODEL)
    is_heavy = "7b" in model or "deep" in model.lower()

    if is_heavy:
        async with _OLLAMA_LOCK:
            return await _execute_query_logic(prompt_type, context, cache_ttl_minutes, force_refresh)
    else:
        return await _execute_query_logic(prompt_type, context, cache_ttl_minutes, force_refresh)

async def _execute_query_logic(prompt_type: str, context: Dict[str, Any], cache_ttl_minutes: int = 60, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    template = PROMPT_TEMPLATES.get(prompt_type, "Analyze this context:\n{context}")
    prompt = _render_prompt(template, context)
    data_hash = hashlib.md5(json.dumps(context, sort_keys=True).encode()).hexdigest()[:8]
    candidates = _candidate_providers(prompt_type)
    runtime_sig = hashlib.md5(
        json.dumps(
            {
                "template": template,
                "candidates": [
                    {"name": provider, "model": _provider_model(provider, prompt_type)}
                    for provider in candidates
                ],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:8]
    cache_key = f"{prompt_type}_{runtime_sig}_{data_hash}"
    if not force_refresh:
        cached = _get_from_cache(cache_key, cache_ttl_minutes)
        if cached:
            return cached
    for provider in candidates:
        response = await _call_provider(provider, prompt, prompt_type=prompt_type)
        if not response:
            continue
        _increment_usage(provider)
        parsed = _extract_json_object(response)
        if not isinstance(parsed, dict):
            _set_provider_cooldown(provider, AI_EMPTY_COOLDOWN_SEC, "invalid_json")
            continue
        parsed.setdefault("provider", provider)
        parsed.setdefault("model", _provider_model(provider, prompt_type))
        if not _response_has_minimum_schema(prompt_type, parsed):
            _set_provider_cooldown(provider, AI_EMPTY_COOLDOWN_SEC, "invalid_schema")
            continue
        _save_to_cache(cache_key, parsed)
        return parsed
    if force_refresh:
        return AI_SAFE_FALLBACK
    
    # Emergency Fallback: If all candidates failed, try a final local lightweight poll
    if "ollama" not in candidates:
        response = await _call_provider("ollama", prompt, prompt_type=prompt_type)
        if response:
            parsed = _extract_json_object(response)
            if isinstance(parsed, dict):
                return parsed

    return _latest_prompt_cache(prompt_type) or AI_SAFE_FALLBACK


async def query_ai_consensus(context: Dict[str, Any], ticker: str = "BTC/IDR") -> Optional[Dict[str, Any]]:
    """
    Sovereign Council Consensus Debate.
    """
    hawk = await query_ai("MOMENTUM_HAWK", {"ticker": ticker, "signal": context})
    sentinel = await query_ai("RISK_SENTINEL", {"ticker": ticker, "context": context})
    
    return await query_ai("COUNCIL_SPEAKER", {
        "ticker": ticker,
        "hawk_view": hawk,
        "sentinel_view": sentinel
    }, force_refresh=True)


async def query_ai_debate(prompt_type: str, context: Dict[str, Any], debate_rounds: int = 1, cache_ttl_minutes: int = 60) -> Optional[Dict[str, Any]]:
    """
    Enhanced Multi-turn Debate with Hallucination Check.
    """
    # Caching check
    template = PROMPT_TEMPLATES.get(prompt_type, "")
    data_hash = hashlib.md5(json.dumps(context, sort_keys=True).encode()).hexdigest()[:8]
    cache_key = f"DEBATE_{prompt_type}_{debate_rounds}_{data_hash}"
    
    cached = _get_from_cache(cache_key, cache_ttl_minutes)
    if cached:
        return cached

    # 1. Initial Thesis
    thesis = await query_ai(prompt_type, context, force_refresh=True)
    if not thesis or thesis.get("is_fallback"):
        return thesis or AI_SAFE_FALLBACK
    
    current_thesis = thesis
    for r in range(debate_rounds):
        # 2. Self-Correction / Critique
        critique_context = {
            "original_context": context,
            "thesis_to_critique": current_thesis,
            "instruction": f"Round {r+1}: Critically analyze this thesis for logical gaps, overconfidence, or missing market risks."
        }
        critique = await query_ai("BRAIN_CRITIC", critique_context, force_refresh=True)
        
        if not critique or critique.get("verdict") == "APPROVE":
            break
            
        # 3. Refined Synthesis
        refined_context = {
            "original_context": context,
            "thesis": current_thesis,
            "critique": critique,
            "instruction": "Integrate the critique to produce a more robust, battle-hardened decision."
        }
        current_thesis = await query_ai(prompt_type, refined_context, force_refresh=True)
        
    if current_thesis:
        _save_to_cache(cache_key, current_thesis)
        
    return current_thesis


def get_provider_status() -> Dict[str, Dict[str, Any]]:
    state = _load_rate_state()
    provider_state = _load_provider_state().get("providers", {})
    counts = state.get("counts", {})
    summary: Dict[str, Dict[str, Any]] = {}
    for name, config in PROVIDERS.items():
        used = counts.get(name, 0)
        limit = config["daily_limit"]
        runtime_state = provider_state.get(name) if isinstance(provider_state.get(name), dict) else {}
        cooldown_remaining = max(0.0, float(runtime_state.get("cooldown_until") or 0.0) - time.time())
        summary[name] = {
            "configured": bool(_provider_api_key(name)),
            "model": str(config["model"]),
            "priority": int(config["priority"]),
            "used": used,
            "remaining": max(0, limit - used),
            "pct_used": round((used / limit) * 100, 1),
            "available": cooldown_remaining <= 0.0,
            "cooldown_remaining_sec": int(round(cooldown_remaining)),
            "last_failure_reason": str(runtime_state.get("last_failure_reason") or ""),
            "last_failure_at": str(runtime_state.get("last_failure_at") or ""),
            "last_success_at": str(runtime_state.get("last_success_at") or ""),
        }
        if str(name).lower() == "ollama":
            summary[name]["profiles"] = {
                "fast_model": OLLAMA_FAST_MODEL,
                "default_model": OLLAMA_DEFAULT_MODEL,
                "deep_model": OLLAMA_DEEP_MODEL,
                "fast_timeout_sec": OLLAMA_FAST_TIMEOUT_SEC,
                "default_timeout_sec": OLLAMA_DEFAULT_TIMEOUT_SEC,
                "deep_timeout_sec": OLLAMA_DEEP_TIMEOUT_SEC,
                "fast_keep_alive": OLLAMA_FAST_KEEP_ALIVE,
                "default_keep_alive": OLLAMA_DEFAULT_KEEP_ALIVE,
                "deep_keep_alive": OLLAMA_DEEP_KEEP_ALIVE,
            }
    return summary


def get_rate_summary() -> Dict[str, Dict[str, Any]]:
    summary = get_provider_status()
    return {
        name: {
            "used": data.get("used", 0),
            "remaining": data.get("remaining", 0),
            "pct_used": data.get("pct_used", 0.0),
        }
        for name, data in summary.items()
    }


if __name__ == "__main__":
    print("[COORDINATOR] Starting AI Coordinator service loop...", flush=True)
    while True:
        try:
            status = get_provider_status()
            print(f"[COORDINATOR][{time.strftime('%H:%M:%S')}] Active Providers: {list(status.keys())}", flush=True)
        except Exception as e:
            print(f"[COORDINATOR][ERROR] {e}", flush=True)
        time.sleep(60)
def handle_sigterm(signum, frame):
    """Graceful shutdown handler for AI Coordinator."""
    logger.info("👋 AI Coordinator shutting down gracefully...")
    # Add any cleanup logic here if needed
    exit(0)

# Register signal handlers
signal.signal(signal.SIGTERM, handle_sigterm)
signal.signal(signal.SIGINT, handle_sigterm)
