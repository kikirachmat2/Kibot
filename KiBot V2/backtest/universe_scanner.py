"""
KiBot V2 Dynamic Universe Scanner.
Scans all active Indodax IDR pairs, correlates with Binance USDT pairs,
computes 7-day liquidity and spread metrics, and selects tradable universe.
Caches results to backtest/cache/universe/ with 24-hour validity.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Tuple
import requests

logger = logging.getLogger("KiBotV2.Backtest.UniverseScanner")

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache" / "universe"
INDODAX_API_PAIRS = "https://indodax.com/api/pairs"
INDODAX_API_TICKERS = "https://indodax.com/api/ticker_all"
BINANCE_API_EXCHANGE_INFO = "https://api.binance.com/api/v3/exchangeInfo"


def fetch_all_indodax_pairs(session: Optional[requests.Session] = None) -> List[str]:
    """
    Fetch all active IDR pairs from Indodax API.
    Returns sorted list of symbols like ['BTCIDR', 'ETHIDR', ...].
    """
    http = session or requests.Session()
    resp = http.get(INDODAX_API_PAIRS, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    pairs_data = resp.json()

    idr_pairs = []
    for p in pairs_data:
        pair_id = p.get("id", "").upper().replace("_", "")
        # Indodax IDR pairs typically end with 'idr' and traded_currency is 'idr'
        if pair_id.endswith("IDR") and p.get("traded_currency", "").lower() == "idr":
            idr_pairs.append(pair_id)

    idr_pairs.sort()
    logger.info(f"[UniverseScanner] Found {len(idr_pairs)} active IDR pairs on Indodax.")
    return idr_pairs


def fetch_all_binance_usdt_pairs(session: Optional[requests.Session] = None) -> Set[str]:
    """
    Fetch all actively trading USDT pairs from Binance API.
    Returns set like {'BTCUSDT', 'ETHUSDT', ...}.
    """
    http = session or requests.Session()
    try:
        base_url = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
        url = f"{base_url}/api/v3/exchangeInfo"
        proxy = os.getenv("BINANCE_PROXY") or os.getenv("BINANCE_PROXY_HOST")
        proxies = {"http": proxy, "https": proxy} if proxy else None

        resp = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, proxies=proxies, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        usdt_pairs = set(
            s["symbol"]
            for s in data.get("symbols", [])
            if s["symbol"].endswith("USDT") and s.get("status") == "TRADING"
        )
        logger.info(f"[UniverseScanner] Found {len(usdt_pairs)} active USDT pairs on Binance.")
        return usdt_pairs
    except Exception as e:
        logger.warning(f"[UniverseScanner] Could not fetch Binance pairs directly ({e}). Using empty set or fallback.")
        return set()


def build_pair_mapping(indodax_pairs: List[str], binance_pairs: Set[str]) -> Dict[str, Optional[str]]:
    """
    Map Indodax pair to Binance symbol.
    Return dict: {"BTCIDR": "BTCUSDT", "ETHIDR": "ETHUSDT", "XYZIDR": None}.
    """
    mapping: Dict[str, Optional[str]] = {}
    for p in indodax_pairs:
        clean = p.upper().replace("_", "").replace("/", "").strip()
        if clean.endswith("IDR"):
            base = clean[:-3]
            candidate = f"{base}USDT"
            if candidate in binance_pairs:
                mapping[clean] = candidate
            else:
                mapping[clean] = None
        else:
            mapping[clean] = None

    matched_count = sum(1 for v in mapping.values() if v is not None)
    logger.info(f"[UniverseScanner] Mapped {matched_count}/{len(mapping)} Indodax pairs to Binance.")
    return mapping


def fetch_indodax_ticker_snapshots(session: Optional[requests.Session] = None) -> Dict[str, Dict[str, Any]]:
    """
    Fetches 24h ticker summary from Indodax ticker_all endpoint.
    Returns dict keyed by normalized uppercase symbol (e.g. 'BTCIDR').
    """
    http = session or requests.Session()
    resp = http.get(INDODAX_API_TICKERS, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    raw = resp.json().get("tickers", {})

    normalized: Dict[str, Dict[str, Any]] = {}
    for k, v in raw.items():
        sym = k.upper().replace("_", "")
        normalized[sym] = v
    return normalized


def compute_liquidity_metrics(
    pair: str,
    ticker_snapshot: Optional[Dict[str, Any]] = None,
    session: Optional[requests.Session] = None,
) -> Dict[str, float]:
    """
    Compute liquidity score for a pair:
    - avg_daily_volume_idr
    - avg_spread_pct (from buy/sell quote)
    - depth_2pct_idr (approximate proxy from volume)
    """
    snap = ticker_snapshot
    if snap is None:
        all_snaps = fetch_indodax_ticker_snapshots(session)
        snap = all_snaps.get(pair.upper().replace("_", ""), {})

    try:
        vol_idr = float(snap.get("vol_idr", 0.0))
        buy = float(snap.get("buy", 0.0))
        sell = float(snap.get("sell", 0.0))

        if buy > 0 and sell >= buy:
            spread_pct = ((sell - buy) / buy) * 100.0
        else:
            spread_pct = 999.0

        # Approximate 2% depth as 1% of 24h volume
        depth_2pct = vol_idr * 0.01

        return {
            "avg_daily_volume_idr": vol_idr,
            "avg_spread_pct": round(spread_pct, 4),
            "depth_2pct_idr": round(depth_2pct, 2),
        }
    except Exception as e:
        logger.warning(f"[UniverseScanner] Error computing liquidity for {pair}: {e}")
        return {
            "avg_daily_volume_idr": 0.0,
            "avg_spread_pct": 999.0,
            "depth_2pct_idr": 0.0,
        }


def select_tradable_universe(
    min_volume_idr: float = 10_000_000.0,
    max_spread_pct: float = 0.80,
    exclude_stables: bool = True,
    cache_dir: Optional[Path] = None,
    session: Optional[requests.Session] = None,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Filters pairs that meet liquidity thresholds:
    - 24h Volume IDR >= min_volume_idr
    - Spread % <= max_spread_pct
    - Optional: exclude fiat/stables (USDTIDR)
    Caches results for 24 hours.
    Returns list of dicts:
    [
      {
        "pair": "BTCIDR",
        "binance_pair": "BTCUSDT",
        "has_binance": True,
        "volume_idr": ...,
        "spread_pct": ...,
      },
      ...
    ]
    """
    root_cache = cache_dir or DEFAULT_CACHE_DIR
    cache_file = root_cache / "universe_cache.json"

    # Check 24-hour cache validity
    if not force_refresh and cache_file.exists():
        try:
            mtime = cache_file.stat().st_mtime
            if (time.time() - mtime) < 86400:  # 24 hours
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                logger.info(f"[UniverseScanner] Loaded {len(cached)} pairs from 24h cache.")
                return cached
        except Exception as e:
            logger.warning(f"[UniverseScanner] Could not read cache {cache_file}: {e}")

    http = session or requests.Session()
    indodax_pairs = fetch_all_indodax_pairs(http)
    binance_pairs = fetch_all_binance_usdt_pairs(http)
    mapping = build_pair_mapping(indodax_pairs, binance_pairs)
    tickers = fetch_indodax_ticker_snapshots(http)

    stables_blacklist = {"USDTIDR", "USDCIDR"} if exclude_stables else set()

    qualified = []
    for pair in indodax_pairs:
        if pair in stables_blacklist:
            continue

        snap = tickers.get(pair, {})
        metrics = compute_liquidity_metrics(pair, snap, http)

        vol = metrics["avg_daily_volume_idr"]
        spread = metrics["avg_spread_pct"]

        if vol >= min_volume_idr and spread <= max_spread_pct:
            b_sym = mapping.get(pair)
            qualified.append({
                "pair": pair,
                "binance_pair": b_sym,
                "has_binance": b_sym is not None,
                "volume_idr": vol,
                "spread_pct": spread,
                "depth_2pct_idr": metrics["depth_2pct_idr"],
            })

    # Sort descending by volume
    qualified.sort(key=lambda x: x["volume_idr"], reverse=True)

    # Save cache atomically
    root_cache.mkdir(parents=True, exist_ok=True)
    temp_file = cache_file.with_suffix(".tmp")
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(qualified, f, indent=2)
        os.replace(temp_file, cache_file)
        logger.info(f"[UniverseScanner] Cached {len(qualified)} qualified pairs to {cache_file}.")
    except Exception as e:
        logger.warning(f"[UniverseScanner] Cache write failed: {e}")

    return qualified
