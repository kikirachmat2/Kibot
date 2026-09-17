"""
KiBot V2 Backtest Data Loader.
Provides robust historical OHLCV data fetching, gap validation, disk caching,
and multi-market alignment between Indodax and Binance.
"""
from __future__ import annotations

import gzip
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd
import requests

logger = logging.getLogger("KiBotV2.Backtest.DataLoader")

# Default cache directory inside KiBot V2/backtest/cache
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent / "cache"


def _get_bar_seconds(tf: str) -> int:
    """Converts timeframe string to interval in seconds."""
    clean = str(tf).strip().lower()
    if clean in ("60", "1h", "60m"):
        return 3600
    if clean in ("15", "15m"):
        return 900
    if clean in ("1d", "d"):
        return 86400
    try:
        return int(clean) * 60
    except ValueError:
        return 3600


def _validate_no_gaps(df: pd.DataFrame, symbol: str, bar_seconds: int) -> None:
    """
    Validates that there are no missing bars in consecutive timestamps.
    Raises ValueError if any gap > 1 bar is detected.
    """
    if len(df) <= 1:
        return
    diffs = df["timestamp_utc"].diff().dropna()
    gap_mask = diffs > bar_seconds
    if gap_mask.any():
        bad_indices = gap_mask[gap_mask].index
        first_bad = bad_indices[0]
        prev_ts = df.loc[first_bad - 1, "timestamp_utc"]
        curr_ts = df.loc[first_bad, "timestamp_utc"]
        missing_count = int((curr_ts - prev_ts) / bar_seconds) - 1
        raise ValueError(
            f"Data gap detected for {symbol}: {missing_count} missing bar(s) "
            f"between {prev_ts} and {curr_ts} (expected step: {bar_seconds}s)."
        )


def _load_cache(cache_path: Path) -> Optional[pd.DataFrame]:
    """Reads DataFrame from disk cache if present."""
    if not cache_path.exists():
        return None
    try:
        if cache_path.suffix == ".parquet":
            df = pd.read_parquet(cache_path)
        else:
            df = pd.read_csv(cache_path, compression="gzip")
        logger.info(f"[DataLoader] Loaded cached {len(df)} rows from {cache_path.name}")
        return df
    except Exception as e:
        logger.warning(f"[DataLoader] Cache read failed for {cache_path}: {e}")
        return None


def _save_cache(df: pd.DataFrame, cache_path: Path) -> None:
    """Atomically saves DataFrame to disk cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    try:
        if cache_path.suffix == ".parquet":
            df.to_parquet(temp_path, index=False)
        else:
            df.to_csv(temp_path, compression="gzip", index=False)
        os.replace(temp_path, cache_path)
        logger.info(f"[DataLoader] Cached {len(df)} rows to {cache_path.name}")
    except Exception as e:
        logger.error(f"[DataLoader] Failed to save cache {cache_path}: {e}")
        if temp_path.exists():
            temp_path.unlink()


def fetch_indodax_ohlcv(
    symbol: str,
    tf: str,
    from_ts: int,
    to_ts: int,
    cache_dir: Optional[Path] = None,
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """
    Fetch hourly OHLCV from Indodax TradingView API.
    Returns DataFrame with columns:
      [timestamp_utc, open, high, low, close, volume]
    Caches to backtest/cache/indodax/.
    Idempotent: if cached, reads from disk.
    Sorted by timestamp_utc ascending.
    Raises ValueError if any gap > 1 bar.
    """
    clean_sym = symbol.upper().replace("/", "").strip()
    norm_tf = "60" if str(tf).lower() in ("60", "1h", "60m") else str(tf)
    bar_seconds = _get_bar_seconds(norm_tf)

    root_cache = cache_dir or DEFAULT_CACHE_DIR
    cache_file = root_cache / "indodax" / f"{clean_sym}_{norm_tf}_{from_ts}_{to_ts}.csv.gz"

    cached_df = _load_cache(cache_file)
    if cached_df is not None:
        _validate_no_gaps(cached_df, clean_sym, bar_seconds)
        return cached_df

    url = f"https://indodax.com/tradingview/history_v2?symbol={clean_sym}&tf={norm_tf}&from={from_ts}&to={to_ts}"
    http = session or requests.Session()
    logger.info(f"[DataLoader] Fetching Indodax {clean_sym} ({norm_tf}) from {from_ts} to {to_ts}...")
    resp = http.get(url, timeout=20)
    resp.raise_for_status()

    raw_data = resp.json()
    if not isinstance(raw_data, list) or not raw_data:
        raise ValueError(f"No OHLCV data returned from Indodax for {clean_sym} ({from_ts} -> {to_ts})")

    records = []
    for item in raw_data:
        records.append({
            "timestamp_utc": int(item["Time"]),
            "open": float(item["Open"]),
            "high": float(item["High"]),
            "low": float(item["Low"]),
            "close": float(item["Close"]),
            "volume": float(item.get("Volume", 0.0)),
        })

    df = pd.DataFrame(records)
    df.sort_values(by="timestamp_utc", ascending=True, inplace=True)
    df.drop_duplicates(subset=["timestamp_utc"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    _validate_no_gaps(df, clean_sym, bar_seconds)
    _save_cache(df, cache_file)
    return df


def fetch_binance_ohlcv(
    symbol: str,
    tf: str,
    from_ts: int,
    to_ts: int,
    cache_dir: Optional[Path] = None,
    session: Optional[requests.Session] = None,
    proxy: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fetch hourly OHLCV from Binance Public Kline REST API.
    Returns DataFrame with columns:
      [timestamp_utc, open, high, low, close, volume]
    Caches to backtest/cache/binance/.
    Idempotent: if cached, reads from disk.
    Supports HTTP/SOCKS5 proxy via BINANCE_PROXY or BINANCE_PROXY_HOST env vars,
    or SSH SOCKS tunnel (e.g. ssh -D 1080 to SG1).
    Raises ValueError if any gap > 1 bar.
    """
    clean_sym = symbol.upper().replace("/", "").strip()
    if not clean_sym.endswith("USDT"):
        clean_sym = f"{clean_sym}USDT"
    norm_tf = "1h" if str(tf).lower() in ("60", "1h", "60m") else str(tf)
    bar_seconds = _get_bar_seconds(norm_tf)

    root_cache = cache_dir or DEFAULT_CACHE_DIR
    cache_file = root_cache / "binance" / f"{clean_sym}_{norm_tf}_{from_ts}_{to_ts}.csv.gz"

    cached_df = _load_cache(cache_file)
    if cached_df is not None:
        _validate_no_gaps(cached_df, clean_sym, bar_seconds)
        return cached_df

    # Configure proxy if running from local machine blocked by Indonesian ISP
    active_proxy = proxy or os.getenv("BINANCE_PROXY") or os.getenv("BINANCE_PROXY_HOST")
    proxies_dict = None
    if active_proxy:
        proxies_dict = {"http": active_proxy, "https": active_proxy}

    http = session or requests.Session()
    base_url = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
    
    # Binance returns max 1000 bars per call -> paginate from_ts to to_ts
    records = []
    current_start_ms = int(from_ts * 1000)
    end_ms = int(to_ts * 1000)

    logger.info(f"[DataLoader] Fetching Binance {clean_sym} ({norm_tf}) from {from_ts} to {to_ts}...")
    while current_start_ms < end_ms:
        req_url = f"{base_url}/api/v3/klines"
        params = {
            "symbol": clean_sym,
            "interval": norm_tf,
            "startTime": current_start_ms,
            "endTime": end_ms,
            "limit": 1000,
        }
        resp = http.get(req_url, params=params, proxies=proxies_dict, timeout=15)
        resp.raise_for_status()
        chunk = resp.json()
        if not chunk or not isinstance(chunk, list):
            break

        for k in chunk:
            ts_sec = int(k[0] // 1000)
            if ts_sec > to_ts:
                continue
            records.append({
                "timestamp_utc": ts_sec,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })

        last_open_ms = int(chunk[-1][0])
        next_start_ms = last_open_ms + (bar_seconds * 1000)
        if next_start_ms <= current_start_ms:
            break
        current_start_ms = next_start_ms

    if not records:
        raise ValueError(f"No OHLCV data returned from Binance for {clean_sym} ({from_ts} -> {to_ts})")

    df = pd.DataFrame(records)
    df.sort_values(by="timestamp_utc", ascending=True, inplace=True)
    df.drop_duplicates(subset=["timestamp_utc"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    _validate_no_gaps(df, clean_sym, bar_seconds)
    _save_cache(df, cache_file)
    return df


def align_indodax_binance(indodax_df: pd.DataFrame, binance_df: pd.DataFrame) -> pd.DataFrame:
    """
    Inner join on timestamp_utc.
    Returns aligned DataFrame with prefixes:
      indo_open, indo_high, indo_low, indo_close, indo_volume
      binance_open, binance_high, binance_low, binance_close, binance_volume
    Plus derived features:
      indo_return_1h = (indo_close - indo_open) / indo_open
      binance_return_1h = (binance_close - binance_open) / binance_open
      dislocation_1h = binance_return_1h - indo_return_1h
    Reports row count before/after alignment, and % overlap.
    """
    indo_clean = indodax_df.copy()
    bina_clean = binance_df.copy()

    indo_cols = {c: f"indo_{c}" for c in ["open", "high", "low", "close", "volume"]}
    bina_cols = {c: f"binance_{c}" for c in ["open", "high", "low", "close", "volume"]}

    indo_clean.rename(columns=indo_cols, inplace=True)
    bina_clean.rename(columns=bina_cols, inplace=True)

    len_indo = len(indo_clean)
    len_bina = len(bina_clean)

    aligned = pd.merge(indo_clean, bina_clean, on="timestamp_utc", how="inner")
    aligned.sort_values(by="timestamp_utc", ascending=True, inplace=True)
    aligned.reset_index(drop=True, inplace=True)

    len_aligned = len(aligned)
    max_len = max(len_indo, len_bina) if max(len_indo, len_bina) > 0 else 1
    overlap_pct = (len_aligned / max_len) * 100.0

    logger.info(
        f"[DataLoader.Alignment] Rows before: Indodax={len_indo}, Binance={len_bina} | "
        f"Rows aligned={len_aligned} | Overlap: {overlap_pct:.2f}%"
    )

    # Calculate derived hourly returns and dislocation
    aligned["indo_return_1h"] = (aligned["indo_close"] - aligned["indo_open"]) / aligned["indo_open"]
    aligned["binance_return_1h"] = (aligned["binance_close"] - aligned["binance_open"]) / aligned["binance_open"]
    aligned["dislocation_1h"] = aligned["binance_return_1h"] - aligned["indo_return_1h"]

    return aligned
