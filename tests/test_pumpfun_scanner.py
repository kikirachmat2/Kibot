import pytest

from Core.Web3.pumpfun_scanner import PumpfunScanner


@pytest.mark.anyio
async def test_pumpfun_scanner_rejects_no_exit_route(monkeypatch, tmp_path):
    scanner = PumpfunScanner()
    monkeypatch.setattr("Core.Web3.pumpfun_scanner.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.pumpfun_scanner.PUMPFUN_FILE", tmp_path / "pumpfun_candidates.json")

    async def fake_dex():
        return [{
            "symbol": "USRX",
            "mint": "mint_usrx",
            "pair_address": "pair1",
            "route_hint": "pumpfun",
            "age_seconds": 120,
            "market_cap_idr": 100000000,
            "liquidity_usd": 25000,
            "volume_5m_usd": 5000,
            "volume_1h_usd": 20000,
            "price_change_5m_pct": 10,
            "price_change_1h_pct": 40,
            "change_24h_pct": 100,
            "holders": 120,
            "pair": {"dexId": "pumpfun", "label": "pump.fun"},
        }]

    async def fake_detect(mint, pair_hint=None):
        return {
            "updated_at": "now",
            "mint": mint,
            "route_type": "PUMPFUN_BONDING_CURVE",
            "buy_route_available": False,
            "sell_route_available": False,
            "jupiter_quote": {},
            "pumpfun_curve": {"detected": True},
            "reason": "no_exit_route",
        }

    monkeypatch.setattr(scanner, "_dexscreener_candidates", fake_dex)
    monkeypatch.setattr(scanner.detector, "detect_best_effort", fake_detect)
    state = await scanner.scan()
    assert state["best_candidate"] == {}
    assert state["rejected"][0]["reason"] == "no_exit_route"


@pytest.mark.anyio
async def test_pumpfun_scanner_approves_jupiter_routable(monkeypatch, tmp_path):
    scanner = PumpfunScanner()
    monkeypatch.setattr("Core.Web3.pumpfun_scanner.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.pumpfun_scanner.PUMPFUN_FILE", tmp_path / "pumpfun_candidates.json")

    async def fake_dex():
        return [{
            "symbol": "rocky",
            "mint": "mint_rocky",
            "pair_address": "pair2",
            "route_hint": "jupiter",
            "age_seconds": 600,
            "market_cap_idr": 100000000,
            "liquidity_usd": 50000,
            "volume_5m_usd": 10000,
            "volume_1h_usd": 40000,
            "price_change_5m_pct": 12,
            "price_change_1h_pct": 22,
            "change_24h_pct": 90,
            "holders": 200,
            "pair": {"dexId": "raydium", "label": "raydium"},
        }]

    async def fake_detect(mint, pair_hint=None):
        return {
            "updated_at": "now",
            "mint": mint,
            "route_type": "JUPITER_ROUTABLE",
            "buy_route_available": True,
            "sell_route_available": True,
            "jupiter_quote": {"quote_ok": True},
            "pumpfun_curve": {"detected": False},
            "reason": "jupiter_quote_available",
        }

    async def fake_quote(self, route, input_asset, output_asset, amount_raw):
        return {"quote_ok": True, "expected_out": 1000, "slippage_pct": 0.4}

    monkeypatch.setattr(scanner, "_dexscreener_candidates", fake_dex)
    monkeypatch.setattr(scanner.detector, "detect_best_effort", fake_detect)
    monkeypatch.setattr("Core.Web3.pumpfun_scanner.Web3QuoteRouter.quote", fake_quote)
    state = await scanner.scan()
    assert state["best_candidate"]["symbol"] == "rocky"
    assert state["best_candidate"]["route_type"] == "JUPITER_ROUTABLE"
