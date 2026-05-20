import pytest

from Core.Web3.solana_trending_scanner import SolanaTrendingScanner


@pytest.mark.anyio
async def test_trending_scanner_picks_best_candidate(monkeypatch, tmp_path):
    scanner = SolanaTrendingScanner()
    monkeypatch.setattr("Core.Web3.solana_trending_scanner.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.solana_trending_scanner.TREND_FILE", tmp_path / "solana_trending_candidates.json")

    async def fake_dex():
        return [{
            "symbol": "USRX",
            "mint": "mint1",
            "price_idr": 2,
            "change_24h_pct": 120.0,
            "change_5m_pct": 12.0,
            "change_1h_pct": 30.0,
            "market_cap_idr": 100000000,
            "liquidity_usd": 25000,
            "volume_5m_usd": 5000,
            "volume_1h_usd": 25000,
            "volume_24h_usd": 100000,
            "holders": 120,
            "age_minutes": 10080,
            "safety_score": 80,
            "source": "dexscreener",
        }]

    async def fake_jup():
        return []

    async def fake_detect(mint, pair_hint=None, trade_size_idr=0.0, balance_snapshot=None, **kwargs):
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

    monkeypatch.setattr(scanner, "_dexscreener_candidates", fake_dex)
    monkeypatch.setattr(scanner, "_jupiter_candidates", fake_jup)
    monkeypatch.setattr(scanner.route_detector, "detect_best_effort", fake_detect)
    async def fake_quote(mint, amount_raw, trade_size_idr=0.0, **kwargs):
        return {
            "route": "solana",
            "input_asset": "SOL",
            "output_asset": mint,
            "quote_ok": True,
            "expected_out": 1000,
            "slippage_pct": 0.5,
            "gas_idr": 1,
            "expires_at": "2030-01-01T00:00:00Z",
            "fresh_at": "2030-01-01T00:00:00Z",
            "fee_intelligence": {"gas_affordable": True, "gas_reason": "ok", "gas_fee_idr": 1, "gas_floor_idr": 1},
        }

    monkeypatch.setattr(scanner, "_quote_candidate", fake_quote)
    state = await scanner.scan()
    assert state["best_candidate"]["symbol"] == "USRX"
    assert state["candidates"][0]["decision"] == "APPROVE"
    assert state["candidates"][0]["reason"] == "ok"
    assert state["candidates"][0]["quote_ok"] is True
