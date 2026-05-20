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
    async def fake_detect_best_effort(self, mint, pair_hint=None, trade_size_idr=0.0, balance_snapshot=None, **kwargs):
        return {
            "updated_at": "now",
            "mint": mint,
            "route_type": "JUPITER_ROUTABLE",
            "buy_route_available": True,
            "sell_route_available": True,
            "jupiter_quote": {"quote_ok": True, "fee_intelligence": {"gas_affordable": True, "gas_reason": "ok"}},
            "pumpfun_curve": {"detected": False},
            "reason": "jupiter_quote_available",
        }
    monkeypatch.setattr("Core.Web3.pumpfun_live_runner.PumpfunRouteDetector.detect_best_effort", fake_detect_best_effort)
    async def fake_maybe_trade(self, candidate):
        return {"status": "READY", "reason": "jupiter_routable"}
    monkeypatch.setattr("Core.Web3.pumpfun_live_runner.PumpfunLiveRunner._maybe_trade", fake_maybe_trade)

    runner = PumpfunLiveRunner()
    state = await runner.tick()
    assert state["runner"] == "ACTIVE"
    assert state["latency"]["decision_source"] == "script_only"
