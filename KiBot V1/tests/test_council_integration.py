import asyncio
import json
import logging
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from Core.sovereign_council import SovereignCouncil

logging.basicConfig(level=logging.INFO)

# Define async mock search methods
async def mock_async_search_dict(*args, **kwargs):
    return {}

async def mock_async_search_list(*args, **kwargs):
    return []

async def mock_async_search_str(*args, **kwargs):
    return ""

@pytest.mark.anyio
async def test_council_trading_deliberation():
    """
    Test SovereignCouncil's trading deliberation using robust offline mocks
    to ensure the core logic executes successfully without hitting any external APIs.
    """
    council = SovereignCouncil()

    # Define mock AI query responses based on roles
    async def mock_query_ai(role, payload):
        if role == "COUNCIL_ANTAGONIST":
            return {
                "best_alternative_action": "BUY",
                "best_alternative_ticker": "BTC/IDR",
                "best_alternative_confidence": 0.95
            }
        elif role == "COUNCIL_SPEAKER":
            return {
                "action": "BUY",
                "ticker": "BTC/IDR",
                "confidence": 0.92,
                "status": "EXECUTING",
                "decision_state": "ENTER",
                "trade_profile": "STANDARD"
            }
        return {}

    # Define trading signal context
    context = {
        "signals": [
            {
                "symbol": "BTC/IDR",
                "base_symbol": "BTC/IDR",
                "confidence": 0.92,
                "pump_probability": 0.88,
                "lag_sec": 0.5,
                "exchange": "BINANCE",
                "source": "UNIVERSAL_LEAD",
                "spread_pct": 0.1,
                "opportunity_score": 0.95,
                "trade_grade": "A",
                "lifecycle": "ACCUMULATION"
            }
        ],
        "system_health": {"status": "OK"},
        "market_context": {"regime": "BULL"}
    }

    # Patch both the LLM query function and the external search methods
    with patch("Core.sovereign_council.query_ai", new=mock_query_ai), \
         patch("Core.Intelligence.kibot_ai_search.AISearchService.tavily_search_async", new=mock_async_search_dict), \
         patch("Core.Intelligence.kibot_ai_search.AISearchService.serper_search_async", new=mock_async_search_dict), \
         patch("Core.Intelligence.kibot_ai_search.AISearchService.ddg_search_async", new=mock_async_search_list), \
         patch("Core.Intelligence.kibot_ai_search.AISearchService.finnhub_news_async", new=mock_async_search_list), \
         patch("Core.Intelligence.kibot_ai_search.AISearchService.brave_search_async", new=mock_async_search_dict), \
         patch("Core.Intelligence.kibot_ai_search.AISearchService.cryptopanic_news_async", new=mock_async_search_list):
        
        print("\n--- [TEST] Deliberating Trading Directive (Offline Mode) ---")
        directive = await council.deliberate_trading(context)
        print(f"RESULT: {json.dumps(directive, indent=2)}")
        
        assert isinstance(directive, dict), "Deliberation result must be a dictionary"
        assert "action" in directive, "Directive must contain 'action'"
        assert "ticker" in directive, "Directive must contain 'ticker'"

@pytest.mark.anyio
async def test_council_system_deliberation():
    """
    Test SovereignCouncil's system anomaly deliberation using offline mocks.
    """
    council = SovereignCouncil()

    async def mock_query_ai(role, payload):
        if role == "COUNCIL_WATCHMAN":
            return {
                "status": "ANOMALY",
                "severity": "HIGH",
                "reason": "Executor disconnected"
            }
        elif role == "COUNCIL_STRATEGIST":
            return {
                "action": "RESTART_SERVICE",
                "reasoning": "Restart executor systemd unit",
                "confidence": 0.98
            }
        return {}

    # Define system anomaly context
    issue = {
        "type": "ANOMALY",
        "snapshot": {
            "executor_status": "DISCONNECTED",
            "uptime": 3600,
            "memory_usage": "85%"
        }
    }

    with patch("Core.sovereign_council.query_ai", new=mock_query_ai):
        print("\n--- [TEST] Deliberating System Issue (Offline Mode) ---")
        system_action = await council.deliberate_system(issue)
        print(f"RESULT: {json.dumps(system_action, indent=2)}")
        
        assert isinstance(system_action, dict), "System action result must be a dictionary"
        assert system_action.get("action") == "RESTART_SERVICE", "SovereignCouncil failed to formulate correct recovery action"
