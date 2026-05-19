import pytest

from Core.Web3.pumpfun_live_runner import PumpfunLiveRunner


@pytest.mark.anyio
async def test_pumpfun_runner_writes_latency(monkeypatch, tmp_path):
    monkeypatch.setattr("Core.Web3.pumpfun_live_runner.STATE_DIR", tmp_path)
    async def fake_scan(self):
        return {
            "updated_at": "now",
            "runner": "ACTIVE",
            "scan_interval_ms": 1000,
            "candidates_found": 1,
            "hot_queue": [{"symbol": "rocky", "mint": "mint1"}],
            "best_candidate": {
                "symbol": "rocky",
                "mint": "mint1",
                "route_type": "JUPITER_ROUTABLE",
                "can_buy": True,
                "can_sell": True,
                "decision": "APPROVE",
                "reason": "ok",
                "liquidity_usd": 50000,
                "slippage_pct": 0.4,
                "ev_pct": 3.2,
                "safety_score": 85,
            },
            "approved_candidates": [],
            "rejected": [],
            "current_action": "SCAN",
            "reason": "ok",
            "latency": {},
            "decision_source": "script_only",
        }

    monkeypatch.setattr("Core.Web3.pumpfun_live_runner.PumpfunFastScanner.scan", fake_scan)

    runner = PumpfunLiveRunner()
    state = await runner.tick()
    assert state["runner"] == "ACTIVE"
    assert state["latency"]["decision_source"] == "script_only"
