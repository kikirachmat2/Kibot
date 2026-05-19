import pytest
from unittest.mock import AsyncMock, patch
from Core.Web3.web3_opportunity_scanner import Web3OpportunityScanner

@pytest.mark.anyio
async def test_web3_scanner_writes_state(tmp_path, monkeypatch):
    with patch.object(Web3OpportunityScanner, '_solana_health', AsyncMock(return_value={'ok': True})), \
         patch.object(Web3OpportunityScanner, '_base_health', AsyncMock(return_value={'ok': True, 'latest_block': 123})), \
         patch("Core.Web3.solana_trending_scanner.SolanaTrendingScanner.scan", AsyncMock(return_value={"updated_at": "now", "candidates": [], "best_candidate": {}, "rejected": [], "source": ["dexscreener", "jupiter"]})), \
         patch("Core.Web3.pumpfun_scanner.PumpfunScanner.scan", AsyncMock(return_value={"updated_at": "now", "candidates": [], "best_candidate": {}, "rejected": []})):
        scanner = Web3OpportunityScanner()
        res = await scanner.scan()
        assert 'best_opportunities' in res
        assert res['routes']['solana']['status'] == 'LIVE_READY'
