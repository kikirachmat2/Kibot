import json
import hashlib
import hmac
import os
import time
from pathlib import Path

def _get_signing_key() -> bytes:
    return os.getenv("KIBOT_SECRET", "SOVEREIGN_DEFAULT_SECRET").encode()

def initialize_learning_state():
    # Healthy seed data for major pairs
    seed_data = {
        "btc_idr": {
            "pair": "btc_idr",
            "alpha": 15.0,
            "beta": 10.0,
            "trade_count": 25,
            "win_count": 15,
            "loss_count": 10,
            "sum_wins": 0.45,
            "sum_losses": 0.20,
            "ema_pnl": 0.01,
            "last_trade_ts": time.time(),
            "cooldown_until_ts": 0.0,
            "regime_stats": {"NORMAL": {"count": 25, "sum_pnl": 0.25}},
            "lessons": ["Consistently reacts to 4H VWAP", "Avoid entry during high exchange inflow"]
        },
        "eth_idr": {
            "pair": "eth_idr",
            "alpha": 12.0,
            "beta": 8.0,
            "trade_count": 20,
            "win_count": 12,
            "loss_count": 8,
            "sum_wins": 0.35,
            "sum_losses": 0.15,
            "ema_pnl": 0.008,
            "last_trade_ts": time.time(),
            "cooldown_until_ts": 0.0,
            "regime_stats": {"NORMAL": {"count": 20, "sum_pnl": 0.20}},
            "lessons": ["Correlated with BTC momentum", "Strong support at previous week low"]
        }
    }
    
    payload = json.dumps(seed_data, indent=2)
    key = _get_signing_key()
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    
    state_path = Path("SERVER_BATAM/state/learning_state.json")
    state_path.write_text(f"{payload}|{signature}")
    print(f"Successfully initialized and signed {state_path}")

if __name__ == "__main__":
    initialize_learning_state()
