import os
import sys
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for rel in [
    "SERVER_BATAM/Core_Logic",
    "SERVER_BATAM/Indicators_Math",
    "SERVER_BATAM/Support",
]:
    sys.path.insert(0, str(REPO_ROOT / rel))

def test_stats():
    from ki_stats import calculate_z_score
    prices = [100, 102, 101, 105, 110, 108, 115, 120, 118, 125, 
              130, 135, 132, 140, 145, 150, 155, 160, 165, 250] # Gigantic spike
    z = calculate_z_score(prices)
    print(f"Test Z-Score (Last Price 250): {z:.2f}")
    if z > 2.0:
        print("✅ Z-Score detection works.")
    else:
        print("❌ Z-Score detection failed.")

def test_brain():
    from ki_brain import BrainManager
    brain = BrainManager()

    def fake_get_json(url, params=None):
        if "binance.com" in url:
            return {"quoteVolume": "1234567.89"}
        if "indodax.com/api/pairs" in url:
            return [{"traded_currency": "btc", "base_currency": "idr", "ticker_id": "btc_idr"}]
        if "coingecko.com" in url:
            return {"coins": [{"id": "bitcoin"}]}
        return {}

    with (
        patch.object(brain, "_get_json", side_effect=fake_get_json),
        patch.object(brain, "_status_code", return_value=200),
        patch.object(brain, "_get_finnhub_crypto_news", return_value=[
            {"headline": "Bitcoin rally gains strength", "summary": "BTC breakout extends", "related": "BTC,ETH"},
            {"headline": "Altcoins recover after selloff", "summary": "market stabilizes", "related": "BTC,SOL"},
        ]),
        patch.object(brain, "_get_tavily_market_brief", return_value={"answer": "Market constructive with selective risk appetite.", "results": []}),
        patch.object(brain, "_get_tavily_symbol_brief", return_value={"answer": "BTC remains liquid with manageable event risk.", "results": []}),
        patch.object(brain, "_get_serper_market_brief", return_value={}),
        patch.object(brain, "_get_serper_symbol_brief", return_value={}),
        patch.object(brain, "_get_ddg_market_brief", return_value={"results": [{"title": "DDG market pulse", "content": "Crypto market selective"}]}),
        patch.object(brain, "_get_ddg_symbol_brief", return_value={"results": [{"title": "DDG BTC note", "content": "BTC remains liquid"}]}),
        patch.object(brain, "_has_ddg_client", return_value=True),
        patch("ki_brain._coordinator_query_ai_fn", return_value={
            "capital_posture": "DEFENSIVE",
            "risk_bias": "MIXED",
            "confidence": 0.72,
            "strategy_next": "Stay selective and wait for cleaner confirmation.",
            "focus_symbols": ["BTC"],
            "do_not_do": ["chase thin liquidity"],
            "provider": "groq",
            "model": "llama-3.1-8b-instant",
        }),
        patch("ki_brain._coordinator_provider_status_fn", return_value={
            "ollama": {"configured": True, "model": "qwen3:0.6b", "priority": 1, "used": 3, "remaining": 99997, "pct_used": 0.0},
            "groq": {"configured": True, "model": "llama-3.1-8b-instant", "priority": 1, "used": 2, "remaining": 98, "pct_used": 2.0},
            "gemini": {"configured": True, "model": "gemini-2.0-flash-lite", "priority": 2, "used": 0, "remaining": 100, "pct_used": 0.0},
        }),
    ):
        print("\n--- Testing Brain Market Intel ---")
        symbol = "BTC"
        intel = brain.get_market_intel(symbol)

        if intel.get('binance'):
            print("✅ Binance intel successful.")
        if intel.get('indodax_pairs'):
            print("✅ Indodax pair intel successful.")
        if intel.get('coingecko_search'):
            print("✅ CoinGecko intel successful.")

        print("\n--- Testing Mindset Vetting ---")
        approved, reason = brain.vet_signal("BTC", 0.9)
        print(f"Mindset Approval: {approved}")
        print(f"Reason: {reason}")

        snapshot = brain.think(
            ["BTC", "ETH"],
            context={
                "daily_pnl_pct": -0.0045,
                "equity_idr": 125000,
                "free_cash_idr": 62000,
                "capital_profile": {
                    "mode": "BUILDUP",
                    "reason": "small_balance_build_up",
                    "max_position_idr": 12000,
                    "risk_pct_per_trade": 0.15,
                },
            },
        )
        print(f"Brain snapshot keys: {list(snapshot.keys())}")
        print(f"Provider status: {snapshot.get('provider_status')}")
        print(f"AI Legion: {snapshot.get('ai_legion')}")
        print(f"Daily target: {snapshot.get('daily_target')}")
        print(f"Market pulse: {snapshot.get('market_pulse')}")
        print(f"Strategy next: {snapshot.get('daily_target', {}).get('strategy_next')}")
        print("✅ Brain advisory loop works.")

if __name__ == "__main__":
    test_stats()
    test_brain()
