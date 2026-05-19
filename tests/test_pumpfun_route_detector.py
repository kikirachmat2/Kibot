import pytest

from Core.Web3.pumpfun_route_detector import PumpfunRouteDetector


@pytest.mark.anyio
async def test_detector_marks_jupiter_routable(monkeypatch, tmp_path):
    detector = PumpfunRouteDetector()
    monkeypatch.setattr("Core.Web3.pumpfun_route_detector.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.pumpfun_route_detector.ROUTE_STATE_FILE", tmp_path / "pumpfun_route_state.json")

    async def fake_quote(route, input_asset, output_asset, amount_raw):
        return {"quote_ok": True, "expected_out": 123, "slippage_pct": 0.4}

    monkeypatch.setattr(detector, "_quote_solana", lambda mint, amount_raw=1_000_000: fake_quote("solana", "", mint, amount_raw))
    state = await detector.detect("mint111")
    assert state["route_type"] == "JUPITER_ROUTABLE"
    assert state["buy_route_available"] is True
    assert state["sell_route_available"] is True


@pytest.mark.anyio
async def test_detector_blocks_bonding_curve_without_exit(monkeypatch, tmp_path):
    detector = PumpfunRouteDetector()
    monkeypatch.setattr("Core.Web3.pumpfun_route_detector.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.pumpfun_route_detector.ROUTE_STATE_FILE", tmp_path / "pumpfun_route_state.json")

    async def fake_quote(route, input_asset, output_asset, amount_raw):
        return {"quote_ok": False, "reason": "no route"}

    monkeypatch.setattr(detector, "_quote_solana", lambda mint, amount_raw=1_000_000: fake_quote("solana", "", mint, amount_raw))
    state = await detector.detect("mint222", pair_hint={"dexId": "pumpfun", "label": "pump.fun"})
    assert state["route_type"] == "PUMPFUN_BONDING_CURVE"
    assert state["buy_route_available"] is False
    assert state["sell_route_available"] is False
    assert state["reason"] == "no_exit_route"
