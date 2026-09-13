"""
Coin category intelligence for KiBot V2 Sector Diversification.
Ported and adapted from KiBot V1 Core/Intelligence/coin_category.py.

Provides deterministic sector classification for cryptocurrencies traded on Indodax.
Used by CapitalGovernor to prevent dangerous sector concentration (e.g. correlated meme coin exposure).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Set

HIGH_LIQUIDITY_MAJOR: Set[str] = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "TRX", "LTC",
    "BCH", "LINK", "AVAX", "DOT", "SUI", "NEAR", "TON", "POL", "MATIC",
}

BTC_ETH_BETA: Set[str] = {
    "STX", "ORDI", "SATS", "RUNE", "ETC", "ARB", "OP", "STRK", "APT",
    "INJ", "SEI", "TIA", "JUP", "PYTH",
}

MEME_ROTATION: Set[str] = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME", "TURBO",
    "TROLLSOL", "HAPPY", "GIGA", "AVA", "MOG", "BRETT", "PNUT", "POPCAT",
}

AI_BIG_DATA: Set[str] = {
    "FET", "AI", "AGIX", "OCEAN", "RNDR", "RENDER", "TAO", "GRT", "ARKM",
    "WLD", "AIOZ", "NMR", "PHA", "CTXC", "AKT", "IO", "SAHARA",
}

RWA_DEFI: Set[str] = {
    "ONDO", "PENDLE", "ENA", "AAVE", "UNI", "MKR", "COMP", "LDO", "CRV",
    "SNX", "JTO", "JST", "OM", "CFG",
}

STABLE_OR_QUOTE: Set[str] = {"USDT", "USDC", "DAI", "BIDR", "IDR"}


def normalize_symbol(symbol: str) -> str:
    """Normalizes pairs like 'DOGE/IDR', 'pepe_idr', 'btc' into clean uppercase base asset 'DOGE'."""
    raw = str(symbol or "").upper().strip()
    if "/" in raw:
        raw = raw.split("/", 1)[0]
    if "_" in raw:
        raw = raw.split("_", 1)[0]
    return raw.strip()


def classify_coin_category(symbol: str) -> Dict[str, Any]:
    """
    Returns full category policy dictionary for a given symbol.
    """
    base = normalize_symbol(symbol)
    if not base:
        return _policy("UNKNOWN", 99, False, "avoid", "Symbol empty or unknown.")
    if base in STABLE_OR_QUOTE:
        return _policy("AVOID_STABLE", 99, False, "avoid", "Stable/quote asset is not an alpha target.")
    if base in MEME_ROTATION:
        # Note: DOGE is both major and meme, priority is MEME_ROTATION for risk containment
        return _policy("MEME_ROTATION", 5, True, "short_scalp_only", "Meme coin: strictly limit concurrent exposure.")
    if base in HIGH_LIQUIDITY_MAJOR:
        return _policy("HIGH_LIQUIDITY_MAJOR", 1, True, "green_builder", "High liquidity major asset.")
    if base in BTC_ETH_BETA:
        return _policy("BTC_ETH_BETA", 2, True, "beta_rotation", "Beta to BTC/ETH major narratives.")
    if base in AI_BIG_DATA:
        return _policy("AI_BIG_DATA", 3, True, "narrative_rotation", "AI and big data narrative asset.")
    if base in RWA_DEFI:
        return _policy("RWA_DEFI", 4, True, "sector_rotation", "DeFi and Real World Asset category.")
    return _policy("LOCAL_MOMENTUM", 6, True, "short_scalp_only", "Local Indodax momentum / altcoin.")


def get_coin_category(symbol: str) -> str:
    """Fast helper returning just the category string name."""
    return classify_coin_category(symbol)["category"]


def _policy(category: str, priority: int, allowed: bool, mode: str, reason: str) -> Dict[str, Any]:
    return {
        "category": category,
        "priority": priority,
        "allowed": allowed,
        "default_mode": mode,
        "reason": reason,
    }
