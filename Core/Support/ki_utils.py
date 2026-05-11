import json
import time
import requests
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

# Pathing resolved via PYTHONPATH=.
root = Path(__file__).resolve().parent.parent.parent

try:
    from Support.ki_config import WIB, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
except ImportError:
    # Fallback to local import if run as a script in the Support directory
    try:
        from ki_config import WIB, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    except ImportError:
        WIB = None
        TELEGRAM_BOT_TOKEN = None
        TELEGRAM_CHAT_ID = None

def get_wib_now() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=7)

def get_wib_str() -> str:
    return get_wib_now().strftime('%Y-%m-%d %H:%M:%S WIB')

def telegram_send(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[KI_UTILS][TELEGRAM][ERROR] {e}", flush=True)

def load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default if default is not None else {}

def save_json(path: Path, data: Any):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[KI_UTILS][JSON][ERROR] Failed to save {path}: {e}", flush=True)

def safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def bounded_append(target_list: list, item: Any, max_size: int = 200):
    """Appends to a list and ensures it does not exceed max_size (FIFO)."""
    target_list.append(item)
    if len(target_list) > max_size:
        del target_list[0]

def _env_first(*keys: str, default: str = "") -> str:
    import os
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return default

def sign_payload(payload_dict: dict, secret: str) -> str:
    """Generate HMAC-SHA256 signature for a dictionary."""
    import hmac, hashlib
    payload_str = json.dumps(payload_dict, sort_keys=True)
    return hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()

def verify_signature(payload_dict: dict, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature for a dictionary."""
    import hmac, hashlib
    if not signature: return False
    payload_str = json.dumps(payload_dict, sort_keys=True)
    expected = hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
