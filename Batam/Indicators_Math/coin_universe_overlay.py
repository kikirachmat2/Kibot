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
        "metadata": {},
    },
    "probation": {
        "lead_lag": {},
        "indodax_only": [],
        "metadata": {},
    },
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
        payload["permanent"]["metadata"] = dict(permanent.get("metadata") or {}) if isinstance(permanent.get("metadata"), dict) else {}
        
        probation = state.get("probation") if isinstance(state.get("probation"), dict) else {}
        payload["probation"]["lead_lag"] = dict(probation.get("lead_lag") or {}) if isinstance(probation.get("lead_lag"), dict) else {}
        payload["probation"]["indodax_only"] = list(probation.get("indodax_only") or []) if isinstance(probation.get("indodax_only"), list) else []
        payload["probation"]["metadata"] = dict(probation.get("metadata") or {}) if isinstance(probation.get("metadata"), dict) else {}
        
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


    return state

def check_binance_pair(base_symbol: str) -> Optional[str]:
    """Checks if a coin has a USDT pair on Binance."""
    import urllib.request
    target = f"{base_symbol.upper()}USDT"
    url = f"https://api.binance.com/api/v3/exchangeInfo?symbol={target}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            if r.status == 200:
                return target
    except:
        pass
    return None

def validate_tradability(pair_id: str, min_depth_idr: float = 20_000_000, max_spread_pct: float = 2.5) -> Dict[str, Any]:
    """
    Performs deep orderbook analysis to see if a coin is actually tradable.
    Returns {ok: bool, reason: str, spread: float, depth: float}
    """
    import urllib.request
    # Indodax depth API uses no underscore, e.g. btcidr
    api_pair = pair_id.replace("_", "")
    url = f"https://indodax.com/api/{api_pair}/depth"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            bids = data.get("buy", [])
            asks = data.get("sell", [])
            
            if not bids or not asks:
                return {"ok": False, "reason": "Empty orderbook"}
            
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread_pct = ((best_ask - best_bid) / best_ask) * 100
            
            if spread_pct > max_spread_pct:
                return {"ok": False, "reason": f"Spread too wide ({spread_pct:.2f}%)", "spread": spread_pct}
                
            # Depth check (top 5 levels)
            depth_buy = sum(float(b[0]) * float(b[1]) for b in bids[:5])
            depth_sell = sum(float(a[0]) * float(a[1]) for a in asks[:5])
            total_depth = depth_buy + depth_sell
            
            if total_depth < min_depth_idr:
                return {"ok": False, "reason": f"Insufficient depth ({total_depth/1e6:.1f}M IDR)", "depth": total_depth}
                
            return {"ok": True, "reason": "Liquid", "spread": spread_pct, "depth": total_depth}
    except Exception as e:
        return {"ok": False, "reason": f"API Error: {e}"}

def auto_discover_new_coins(min_vol_idr: float = 500_000_000) -> List[str]:
    """
    Fetches all Indodax tickers and adds liquid new coins to probation.
    Returns list of newly onboarded pairs.
    """
    import urllib.request
    state = load_overlay_state()
    onboarded = []
    
    # 1. Fetch Indodax Tickers (Summaries)
    try:
        url_sum = "https://indodax.com/api/summaries"
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
        req_sum = urllib.request.Request(url_sum, headers=headers)
        with urllib.request.urlopen(req_sum, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
            tickers = data.get("tickers", {})
            
        # 1b. Fetch Pair Metadata (for precision)
        url_meta = "https://indodax.com/api/pairs"
        req_meta = urllib.request.Request(url_meta, headers=headers)
        with urllib.request.urlopen(req_meta, timeout=10) as r:
            meta_list = json.loads(r.read().decode("utf-8"))
            meta_map = {m["id"]: m for m in meta_list if "id" in m}
    except Exception as e:
        print(f"[UNIVERSE] Fetch error: {e}")
        return []

    # 2. Existing Pairs (Permanent + Probation)
    existing_indodax = set()
    existing_indodax.update(state["permanent"]["lead_lag"].keys())
    existing_indodax.update(state["permanent"]["indodax_only"].keys())
    existing_indodax.update(state["probation"]["lead_lag"].keys())
    existing_indodax.update(state["probation"]["indodax_only"])

    # 3. Discovery Loop (Top 10 liquid candidates only to avoid rate limits)
    candidates = []
    for pair_id, info in tickers.items():
        if not pair_id.endswith("_idr"): continue
        if pair_id in existing_indodax: continue
        
        vol = float(info.get("vol_idr", 0))
        if vol < min_vol_idr: continue
        
        # SPREAD VETO (From Summary - 0 API Calls)
        try:
            buy = float(info.get("buy", 0))
            sell = float(info.get("sell", 0))
            if buy > 0 and sell > 0:
                spread = ((sell - buy) / sell) * 100
                if spread > 2.5:
                    print(f"[UNIVERSE] Skipped {pair_id}: Wide spread {spread:.2f}% (from summary)")
                    continue
        except: pass

        candidates.append((pair_id, vol))
        
    # Sort by volume descending
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    import time
    for pair_id, vol in candidates[:5]: # Cap to top 5 to be extra safe
        # Deep depth check (Requires 1 API call per candidate)
        valid = validate_tradability(pair_id)
        if not valid["ok"]:
            print(f"[UNIVERSE] Skipped {pair_id}: {valid['reason']}")
            time.sleep(1.0)
            continue
            
        # New liquid coin found!
        base = pair_id.replace("_idr", "")
        binance_pair = check_binance_pair(base)
        
        # Store metadata
        m_data = meta_map.get(pair_id, {})
        precision = m_data.get("price_precision", 2)
        state["probation"]["metadata"][pair_id] = {"price_decimals": precision}
        
        if binance_pair:
            state["probation"]["lead_lag"][pair_id] = binance_pair
            print(f"[UNIVERSE] Onboarded {pair_id} as LEAD_LAG (Binance: {binance_pair}, Precision: {precision})")
        else:
            state["probation"]["indodax_only"].append(pair_id)
            print(f"[UNIVERSE] Onboarded {pair_id} as INDODAX_ONLY (Precision: {precision})")
            
        onboarded.append(pair_id)
        time.sleep(1.0) # Anti-spam

    if onboarded:
        save_overlay_state(state)
        
    return onboarded

def get_active_universe() -> Dict[str, Any]:
    """Returns merged lead-lag, indodax-only, and metadata for runtime."""
    state = load_overlay_state()
    lead_lag = deepcopy(state["permanent"]["lead_lag"])
    lead_lag.update(state["probation"]["lead_lag"])
    
    indodax_only = list(state["permanent"]["indodax_only"].keys())
    indodax_only.extend(state["probation"]["indodax_only"])
    
    # Merge metadata
    metadata = deepcopy(state["permanent"]["metadata"])
    metadata.update(state["probation"]["metadata"])
    
    # Merge sectors
    sectors = deepcopy(state["permanent"]["pair_sectors"])
    
    return {
        "lead_lag": lead_lag,
        "indodax_only": list(set(indodax_only)),
        "metadata": metadata,
        "sectors": sectors
    }
