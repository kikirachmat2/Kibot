from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List


ROOT_DIR = Path(__file__).resolve().parent.parent
STATE_ROOT = Path(os.getenv("KIBOT_MANAGER_STATE_DIR", str(ROOT_DIR / "state")))
OVERLAY_FILE = Path(
    os.getenv(
        "KIBOT_COIN_UNIVERSE_OVERLAY_FILE",
        str(STATE_ROOT / "coin_universe_overlay.json"),
    )
)

_DEFAULT_STATE: Dict[str, Any] = {
    "version": 1,
    "updated_at": "",
    "permanent": {
        "lead_lag": {},
        "indodax_only": {},
        "pair_sectors": {},
    },
    "probation": {},
    "review": {
        "last_review_at_epoch": 0.0,
        "last_review_reason": "",
        "last_batch_fingerprint": "",
        "last_result_count": 0,
    },
}

_STATE_LOCK = threading.RLock()


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def _normalise_state(state: Any) -> Dict[str, Any]:
    payload = deepcopy(_DEFAULT_STATE)
    if isinstance(state, dict):
        payload["version"] = int(state.get("version") or 1)
        payload["updated_at"] = str(state.get("updated_at") or "")
        permanent = state.get("permanent") if isinstance(state.get("permanent"), dict) else {}
        payload["permanent"]["lead_lag"] = dict(permanent.get("lead_lag") or {}) if isinstance(permanent.get("lead_lag"), dict) else {}
        payload["permanent"]["indodax_only"] = dict(permanent.get("indodax_only") or {}) if isinstance(permanent.get("indodax_only"), dict) else {}
        payload["permanent"]["pair_sectors"] = dict(permanent.get("pair_sectors") or {}) if isinstance(permanent.get("pair_sectors"), dict) else {}
        payload["probation"] = dict(state.get("probation") or {}) if isinstance(state.get("probation"), dict) else {}
        review = state.get("review") if isinstance(state.get("review"), dict) else {}
        payload["review"]["last_review_at_epoch"] = float(review.get("last_review_at_epoch") or 0.0)
        payload["review"]["last_review_reason"] = str(review.get("last_review_reason") or "")
        payload["review"]["last_batch_fingerprint"] = str(review.get("last_batch_fingerprint") or "")
        payload["review"]["last_result_count"] = int(review.get("last_result_count") or 0)
    return payload


def load_overlay_state() -> Dict[str, Any]:
    if not OVERLAY_FILE.exists():
        return deepcopy(_DEFAULT_STATE)
    try:
        raw = json.loads(OVERLAY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(_DEFAULT_STATE)
    return _normalise_state(raw)


def save_overlay_state(state: Dict[str, Any]) -> None:
    with _STATE_LOCK:
        payload = _normalise_state(state)
        payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _atomic_write(OVERLAY_FILE, payload)


def group_to_sector(group: str) -> str:
    normalized = str(group or "").strip().upper()
    mapping = {
        "BTC_FAMILY": "btc_family",
        "ETH_FAMILY": "eth_family",
        "SOL_FAMILY": "sol_family",
        "LEAD_LAG": "lead_lag",
        "MEME_COIN": "meme",
        "AI_TOKEN": "ai_token",
        "DEFI_TOKEN": "defi",
        "GAMING": "gaming",
        "MICRO_CAP": "micro_cap",
        "STABLECOIN": "stablecoin",
        "UNKNOWN": "unknown",
    }
    return mapping.get(normalized, normalized.lower() or "unknown")


def apply_overlay_to_runtime(
    lead_lag_pairs: Dict[str, str],
    indodax_only_pairs: List[str],
    pair_sectors: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    state = load_overlay_state()
    permanent = state.get("permanent") if isinstance(state.get("permanent"), dict) else {}
    overlay_lead_lag = permanent.get("lead_lag") if isinstance(permanent.get("lead_lag"), dict) else {}
    overlay_indodax = permanent.get("indodax_only") if isinstance(permanent.get("indodax_only"), dict) else {}
    overlay_sectors = permanent.get("pair_sectors") if isinstance(permanent.get("pair_sectors"), dict) else {}

    for pair_id, binance_pair in overlay_lead_lag.items():
        pair_key = str(pair_id or "").strip().lower()
        if pair_key and pair_key not in lead_lag_pairs:
            lead_lag_pairs[pair_key] = str(binance_pair or "").strip().upper()

    for pair_id in overlay_indodax.keys():
        pair_key = str(pair_id or "").strip().lower()
        if pair_key and pair_key not in indodax_only_pairs:
            indodax_only_pairs.append(pair_key)

    if pair_sectors is not None:
        for pair_id, sector in overlay_sectors.items():
            pair_key = str(pair_id or "").strip().lower()
            if pair_key and pair_key not in pair_sectors:
                pair_sectors[pair_key] = str(sector or "").strip().lower() or "unknown"

    return state
