import json
import time
import requests
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from ki_config import WIB, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

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
