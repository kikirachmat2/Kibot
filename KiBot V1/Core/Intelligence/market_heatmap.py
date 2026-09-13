"""Indodax market breadth and heatmap snapshot."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
HEATMAP_FILE = STATE_DIR / "market_heatmap.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _build_from_tickers(tickers: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for pair, ticker in (tickers or {}).items():
        if not str(pair).endswith("_idr") or not isinstance(ticker, dict):
            continue
        last = _f(ticker.get("last"))
        low = _f(ticker.get("low"), last)
        high = _f(ticker.get("high"), last)
        vol_idr = _f(ticker.get("vol_idr"))
        change_pct = ((last - low) / low * 100.0) if low > 0 else 0.0
        range_pos = ((last - low) / max(high - low, 1e-9)) if high > low else 0.0
        rows.append({
            "pair": pair.upper().replace("_", "/"),
            "last": last,
            "low": low,
            "high": high,
            "vol_idr": vol_idr,
            "change_from_low_pct": round(change_pct, 3),
            "range_position": round(max(0.0, min(1.0, range_pos)), 3),
        })

    green = [r for r in rows if r["change_from_low_pct"] > 0]
    # Filter out micro-penny tick noise (coins <= 10 IDR with negligible volume) from pump stats
    pump5 = [r for r in rows if r["change_from_low_pct"] >= 5.0 and (r.get("last", 0) > 10 or r.get("vol_idr", 0) >= 10_000_000)]
    pump10 = [r for r in rows if r["change_from_low_pct"] >= 10.0 and (r.get("last", 0) > 10 or r.get("vol_idr", 0) >= 25_000_000)]
    pump20 = [r for r in rows if r["change_from_low_pct"] >= 20.0 and (r.get("last", 0) > 10 or r.get("vol_idr", 0) >= 25_000_000)]

    # Filter top movers for meaningful liquidity (avoid 1-Rupiah tick jump on dead orderbooks)
    liquid_movers = [
        r for r in rows
        if r.get("change_from_low_pct", 0) > 0 and (
            (r.get("last", 0) > 10 and r.get("vol_idr", 0) >= 10_000_000) or
            (r.get("last", 0) <= 10 and r.get("vol_idr", 0) >= 50_000_000)
        )
    ]
    if len(liquid_movers) >= 3:
        top_movers = sorted(liquid_movers, key=lambda r: r["change_from_low_pct"], reverse=True)[:10]
    else:
        top_movers = sorted(rows, key=lambda r: r["change_from_low_pct"], reverse=True)[:10]
    top_volume = sorted(rows, key=lambda r: r["vol_idr"], reverse=True)[:10]

    if len(pump10) >= 12:
        breadth = "BROAD_RISK_ON"
    elif len(pump10) >= 4:
        breadth = "SELECTIVE"
    elif len(pump5) >= 1:
        breadth = "ISOLATED_PUMP"
    else:
        breadth = "RISK_OFF"

    return {
        "generated_at": time.time(),
        "pair_count": len(rows),
        "green_pairs": len(green),
        "red_pairs": max(0, len(rows) - len(green)),
        "pump_count_5pct": len(pump5),
        "pump_count_10pct": len(pump10),
        "pump_count_20pct": len(pump20),
        "top_movers": top_movers,
        "top_volume": top_volume,
        "market_breadth": breadth,
        "summary": f"{breadth}: {len(pump10)} pairs above +10%, {len(pump20)} above +20%",
    }


def fetch_indodax_heatmap(*, persist: bool = True, timeout: float = 8.0) -> Dict[str, Any]:
    try:
        resp = requests.get("https://indodax.com/api/summaries", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        heatmap = _build_from_tickers(data.get("tickers", {}) if isinstance(data, dict) else {})
    except Exception as exc:
        heatmap = {
            "generated_at": time.time(),
            "pair_count": 0,
            "green_pairs": 0,
            "red_pairs": 0,
            "pump_count_5pct": 0,
            "pump_count_10pct": 0,
            "pump_count_20pct": 0,
            "top_movers": [],
            "top_volume": [],
            "market_breadth": "UNKNOWN",
            "summary": f"heatmap_fetch_failed:{exc}",
        }
    if persist:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = HEATMAP_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(heatmap, indent=2), encoding="utf-8")
        tmp.replace(HEATMAP_FILE)
    return heatmap


def load_heatmap(default_fetch: bool = False) -> Dict[str, Any]:
    try:
        if HEATMAP_FILE.exists():
            data = json.loads(HEATMAP_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    if default_fetch:
        return fetch_indodax_heatmap()
    return {"market_breadth": "UNKNOWN", "top_movers": [], "top_volume": []}
