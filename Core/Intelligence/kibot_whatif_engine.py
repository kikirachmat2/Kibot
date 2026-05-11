"""
KiBot What-If Simulation Engine
================================
Untuk setiap pair di CoinUniverse.tradeable, hitung 3 skenario:
1. BULL: harga naik 5% dalam 1 jam
2. BASE: harga flat / sedikit naik (0.5%)
3. BEAR: harga turun 3% dalam 30 menit

Untuk setiap skenario, hitung:
- Net PnL setelah fee (maker/taker)
- Expected value: E[PnL] = P(bull)*PnL_bull + P(base)*PnL_base + P(bear)*PnL_bear
- Kelly position size yang disarankan
- Risk/reward ratio

Update setiap 15 menit. Hasil disimpan ke state/whatif_results.json
dan di-serve via /api/state.whatIfSimulation
"""

import json, time, math, os
from datetime import datetime
from Intelligence.kibot_learning_engine import get_engine, ROUND_TRIP_MAKER, ROUND_TRIP_TAKER

WHATIF_PATH =  "Data/State/whatif_results.json"

def atomic_write_json(path: str, payload: dict) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def simulate_pair(pair: str, current_price: float, 
                   win_prob: float = 0.55) -> dict:
    """
    Hitung expected value untuk entry di harga sekarang.
    
    Skenario berbasis data historis pair (dari learning engine).
    """
    engine = get_engine()
    stats = engine.get(pair)
    
    # Pakai win_probability dari Bayesian engine kalau sudah ada data
    if stats.trade_count >= 3:
        win_prob = stats.win_probability
    
    bear_prob = 1 - win_prob
    
    # Estimasi PnL per skenario (gross, sebelum fee)
    bull_gross = stats.avg_win if stats.win_count > 0 else 0.015
    bear_gross = -abs(stats.avg_loss) if stats.loss_count > 0 else -0.008
    base_gross = 0.003  # flat / noise

    # Net setelah fee (asumsi limit order = maker)
    fee = ROUND_TRIP_MAKER
    bull_net = bull_gross - fee
    bear_net = bear_gross - fee
    base_net = base_gross - fee

    # Expected value
    ev = win_prob * bull_net + 0.15 * base_net + bear_prob * bear_net

    # Risk/reward
    rr = abs(bull_net / bear_net) if bear_net != 0 else 1.0

    # Kelly size berdasarkan EV
    kelly = stats.kelly_fraction() if ev > 0 else 0.0

    return {
        "pair": pair,
        "currentPrice": current_price,
        "winProbability": round(win_prob, 3),
        "expectedValue": round(ev, 5),
        "riskRewardRatio": round(rr, 2),
        "kellySizeRecommended": round(kelly, 3),
        "scenarios": {
            "bull": {"gross": bull_gross, "net": round(bull_net, 4), "prob": win_prob},
            "base": {"gross": base_gross, "net": round(base_net, 4), "prob": 0.15},
            "bear": {"gross": bear_gross, "net": round(bear_net, 4), "prob": bear_prob}
        },
        "verdict": "ENTRY_OK" if ev > 0.003 else ("MARGINAL" if ev > 0 else "SKIP"),
        "timestamp": datetime.utcnow().isoformat()
    }

def run_simulation(market_prices: dict) -> dict:
    """
    Jalankan simulasi untuk semua pair yang punya harga.
    market_prices: {"btc_idr": 1282178000, "fartcoin_idr": 3568, ...}
    """
    results = {}
    for pair, price in market_prices.items():
        if price > 0:
            results[pair] = simulate_pair(pair, price)
    
    # Sort by expected value, descending
    sorted_results = dict(sorted(
        results.items(),
        key=lambda x: x[1]["expectedValue"],
        reverse=True
    ))
    
    output = {
        "runAt": datetime.utcnow().isoformat(),
        "pairsSimulated": len(sorted_results),
        "topOpportunities": list(sorted_results.keys())[:5],
        "results": sorted_results
    }
    
    os.makedirs("state", exist_ok=True)
    atomic_write_json(WHATIF_PATH, output)
    
    return output
