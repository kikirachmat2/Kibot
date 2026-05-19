from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import aiohttp

from Core.Web3.web3_quote_router import Web3QuoteRouter

logger = logging.getLogger("PumpfunRouteDetector")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
ROUTE_STATE_FILE = STATE_DIR / "pumpfun_route_state.json"

JUPITER_SOL_MINT = "So11111111111111111111111111111111111111112"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_json(path: Path, payload: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _has_pumpfun_hint(payload: Dict[str, Any]) -> bool:
    text_bits = [
        payload.get("dexId"),
        payload.get("label"),
        payload.get("pairAddress"),
        payload.get("baseToken", {}).get("name"),
        payload.get("baseToken", {}).get("symbol"),
        payload.get("info", {}).get("website"),
        payload.get("info", {}).get("description"),
    ]
    haystack = " ".join(str(bit or "").lower() for bit in text_bits)
    return any(token in haystack for token in ("pump", "pumpfun", "pump.fun", "moonshot"))


class PumpfunRouteDetector:
    """Best-effort classifier for Solana meme routes.

    The detector intentionally refuses to over-claim support. If a sell path
    cannot be demonstrated with confidence, the route is classified as blocked.
    """

    def __init__(self) -> None:
        self.dexscreener_base = os.getenv("DEXSCREENER_API_BASE", "https://api.dexscreener.com/latest/dex/search?q=")
        self.route_state = self._blank_state()

    def _blank_state(self) -> Dict[str, Any]:
        return {
            "updated_at": "",
            "mint": "",
            "route_type": "UNSUPPORTED",
            "buy_route_available": False,
            "sell_route_available": False,
            "jupiter_quote": {},
            "pumpfun_curve": {},
            "reason": "",
        }

    async def _fetch_json(self, url: str) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=8) as resp:
                    if resp.status != 200:
                        return {}
                    return await resp.json()
        except Exception as exc:
            logger.debug("route detector fetch failed: %s", exc)
            return {}

    async def _dexscreener_pair(self, mint: str) -> Dict[str, Any]:
        if not mint:
            return {}
        data = await self._fetch_json(f"https://api.dexscreener.com/latest/dex/search?q={mint}")
        for pair in data.get("pairs", []) or []:
            if str(pair.get("chainId", "")).lower() != "solana":
                continue
            base = pair.get("baseToken", {}) or {}
            if str(base.get("address") or "").lower() == mint.lower():
                return pair
        return {}

    async def _quote_solana(self, mint: str, amount_raw: int = 1_000_000) -> Dict[str, Any]:
        router = Web3QuoteRouter()
        return await router.quote(
            route="solana",
            input_asset=JUPITER_SOL_MINT,
            output_asset=mint,
            amount_raw=amount_raw,
        )

    async def detect(self, mint: str, pair_hint: Dict[str, Any] | None = None) -> Dict[str, Any]:
        mint = str(mint or "").strip()
        pair_hint = pair_hint or {}
        state = self._blank_state()
        state["mint"] = mint
        pair = dict(pair_hint)
        if not pair and mint:
            pair = await self._dexscreener_pair(mint)

        quote = await self._quote_solana(mint) if mint else {"quote_ok": False, "reason": "mint_missing"}
        quote_ok = bool(quote.get("quote_ok"))

        dex_hint = _has_pumpfun_hint(pair)
        liq_usd = float((pair.get("liquidity", {}) or {}).get("usd", 0) or 0)
        age_ms = float(pair.get("pairCreatedAt") or 0)
        age_seconds = 0
        if age_ms > 0:
            age_seconds = max(0, int((datetime.now(timezone.utc).timestamp() * 1000 - age_ms) / 1000))

        if quote_ok:
            route_type = "JUPITER_ROUTABLE"
            reason = "jupiter_quote_available"
            buy_ok = sell_ok = True
        elif dex_hint:
            route_type = "PUMPFUN_BONDING_CURVE"
            reason = "pumpfun_hint_no_jupiter_route"
            buy_ok = True
            sell_ok = False
        elif liq_usd > 0 or pair:
            route_type = "PUMPFUN_AMM_OR_GRADUATED"
            reason = "dex_pair_detected_without_jupiter_quote"
            buy_ok = True
            sell_ok = True
        else:
            route_type = "UNSUPPORTED"
            reason = "no_route_found"
            buy_ok = False
            sell_ok = False

        if not sell_ok:
            # No buy if exit cannot be proven.
            buy_ok = False
            if route_type == "PUMPFUN_BONDING_CURVE":
                reason = "no_exit_route"

        pumpfun_curve = {
            "detected": route_type == "PUMPFUN_BONDING_CURVE",
            "hint": dex_hint,
            "pair_address": str(pair.get("pairAddress") or ""),
            "liquidity_usd": liq_usd,
            "age_seconds": age_seconds,
            "dex_id": str(pair.get("dexId") or ""),
            "label": str(pair.get("labels", [""])[0] if isinstance(pair.get("labels"), list) and pair.get("labels") else pair.get("label") or ""),
        }
        state.update(
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "route_type": route_type,
                "buy_route_available": buy_ok,
                "sell_route_available": sell_ok,
                "jupiter_quote": quote if quote_ok else {},
                "pumpfun_curve": pumpfun_curve,
                "reason": reason,
            }
        )
        self.route_state = state
        _write_json(ROUTE_STATE_FILE, state)
        return state

    async def detect_best_effort(self, mint: str, pair_hint: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            return await self.detect(mint, pair_hint=pair_hint)
        except Exception as exc:
            state = self._blank_state()
            state.update(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "mint": str(mint or ""),
                    "route_type": "UNSUPPORTED",
                    "buy_route_available": False,
                    "sell_route_available": False,
                    "reason": str(exc),
                }
            )
            _write_json(ROUTE_STATE_FILE, state)
            return state
