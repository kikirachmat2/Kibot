import os
import json
import time
from pathlib import Path

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "state" / "dynamic_config.json"

# Default values
_DEFAULTS = {
    "KIBOT_Z_SCORE_THRESHOLD": 2.2,
    "KIBOT_MAX_PAIR_LOSS": 2,
    "KIBOT_STALE_SIGNAL_MS": 3000
}

def get_param(key: str, default=None):
    """Get a parameter, checking dynamic config first, then environment."""
    # 1. Try dynamic file
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text())
            if key in data:
                return data[key]
        except:
            pass
    
    # 2. Try environment (loaded from .env by ki_config)
    env_val = os.getenv(key)
    if env_val is not None:
        # Try to cast to float/int if possible
        try:
            if "." in env_val: return float(env_val)
            return int(env_val)
        except:
            return env_val
            
    # 3. Use internal defaults
    return _DEFAULTS.get(key, default)

def set_param(key: str, value):
    """Update a dynamic parameter and persist to file."""
    data = {}
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text())
        except:
            pass
    
    data[key] = value
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(data, indent=2))
    print(f"[v7][DYNAMIC_CONFIG] Updated {key} -> {value}", flush=True)
    
    # Optional: Logic to report changes can be added here
    pass

def sync_from_performance(pnl_metrics: dict):
    """
    AI Logic to adjust parameters based on performance.
    Example: If WinRate < 40%, increase Z-Score threshold.
    """
    win_rate = pnl_metrics.get("win_rate", 1.0)
    current_z = get_param("KIBOT_Z_SCORE_THRESHOLD")
    
    if win_rate < 0.40:
        # Too many losses, be stricter
        new_z = min(current_z + 0.1, 3.5)
        if new_z != current_z:
            set_param("KIBOT_Z_SCORE_THRESHOLD", round(new_z, 2))
    elif win_rate > 0.70:
        # Doing great, can afford to be slightly looser
        new_z = max(current_z - 0.05, 1.8)
        if new_z != current_z:
            set_param("KIBOT_Z_SCORE_THRESHOLD", round(new_z, 2))
