"""Coin category intelligence for KiBot's non-pump fallback routing.

This module is intentionally deterministic. The AI council may debate timing,
but the base category should remain stable and auditable across scanner,
council, executor, dashboard, and daily reports.
"""
from __future__ import annotations

from typing import Any, Dict


HIGH_LIQUIDITY_MAJOR = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "TRX", "LTC",
    "BCH", "LINK", "AVAX", "DOT", "SUI", "NEAR", "TON", "POL", "MATIC",
}

BTC_ETH_BETA = {
    "STX", "ORDI", "SATS", "RUNE", "ETC", "ARB", "OP", "STRK", "APT",
    "INJ", "SEI", "TIA", "JUP", "PYTH",
}

MEME_ROTATION = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "TURBO",
    "TROLLSOL", "HAPPY", "GIGA", "AVA", "MOG", "BRETT", "PNUT", "POPCAT",
}

AI_BIG_DATA = {
    "FET", "AI", "AGIX", "OCEAN", "RNDR", "RENDER", "TAO", "GRT", "ARKM",
    "WLD", "AIOZ", "NMR", "PHA", "CTXC", "AKT", "IO", "SAHARA",
}

RWA_DEFI = {
    "ONDO", "PENDLE", "ENA", "AAVE", "UNI", "MKR", "COMP", "LDO", "CRV",
    "SNX", "JTO", "JST", "OM", "CFG",
}

STABLE_OR_QUOTE = {"USDT", "USDC", "DAI", "BIDR", "IDR"}


def normalize_symbol(symbol: str) -> str:
    raw = str(symbol or "").upper().strip()
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if "_" in raw:
        raw = raw.split("_", 1)[0]
    if raw in STABLE_OR_QUOTE:
        return raw
    return raw.strip()


def classify_coin_category(symbol: str) -> Dict[str, Any]:
    """Return the fallback category policy for a coin base symbol."""
    base = normalize_symbol(symbol)
    if not base:
        return _policy("UNKNOWN", 99, False, "avoid", "Symbol kosong atau tidak dikenal.")
    if base in STABLE_OR_QUOTE:
        return _policy("AVOID_STABLE", 99, False, "avoid", "Stable/quote asset bukan target alpha.")
    if base in HIGH_LIQUIDITY_MAJOR:
        return _policy(
            "HIGH_LIQUIDITY_MAJOR",
            1,
            True,
            "green_builder",
            "Likuiditas besar, cocok untuk fallback saat tidak ada pump bersih.",
        )
    if base in BTC_ETH_BETA:
        return _policy(
            "BTC_ETH_BETA",
            2,
            True,
            "beta_rotation",
            "Beta ke BTC/ETH atau narasi major, boleh dipakai untuk rotasi bertahap.",
        )
    if base in AI_BIG_DATA:
        return _policy(
            "AI_BIG_DATA",
            3,
            True,
            "narrative_rotation",
            "Narasi AI/data dapat dipakai bila heatmap dan web-intel mendukung.",
        )
    if base in RWA_DEFI:
        return _policy(
            "RWA_DEFI",
            4,
            True,
            "sector_rotation",
            "DeFi/RWA boleh dipakai saat sektor sedang hangat dan orderbook sehat.",
        )
    if base in MEME_ROTATION:
        return _policy(
            "MEME_ROTATION",
            5,
            True,
            "short_scalp_only",
            "Meme boleh dikejar hanya saat liquidity, spread, dan momentum valid.",
        )
    return _policy(
        "LOCAL_MOMENTUM",
        6,
        True,
        "short_scalp_only",
        "Koin lokal/Indodax-only: wajib pendek, evidence harus kuat, jangan jadi hold pasif.",
    )


def category_score_adjustment(category: str, signal: Dict[str, Any] | None = None) -> float:
    """Small score nudge. This should never override price, liquidity, or exit safety."""
    cat = str(category or "").upper()
    signal = signal or {}
    spread = float(signal.get("spread_pct", 0.0) or 0.0)
    persistence = float(signal.get("persistence", 0.0) or 0.0)
    vol_ratio = float(signal.get("volume_ratio", signal.get("vol_ratio", 1.0)) or 1.0)

    if cat == "HIGH_LIQUIDITY_MAJOR":
        return 0.025
    if cat == "BTC_ETH_BETA":
        return 0.020
    if cat == "AI_BIG_DATA":
        return 0.015 if vol_ratio >= 1.1 else 0.005
    if cat == "RWA_DEFI":
        return 0.010
    if cat == "MEME_ROTATION":
        return 0.010 if spread <= 0.8 and persistence >= 0.58 and vol_ratio >= 1.25 else -0.015
    if cat == "LOCAL_MOMENTUM":
        return 0.005 if spread <= 0.9 and persistence >= 0.60 and vol_ratio >= 1.30 else -0.020
    return -0.030


def _policy(category: str, priority: int, allowed: bool, mode: str, reason: str) -> Dict[str, Any]:
    return {
        "category": category,
        "fallback_priority": priority,
        "allowed_for_green_builder": allowed,
        "default_mode": mode,
        "reason": reason,
        "unit_price_must_be_below_total_equity": True,
    }
