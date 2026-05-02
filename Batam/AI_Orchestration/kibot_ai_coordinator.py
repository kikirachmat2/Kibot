#!/usr/bin/env python3
"""
KiBot AI Coordinator
====================
Rate-limited AI router for non-trading subsystems.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv_early() -> None:
    candidates = [
        ROOT_DIR / ".env.kibot_manager",
        ROOT_DIR / ".env.kibot",
        ROOT_DIR / ".env.server",
        ROOT_DIR / ".env",
        ROOT_DIR.parent / ".env",
        ROOT_DIR.parent / "Shared" / "Ops" / ".env",
        Path(".env.kibot_manager"),
        Path(".env.kibot"),
        Path(".env.server"),
        Path(".env"),
        Path("../.env"),
        Path("../../.env"),
        Path("../../../.env"),
    ]
    explicit = os.getenv("KIBOT_MANAGER_ENV_FILE")
    if explicit:
        candidates.insert(0, Path(explicit))
    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def _env_first(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


_load_dotenv_early()

ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", Path(__file__).resolve().parent.parent))
STATE_DIR = ROOT / "state"
RATE_STATE_FILE = STATE_DIR / "ai_coordinator_rate.json"
RESPONSE_CACHE = STATE_DIR / "ai_coordinator_cache.json"
PROVIDER_STATE_FILE = STATE_DIR / "ai_coordinator_providers.json"
REQUEST_TIMEOUT_SEC = float(os.getenv("KIBOT_AI_COORDINATOR_TIMEOUT_SEC", "12"))
OLLAMA_FAST_MODEL = os.getenv("KIBOT_OLLAMA_FAST_MODEL", "qwen3:0.6b")
OLLAMA_DEFAULT_MODEL = os.getenv("KIBOT_OLLAMA_MODEL", "qwen3:1.7b")
OLLAMA_DEEP_MODEL = os.getenv("KIBOT_OLLAMA_DEEP_MODEL", "qwen3:8b")
OLLAMA_FAST_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_FAST_TIMEOUT_SEC", "30"))
OLLAMA_DEFAULT_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_TIMEOUT_SEC", "40"))
OLLAMA_DEEP_TIMEOUT_SEC = float(os.getenv("KIBOT_OLLAMA_DEEP_TIMEOUT_SEC", "120"))
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


def _canonical_ollama_chat_url(raw_url: str) -> str:
    fallback = "http://127.0.0.1:11435/api/chat"
    url = str(raw_url or "").strip() or fallback
    allow_direct = os.getenv("KIBOT_ALLOW_DIRECT_OLLAMA", "").strip().lower() in {"1", "true", "yes", "on"}
    if allow_direct:
        return url
    try:
        parsed = urlsplit(url)
    except Exception:
        return fallback
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 11434:
        print(
            "[KIBOT][AI_COORDINATOR] Direct Ollama upstream disabled; using gateway http://127.0.0.1:11435/api/chat",
            flush=True,
        )
        return fallback
    return url

PROVIDERS = {
    "ollama": {
        "daily_limit": 100000,
        "model": OLLAMA_DEFAULT_MODEL,
        "api_key_envs": ["OLLAMA_API_KEY", "KIBOT_OLLAMA_GATEWAY_TOKEN"],
        "base_url": _canonical_ollama_chat_url(os.getenv("KIBOT_OLLAMA_BASE_URL", "")),
        "priority": 1,
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
        "daily_limit": 5000,
        "model": "llama3.1-8b",
        "api_key_envs": ["CEREBRAS_API_KEY"],
        "base_url": "https://api.cerebras.ai/v1/chat/completions",
        "priority": 6,
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
        "daily_limit": 1000,
        "model": "mistral-tiny",
        "api_key_envs": ["MISTRAL_API_KEY"],
        "base_url": "https://api.mistral.ai/v1/chat/completions",
        "priority": 9,
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
}

PROMPT_PROVIDER_ORDER = {
    "BRAIN_CRITIC": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "PAIR_DISCOVERY": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "WHATIF_SIMULATION": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "TRADE_POSTMORTEM": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "VETO_ANALYSIS": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "WEEKLY_SUMMARY": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "NEWS_ANALYSIS": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "STRATEGY_GOVERNOR": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "STRATEGY_GOVERNOR_FAST": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "STRATEGY_GOVERNOR_MEDIUM": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "SOVEREIGN_DAILY_REVIEW": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "OPS_CHAT": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "OPS_CHAT_LOCAL": ["ollama", "groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton"],
    "INTELLIGENCE_SYNTHESIS": ["groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton", "ollama"],
    "TARGETED_VALIDATION": ["groq", "gemini", "deepseek", "sambanova", "cerebras", "together", "fireworks", "mistral", "nvidia", "openrouter", "deepinfra", "octoai", "novita", "perplexity", "cohere", "jina", "huggingface", "friendliai", "lepton", "ollama"],
}

PROMPT_TEMPLATES = {
    "BRAIN_CRITIC": (
        "You are KiBot's strategy critic.\n"
        "Watch symbols: {watch_symbols}\n"
        "Market pulse: {market_pulse}\n"
        "World model: {world_model}\n"
        "Daily target: {daily_target}\n"
        "Capital profile: {capital_profile}\n"
        "Rules: keep risk controls strict, prefer survival on tiny accounts. Your core philosophy is: 'Tekan kerugian, maksimalkan probabilitas keuntungan' and 'Sedikit demi sedikit lama lama jadi bukit'. Only turn opportunistic when market pulse and local learning strongly support it.\n"
        "Return compact JSON only with keys "
        "{{\"capital_posture\":\"DEFENSIVE|NEUTRAL|OPPORTUNISTIC\",\"risk_bias\":\"RISK_OFF|MIXED|RISK_ON\",\"confidence\":0.0,\"strategy_next\":\"...\",\"focus_symbols\":[...],\"do_not_do\":[...]}}"
    ),
    "PAIR_DISCOVERY": (
        "You are KiBot's universe expansion analyst.\n"
        "Goal: find new Indodax pairs worth tracking, but reject noisy pumps.\n"
        "Use only the candidate batch and market intel below.\n"
        "Trigger={trigger}\n"
        "Universe summary={universe_summary}\n"
        "Thresholds={thresholds}\n"
        "Candidate batch={candidates}\n"
        "Rules:\n"
        "- Only promote if volume is strong, chart is healthy, orderbook is not fake, and the candidate is not clearly overextended.\n"
        "- PERMANENT only when evidence is strong and consistent.\n"
        "- Use PROBATION when the setup looks promising but needs one more confirmation pass.\n"
        "- Use REJECT when the pair is illiquid, overextended, or the thesis is weak.\n"
        "- Keep reason under 30 words and never invent a pair that is not in the candidate batch.\n"
        "Return strict compact JSON only with keys "
        "{\"summary\":\"...\",\"candidates\":[{\"indodax_pair\":\"xxx_idr\",\"symbol\":\"XXX\",\"category\":\"LEAD_LAG|INDODAX_ONLY|FUTURES_PROXY|REJECT\",\"group\":\"BTC_FAMILY|ETH_FAMILY|SOL_FAMILY|MEME_COIN|AI_TOKEN|DEFI_TOKEN|GAMING|MICRO_CAP|STABLECOIN|UNKNOWN\",\"promotion\":\"PERMANENT|PROBATION|REJECT\",\"urgency\":\"NOW|WATCH|MONITOR\",\"confidence\":0.0,\"binance_pair\":null,\"reason\":\"...\"}]}"
    ),
    "VETO_ANALYSIS": (
        "Kamu adalah AI veto gate KiBot.\nSignal: {signal_data}\nMarket: {market_state}\nSystem: {system_health}\n"
        "Balas JSON {{\"approved\": true/false, \"reason\": \"...\", \"confidence\": 0.0}}"
    ),
    "INFRA_ANALYSIS": (
        "Analisis laporan infra Oracle Micro berikut, fokus hanya infrastruktur.\n{audit_report}\n"
        "Balas JSON {{\"critical_issues\": [], \"fixes\": [], \"optimization_tips\": []}}"
    ),
    "TRADE_POSTMORTEM": (
        "Analisis trade rugi berikut.\nTrade: {trade_data}\nMarket: {market_context}\nSystem: {system_state}\n"
        "Balas JSON {{\"root_cause\": \"...\", \"contributing_factors\": [], \"prevention\": \"...\", \"pattern\": \"...\"}}"
    ),
    "WEEKLY_SUMMARY": (
        "Buat insight mingguan untuk KiBot berdasarkan data berikut.\n{weekly_data}\n"
        "Balas JSON {{\"overall_assessment\": \"...\", \"top_issues\": [], \"opportunities_missed\": [], \"strengths\": [], \"recommendations\": [], \"next_week_focus\": \"...\"}}"
    ),
    "WHATIF_SIMULATION": (
        "Simulasikan skenario berikut.\nScenario: {scenario}\nContext: {context}\nParams: {params}\n"
        "Balas JSON {{\"likely_outcome\": \"...\", \"probability\": 0.0, \"risk_factors\": [], \"expected_pnl_pct\": 0.0, \"recommendation\": \"...\"}}"
    ),
    "NEWS_ANALYSIS": (
        "Analyze latest market news for {symbol}.\nNews: {news_dump}\n"
        "Categorize sentiment and impact on price movement.\n"
        "Return JSON {{\"sentiment\": \"BULLISH/BEARISH/NEUTRAL\", \"confidence\": 0.0, \"reason\": \"...\", \"action\": \"HOLD/SELL/STABLE\"}}"
    ),
    "STRATEGY_GOVERNOR": (
        "You are KiBot's sovereign strategy brain.\n"
        "Use the provided context to issue one adaptive plan for Indodax and Polymarket.\n"
        "Mission: preserve capital, stay adaptive, exploit clean opportunities, avoid preventable losses. Core Philosophy: 'Tekan kerugian, maksimalkan probabilitas keuntungan' and 'Sedikit demi sedikit lama lama jadi bukit'.\n"
        "Context market={market}\n"
        "critic={ai_critic}\n"
        "performance={performance}\n"
        "capital={capital_profile}\n"
        "scanner_feed={scanner_feed}\n"
        "runtime={runtime}\n"
        "world_model={world_model}\n"
        "memory={memory}\n"
        "pair_memory={pair_memory}\n"
        "polymarket={polymarket}\n"
        "whatif={whatif_top_opportunities}\n"
        "gate={gate}\n"
        "Return strict compact JSON only with keys "
        "plan_id,plan_ttl_sec,expires_at,reason,why,brain_mode,market_regime,capital_posture,confidence,"
        "confidence_decay_per_hour,fallback_if_expired,what_could_make_this_wrong,ops_alerts,"
        "strategy_mode,scanner,capital,risk,survival,execution,indodax,polymarket.\n"
        "Rules: do not invent unsupported pairs or budgets, keep tiny accounts conservative, and always include short risks."
    ),
    "STRATEGY_GOVERNOR_FAST": (
        "You are KiBot's FAST sovereign loop running every ~30 seconds.\n"
        "Use only the supplied working memory to refresh a short-lived plan.\n"
        "Prioritize: live health, active pairs, current capital, cross-market shifts, and whether entries should be blocked.\n"
        "Context profile={governor_profile}\n"
        "market={market}\n"
        "performance={performance}\n"
        "capital={capital_profile}\n"
        "runtime={runtime}\n"
        "scanner_feed={scanner_feed}\n"
        "world_model={world_model}\n"
        "polymarket={polymarket}\n"
        "gate={gate}\n"
        "Return strict compact JSON only with keys "
        "reason,why,brain_mode,strategy_mode,confidence,confidence_decay_per_hour,ops_alerts,"
        "what_could_make_this_wrong,indodax,polymarket.\n"
        "Inside indodax include only allow_entries,max_open_positions,budget_per_trade_idr,focus_pairs,avoid_pairs,preferred_style.\n"
        "Inside polymarket include only allow_execution,max_risk_pct,focus_markets.\n"
        "Keep why, ops_alerts, and what_could_make_this_wrong to max 2 short items.\n"
        "Keep focus_pairs and avoid_pairs to max 3 items, and focus_markets to max 2 short labels.\n"
        "Target a TTL of 180-600 seconds, keep output minimal, and never add prose outside JSON."
    ),
    "STRATEGY_GOVERNOR_MEDIUM": (
        "You are KiBot's MEDIUM sovereign loop running every ~5 minutes.\n"
        "Re-evaluate posture using working memory plus compact historical memory.\n"
        "Context profile={governor_profile}\n"
        "market={market}\n"
        "critic={ai_critic}\n"
        "performance={performance}\n"
        "capital={capital_profile}\n"
        "runtime={runtime}\n"
        "scanner_feed={scanner_feed}\n"
        "world_model={world_model}\n"
        "memory={memory}\n"
        "pair_memory={pair_memory}\n"
        "polymarket={polymarket}\n"
        "whatif={whatif_top_opportunities}\n"
        "gate={gate}\n"
        "Return strict JSON with the same plan schema as STRATEGY_GOVERNOR.\n"
        "Target a TTL of 600-1800 seconds. Adjust focus pairs, market regime, aggression mode, and risk posture."
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
        "You are KiBot's operator copilot.\n"
        "System state={system_state}\n"
        "Polymarket={polymarket}\n"
        "User message={user_message}\n"
        "Return compact JSON only with keys "
        "{\"answer\":\"...\",\"intent\":\"STATUS|COMMAND|QUESTION|POLYMARKET\",\"recommended_command\":\"...\",\"risk_note\":\"...\"}\n"
        "Rules: be concise, operational, and truthful; never invent balances or executions."
    ),
    "OPS_CHAT_LOCAL": (
        "You are KiBot's local Ollama operator copilot.\n"
        "System state={system_state}\n"
        "Polymarket={polymarket}\n"
        "User message={user_message}\n"
        "Return compact JSON only with keys "
        "{\"answer\":\"...\",\"intent\":\"STATUS|COMMAND|QUESTION|POLYMARKET\",\"recommended_command\":\"...\",\"risk_note\":\"...\"}\n"
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
}

PROMPT_OLLAMA_MODEL = {
    "BRAIN_CRITIC": OLLAMA_FAST_MODEL,
    "PAIR_DISCOVERY": OLLAMA_FAST_MODEL,
    "VETO_ANALYSIS": OLLAMA_FAST_MODEL,
    "NEWS_ANALYSIS": OLLAMA_FAST_MODEL,
    "STRATEGY_GOVERNOR": OLLAMA_FAST_MODEL,
    "STRATEGY_GOVERNOR_FAST": OLLAMA_FAST_MODEL,
    "STRATEGY_GOVERNOR_MEDIUM": OLLAMA_FAST_MODEL,
    "SOVEREIGN_DAILY_REVIEW": OLLAMA_DEEP_MODEL,
    "OPS_CHAT": OLLAMA_FAST_MODEL,
    "OPS_CHAT_LOCAL": OLLAMA_FAST_MODEL,
    "WHATIF_SIMULATION": OLLAMA_DEFAULT_MODEL,
    "TRADE_POSTMORTEM": OLLAMA_DEFAULT_MODEL,
    "WEEKLY_SUMMARY": OLLAMA_DEEP_MODEL,
}

PROMPT_OLLAMA_TIMEOUT = {
    "BRAIN_CRITIC": OLLAMA_FAST_TIMEOUT_SEC,
    "PAIR_DISCOVERY": OLLAMA_FAST_TIMEOUT_SEC,
    "VETO_ANALYSIS": OLLAMA_FAST_TIMEOUT_SEC,
    "NEWS_ANALYSIS": OLLAMA_FAST_TIMEOUT_SEC,
    "STRATEGY_GOVERNOR": OLLAMA_FAST_TIMEOUT_SEC,
    "STRATEGY_GOVERNOR_FAST": OLLAMA_FAST_TIMEOUT_SEC,
    "STRATEGY_GOVERNOR_MEDIUM": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "SOVEREIGN_DAILY_REVIEW": OLLAMA_DEEP_TIMEOUT_SEC,
    "OPS_CHAT": OLLAMA_FAST_TIMEOUT_SEC,
    "OPS_CHAT_LOCAL": OLLAMA_FAST_TIMEOUT_SEC,
    "WHATIF_SIMULATION": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "TRADE_POSTMORTEM": OLLAMA_DEFAULT_TIMEOUT_SEC,
    "WEEKLY_SUMMARY": OLLAMA_DEEP_TIMEOUT_SEC,
}

PROMPT_OLLAMA_KEEP_ALIVE = {
    "BRAIN_CRITIC": OLLAMA_FAST_KEEP_ALIVE,
    "PAIR_DISCOVERY": OLLAMA_FAST_KEEP_ALIVE,
    "VETO_ANALYSIS": OLLAMA_FAST_KEEP_ALIVE,
    "NEWS_ANALYSIS": OLLAMA_FAST_KEEP_ALIVE,
    "STRATEGY_GOVERNOR": OLLAMA_FAST_KEEP_ALIVE,
    "STRATEGY_GOVERNOR_FAST": OLLAMA_FAST_KEEP_ALIVE,
    "STRATEGY_GOVERNOR_MEDIUM": OLLAMA_FAST_KEEP_ALIVE,
    "SOVEREIGN_DAILY_REVIEW": OLLAMA_DEEP_KEEP_ALIVE,
    "OPS_CHAT": OLLAMA_FAST_KEEP_ALIVE,
    "OPS_CHAT_LOCAL": OLLAMA_FAST_KEEP_ALIVE,
    "WHATIF_SIMULATION": OLLAMA_DEFAULT_KEEP_ALIVE,
    "TRADE_POSTMORTEM": OLLAMA_DEFAULT_KEEP_ALIVE,
    "WEEKLY_SUMMARY": OLLAMA_DEEP_KEEP_ALIVE,
}

PROMPT_OLLAMA_OPTIONS = {
    "BRAIN_CRITIC": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "PAIR_DISCOVERY": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "VETO_ANALYSIS": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "NEWS_ANALYSIS": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "STRATEGY_GOVERNOR": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "STRATEGY_GOVERNOR_FAST": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
    "STRATEGY_GOVERNOR_MEDIUM": {"num_ctx": OLLAMA_FAST_NUM_CTX, "num_predict": OLLAMA_FAST_NUM_PREDICT},
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
    return _env_first(*[str(item) for item in envs])


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
    options = {"temperature": 0.2}
    options.update(PROMPT_OLLAMA_OPTIONS.get(prompt_type, {}))
    return options


def _call_provider(provider: str, prompt: str, prompt_type: str = "") -> Optional[str]:
    config = PROVIDERS[provider]
    api_key = _provider_api_key(provider)
    if not api_key:
        return None
    model = _provider_model(provider, prompt_type)
    timeout_sec = _provider_timeout(provider, prompt_type)
    try:
        if provider == "ollama":
            url = config["base_url"]
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
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
        elif provider == "gemini":
            url = f"{config['base_url']}/{config['model']}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            headers = {"Content-Type": "application/json"}
        else:
            url = config["base_url"]
            if provider == "cohere":
                payload = {
                    "model": model,
                    "message": prompt,
                    "temperature": 0.3,
                }
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
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
        request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            data = json.loads(response.read())
            if provider == "ollama":
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
    except urllib.error.HTTPError as error:
        if error.code in {401, 403, 404}:
            _set_provider_cooldown(provider, AI_AUTH_COOLDOWN_SEC, f"http_{error.code}")
        elif error.code == 429:
            _set_provider_cooldown(provider, AI_RATE_LIMIT_COOLDOWN_SEC, f"http_{error.code}")
        elif provider == "ollama":
            _set_provider_cooldown(provider, AI_OLLAMA_COOLDOWN_SEC, f"http_{error.code}")
        else:
            _set_provider_cooldown(provider, AI_NETWORK_COOLDOWN_SEC, f"http_{error.code}")
        return None
    except Exception as error:
        if provider == "ollama":
            _set_provider_cooldown(provider, AI_OLLAMA_COOLDOWN_SEC, type(error).__name__)
        else:
            _set_provider_cooldown(provider, AI_NETWORK_COOLDOWN_SEC, type(error).__name__)
        return None


def _extract_json_object(response: str) -> Optional[Dict[str, Any]]:
    response = str(response or "").strip()
    if not response:
        return None
    try:
        parsed = json.loads(response)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
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
        "BRAIN_CRITIC": {"capital_posture", "risk_bias", "confidence"},
        "PAIR_DISCOVERY": {"summary", "candidates"},
        "VETO_ANALYSIS": {"approved", "reason", "confidence"},
        "NEWS_ANALYSIS": {"summary"},
        "STRATEGY_GOVERNOR": {"brain_mode", "strategy_mode", "confidence"},
        "STRATEGY_GOVERNOR_FAST": {"brain_mode", "strategy_mode", "confidence"},
        "STRATEGY_GOVERNOR_MEDIUM": {"brain_mode", "strategy_mode", "confidence"},
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


def query_ai(prompt_type: str, context: Dict[str, Any], cache_ttl_minutes: int = 60, force_refresh: bool = False) -> Optional[Dict[str, Any]]:
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
        response = _call_provider(provider, prompt, prompt_type=prompt_type)
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
        return None
    return _latest_prompt_cache(prompt_type)


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
        if name == "ollama":
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
