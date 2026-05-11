import json
import os
import time
import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger("SovereignState")

# Strategy State Path
from Core.Support.ki_config import STATE_DIR
STRATEGY_FILE = STATE_DIR / "active_strategy.json"
URGENCY_FILE = STATE_DIR / "urgency_flag.json"

DEFAULT_STRATEGY = {
    "version": "3.1.0",
    "last_updated": 0,
    "global_mode": "FULL_ATTACK", # Switched to FULL_ATTACK as per user request for aggressive trading
    "indodax": {
        "buy_threshold_pct": 0.5,         # More aggressive momentum entry
        "trailing_stop_pct": 0.25,        # Tighter trailing stop
        "hard_stop_pct": 2.0,             # Wider stop loss for volatility
        "max_exposure_idr": 0,            # 0 means "Use full available balance"
        "max_slots": 100,                  # Allow up to 100 parallel trades
        "min_confidence": 0.65,           # Hyper-aggressive threshold
        "allowed_pairs": ["*"]            # ["*"] means all coins are allowed
    },
    "polymarket": {
        "min_liquidity_usd": 500,
        "max_bet_usd": 0,                 # 0 means "Use available USDC balance"
        "min_confidence": 0.75,
        "risk_limit": "AGGRESSIVE"
    }
}

def load_strategy() -> Dict[str, Any]:
    """Load the current active strategy for fast script execution."""
    if not STRATEGY_FILE.exists():
        return DEFAULT_STRATEGY
    try:
        with open(STRATEGY_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load strategy: {e}")
        return DEFAULT_STRATEGY

def reset_strategy():
    """Reset to Default Strategy."""
    save_strategy(DEFAULT_STRATEGY)
    logger.info("♻️ STRATEGY RESET TO DEFAULTS")

def save_strategy(strategy: Dict[str, Any]):
    """Update the strategy from the Sovereign Council (Strategic Planning)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    strategy["last_updated"] = time.time()
    try:
        with open(STRATEGY_FILE, "w") as f:
            json.dump(strategy, f, indent=2)
        logger.info(f"🏛️ STRATEGY UPDATED: {strategy.get('global_mode')}")
    except Exception as e:
        logger.error(f"Failed to save strategy: {e}")

def set_urgency(flag: str, reason: str):
    """Set immediate urgency flags (e.g., EMERGENCY_STOP)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"flag": flag, "reason": reason, "timestamp": time.time()}
    with open(URGENCY_FILE, "w") as f:
        json.dump(data, f)
    logger.warning(f"🚨 URGENCY TRIGGERED: {flag} - {reason}")

def check_urgency() -> Dict[str, Any]:
    """Check for any active urgency flags."""
    if not URGENCY_FILE.exists():
        return {"flag": "NORMAL"}
    try:
        with open(URGENCY_FILE, "r") as f:
            return json.load(f)
    except:
        return {"flag": "NORMAL"}

def clear_urgency():
    """Clear existing urgency flags."""
    if URGENCY_FILE.exists():
        URGENCY_FILE.unlink()

def rotate_logs(log_file: Path, max_size_mb: int = 5):
    """Rotate log files if they exceed max_size_mb."""
    if log_file.exists() and log_file.stat().st_size > max_size_mb * 1024 * 1024:
        backup = log_file.with_suffix(".log.old")
        if backup.exists(): backup.unlink()
        log_file.rename(backup)

def extract_json_safe(response: str):
    """Stricter JSON extraction with provider fallback."""
    try:
        # 1. Direct Try
        parsed = json.loads(response)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    
    # 2. Markdown Block Cleaning
    if "```json" in response:
        try:
            content = response.split("```json")[1].split("```")[0].strip()
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

    # 3. Sliding Window Brace Matcher
    start = response.find("{")
    end = response.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            content = response[start:end+1]
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
    
    return None

def save_trade_result(symbol: str, profit_pct: float, reason: str):
    """Record trade result for Council learning loop."""
    history_file = STATE_DIR / "pnl_history.json"
    history = []
    if history_file.exists():
        try:
            with open(history_file, "r") as f:
                history = json.load(f)
        except: pass
    
    history.append({
        "timestamp": time.time(),
        "symbol": symbol,
        "profit_pct": profit_pct,
        "reason": reason
    })
    
    # Keep last 20 trades
    history = history[-20:]
    with open(history_file, "w") as f:
        json.dump(history, f, indent=2)

def load_pnl_history() -> list:
    history_file = STATE_DIR / "pnl_history.json"
    if not history_file.exists(): return []
    try:
        with open(history_file, "r") as f:
            return json.load(f)
    except: return []
