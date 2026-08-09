from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("KiBot.PairQuarantine")

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
PAIR_FILE = STATE_DIR / "pair_quarantine.json"
WIB = timezone(timedelta(hours=7))

# ---------------------------------------------------------------------------
# Configurable thresholds (via env vars)
# ---------------------------------------------------------------------------
COOLDOWN_CONSECUTIVE_LOSSES = int(os.environ.get("KIBOT_PAIR_COOLDOWN_LOSSES", "3"))
COOLDOWN_SECONDS = int(os.environ.get("KIBOT_PAIR_COOLDOWN_SECONDS", "86400"))  # 24h


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_pair_quarantine() -> Dict[str, Any]:
    return _read_json(PAIR_FILE, {"blocked_pairs": [], "records": {}, "updated_at": ""})


def _save_pair_quarantine(data: Dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(WIB).isoformat()
    _atomic_write_json(PAIR_FILE, data)


def cleanup_expired(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Remove expired quarantine entries.  Returns the cleaned data dict."""
    if data is None:
        data = load_pair_quarantine()
    now_ts = time.time()
    records = data.get("records", {})
    # Rebuild blocked_pairs from records that are still active
    still_blocked: List[str] = []
    for pair_key, rec in list(records.items()):
        until_ts = rec.get("until_ts", 0)
        if until_ts > now_ts:
            still_blocked.append(pair_key.upper())
        else:
            # Expired — keep record but mark inactive
            rec["active"] = False
    data["blocked_pairs"] = still_blocked
    return data


PERMANENT_BLOCKED_PAIRS = {"TRX/IDR", "TRX_IDR", "TRXIDR", "SHIB/IDR", "SHIB_IDR", "SHIBIDR", "BNB/IDR", "BNB_IDR", "BNBIDR"}


def is_quarantined(pair: str) -> bool:
    """Check if a pair is currently quarantined or permanently blacklisted (with TTL-aware expiry)."""
    pair_u = str(pair or "").upper().strip()
    pair_slash = pair_u.replace("_", "/")
    pair_underscore = pair_u.replace("/", "_")
    
    if pair_u in PERMANENT_BLOCKED_PAIRS or pair_slash in PERMANENT_BLOCKED_PAIRS or pair_underscore in PERMANENT_BLOCKED_PAIRS:
        return True

    data = load_pair_quarantine()
    data = cleanup_expired(data)
    _save_pair_quarantine(data)
    blocked = data.get("blocked_pairs", [])
    if not isinstance(blocked, list):
        return False
    return pair_u in {str(x).upper() for x in blocked}


def quarantine_pair(pair: str, reason: str, seconds: int = COOLDOWN_SECONDS) -> Dict[str, Any]:
    """Quarantine a specific pair for `seconds`.  Overwrites existing entry."""
    data = load_pair_quarantine()
    data = cleanup_expired(data)

    pair_u = str(pair or "").upper()
    now = time.time()
    until_ts = now + int(seconds)
    until_iso = (datetime.now(WIB) + timedelta(seconds=int(seconds))).isoformat()

    records = data.setdefault("records", {})
    records[pair_u] = {
        "pair": pair_u,
        "reason": reason,
        "quarantined_at": datetime.now(WIB).isoformat(),
        "until": until_iso,
        "until_ts": until_ts,
        "active": True,
    }

    # Rebuild blocked list
    data["blocked_pairs"] = [
        k.upper() for k, v in records.items()
        if v.get("until_ts", 0) > now and v.get("active", True)
    ]
    data["last_record"] = records[pair_u]
    _save_pair_quarantine(data)

    logger.warning(
        "🚫 Pair %s QUARANTINED for %ds — reason: %s (until %s)",
        pair_u, seconds, reason, until_iso,
    )
    return data


def record_pair_outcome(pair: str, pnl_idr: float) -> bool:
    """Record a trade outcome for a pair.  Returns True if quarantine was triggered.

    On loss: increment consecutive loss counter.  If counter reaches
    COOLDOWN_CONSECUTIVE_LOSSES → quarantine the pair.
    On win: reset the loss counter.

    This is the main entry point that wires the quarantine system to the
    trade lifecycle.
    """
    data = load_pair_quarantine()
    data = cleanup_expired(data)

    pair_u = str(pair or "").upper()
    records = data.setdefault("records", {})
    rec = records.get(pair_u, {})

    # Already quarantined — no-op
    if rec.get("active") and rec.get("until_ts", 0) > time.time():
        _save_pair_quarantine(data)
        return False

    loss_streak = int(rec.get("loss_streak", 0))
    total_trades = int(rec.get("total_trades", 0))
    total_losses = int(rec.get("total_losses", 0))

    total_trades += 1

    triggered = False
    if pnl_idr < 0:
        loss_streak += 1
        total_losses += 1
        if loss_streak >= COOLDOWN_CONSECUTIVE_LOSSES:
            quarantine_pair(
                pair_u,
                reason=f"{loss_streak} consecutive losses",
                seconds=COOLDOWN_SECONDS,
            )
            triggered = True
            loss_streak = 0  # reset after quarantine
            # Reload state written by quarantine_pair to avoid clobbering
            data = load_pair_quarantine()
            records = data.setdefault("records", {})
            rec = records.get(pair_u, {})
    else:
        loss_streak = 0  # win resets streak

    # Update record (preserve quarantine fields if present)
    rec.update({
        "pair": pair_u,
        "loss_streak": loss_streak,
        "total_trades": total_trades,
        "total_losses": total_losses,
        "last_outcome_at": datetime.now(WIB).isoformat(),
    })
    records[pair_u] = rec
    data["records"] = records
    _save_pair_quarantine(data)
    return triggered
