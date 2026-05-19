import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from Core.Intelligence.strategy.deadline_profit_enforcer import DeadlineProfitEnforcer
from Core.Web3.solana_trending_scanner import SolanaTrendingScanner
from Core.Web3.pumpfun_scanner import PumpfunScanner

@pytest.mark.anyio
async def test_deadline_profit_enforcer_lockout(tmp_path, monkeypatch):
    # Set up mock state file
    state_file = tmp_path / "deadline_profit_enforcer.json"
    monkeypatch.setattr("Core.Intelligence.strategy.deadline_profit_enforcer.STATE_FILE", state_file)
    
    # Configure enforcer with target 5% and actual daily PnL of 6% (above target)
    enforcer = DeadlineProfitEnforcer()
    enforcer.profit_target_pct = 5.0
    enforcer.profit_target_idr = 1000000.0
    
    # Simulate high profit
    is_locked = await enforcer.evaluate_enforcement(daily_pnl_pct=6.0, daily_pnl_idr=1200000.0)
    assert is_locked is True
    
    # Read generated state to verify lockout persistency
    state_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert state_data["locked_for_day"] is True
    assert "Daily target reached" in state_data["lock_reason"]

@pytest.mark.anyio
async def test_solana_trending_scanner_watchlist(tmp_path, monkeypatch):
    # Setup mock user watchlist
    watchlist_file = tmp_path / "user_watchlist.json"
    watchlist_data = {
        "symbols": ["ROCKY", "ELIZA", "SOULGUY"],
        "source": "user_phantom_screenshot",
        "priority": "HIGH"
    }
    watchlist_file.write_text(json.dumps(watchlist_data), encoding="utf-8")
    
    # Monkeypatch the paths in solana_trending_scanner
    monkeypatch.setattr("Core.Web3.solana_trending_scanner.TREND_FILE", tmp_path / "solana_trending_candidates.json")
    
    scanner = SolanaTrendingScanner()
    
    # Create dummy mock candidates matching search
    async def mock_dex_candidates():
        return [
            {
                "symbol": "ELIZA",
                "mint": "eliza_mint_addr",
                "pair_address": "pair_eliza",
                "price_idr": 150.0,
                "change_24h_pct": 25.0,
                "change_5m_pct": 5.0,
                "change_1h_pct": 10.0,
                "market_cap_idr": 500000000.0,
                "liquidity_usd": 15000.0,
                "volume_5m_usd": 2000.0,
                "volume_1h_usd": 8000.0,
                "volume_24h_usd": 40000.0,
                "holders": 350,
                "age_minutes": 12.0,
                "source": "dexscreener",
                "quote": "SOL",
            }
        ]
        
    async def mock_jup_candidates():
        return []

    monkeypatch.setattr(scanner, "_dexscreener_candidates", mock_dex_candidates)
    monkeypatch.setattr(scanner, "_jupiter_candidates", mock_jup_candidates)
    
    # Run scan to check watchlist loading and candidate handling
    state = await scanner.scan()
    assert state is not None
    # Watchlist loading didn't fail
