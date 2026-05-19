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
URGENT_FLAG_TTL_SEC = int(os.getenv("KIBOT_URGENCY_TTL_SEC", "3600"))
URGENT_FLAG_GRACE_SEC = int(os.getenv("KIBOT_URGENCY_GRACE_SEC", "300"))

DEFAULT_STRATEGY = {
    "version": "4.0.0",
    "last_updated": 0,
    "global_mode": "CONTROLLED_AGGRESSIVE",
    "daily_state": {
        "color": "RECOVERY",
        "hold_winners": False,
        "take_profit_multiplier": 1.0,
        "reason": "default",
    },
    "indodax": {
        "buy_threshold_pct": 0.35,
        "trailing_stop_pct": 0.3,
        "hard_stop_pct": 2.0,
        "max_exposure_idr": 0,
        "max_slots": 3,
        "min_confidence": 0.74,
        "allowed_pairs": ["*"],
        "take_profit_pct": 1.5,
        "min_profit_after_fee_pct": 0.3,
        "fee_maker_pct": 0.30,
        "fee_taker_pct": 0.55,
        "fee_pph_sell_pct": 0.21,
        "fee_roundtrip_pct": 1.02,
        "prefer_limit_order": True,
        "max_spread_pct": 0.55,
        "green_hold_tp_multiplier": 1.0,
        "reject_tick_traps": True,
        "min_price_levels_24h": 8,
        "max_tick_size_pct": 3.0,
    },
    "polymarket": {
        "min_liquidity_usd": 500,
        "max_bet_usd": 0,                 # 0 means "Use available USDC balance"
        "min_confidence": 0.78,
        "risk_limit": "AGGRESSIVE"
    }
}

def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on", "live", "production"}


def _sanitize_live_autonomous_strategy(strategy: Dict[str, Any]) -> Dict[str, Any]:
    """Keep stale defensive council snapshots from freezing live autonomous routing."""
    mode = os.getenv("KIBOT_TRADING_MODE", "controlled-live").strip().lower()
    live_enabled = _env_flag("KIBOT_LIVE_TRADING_ENABLED", "true" if mode == "controlled-live" else "false")
    force = _env_flag("KIBOT_FORCE_AUTONOMOUS_LIVE_STRATEGY", "true")
    if not force or not live_enabled:
        return strategy

    out = dict(strategy or {})
    indo = dict(out.get("indodax") or {})
    changed = []

    if indo.get("allowed_pairs") != ["*"]:
        indo["allowed_pairs"] = ["*"]
        changed.append("allowed_pairs_wildcard")
    if indo.get("pairs") != ["*"]:
        indo["pairs"] = ["*"]
        changed.append("pairs_wildcard")

    # Strategy/council scores are advisory in live autonomous mode; these bounds
    # preserve fatal risk controls while preventing old defensive snapshots from
    # locking the venue to BTC/ETH/USDT or a too-tight spread.
    min_conf_ceiling = float(os.getenv("KIBOT_LIVE_MAX_MIN_CONFIDENCE", "0.62") or 0.62)
    if float(indo.get("min_confidence", 1.0) or 1.0) > min_conf_ceiling:
        indo["min_confidence"] = min_conf_ceiling
        changed.append("min_confidence_bounded")

    spread_floor = float(os.getenv("KIBOT_INDODAX_LIVE_MAX_SPREAD_PCT", "1.35") or 1.35)
    if float(indo.get("max_spread_pct", 0.0) or 0.0) < spread_floor:
        indo["max_spread_pct"] = spread_floor
        changed.append("max_spread_widened")

    tp_floor = float(os.getenv("KIBOT_INDODAX_LIVE_TAKE_PROFIT_PCT", "2.2") or 2.2)
    if float(indo.get("take_profit_pct", 0.0) or 0.0) < tp_floor:
        indo["take_profit_pct"] = tp_floor
        changed.append("take_profit_widened")

    indo.setdefault("hard_stop_pct", float(os.getenv("KIBOT_INDODAX_LIVE_STOP_LOSS_PCT", "1.5") or 1.5))
    indo["council_mandate_required"] = False
    indo["live_autonomous_sanitized"] = True
    if changed:
        indo["live_autonomous_sanitize_reasons"] = changed
    out["indodax"] = indo
    out["global_mode"] = "LIVE_AUTONOMOUS_TRADING"
    return out


def load_strategy() -> Dict[str, Any]:
    """Load the current active strategy for fast script execution."""
    if not STRATEGY_FILE.exists():
        return _sanitize_live_autonomous_strategy(DEFAULT_STRATEGY)
    try:
        with open(STRATEGY_FILE, "r") as f:
            return _sanitize_live_autonomous_strategy(json.load(f))
    except Exception as e:
        logger.error(f"Failed to load strategy: {e}")
        return _sanitize_live_autonomous_strategy(DEFAULT_STRATEGY)

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
            data = json.load(f)
        if not isinstance(data, dict):
            return {"flag": "NORMAL"}

        flag = str(data.get("flag", "NORMAL")).upper()
        reason = str(data.get("reason", "")).strip()
        timestamp = float(data.get("timestamp", 0) or 0)
        age = time.time() - timestamp if timestamp else 0

        if flag in {"EMERGENCY_PAUSE", "FORCE_EXIT"}:
            if timestamp and age > URGENT_FLAG_TTL_SEC:
                logger.warning("🚦 Stale urgency flag expired automatically.")
                clear_urgency()
                return {"flag": "NORMAL"}
            if not reason and timestamp and age > URGENT_FLAG_GRACE_SEC:
                logger.warning("🚦 Empty urgency flag expired automatically.")
                clear_urgency()
                return {"flag": "NORMAL"}

        data.setdefault("flag", "NORMAL")
        return data
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
