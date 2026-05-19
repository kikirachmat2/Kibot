from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiohttp

from Core.Intelligence.strategy.solana_momentum_meme_strategy import SolanaMomentumMemeStrategy
from Core.Web3.pumpfun_route_detector import PumpfunRouteDetector
from Core.Web3.web3_safety_checker import Web3SafetyChecker
from Core.Web3.web3_quote_router import Web3QuoteRouter

logger = logging.getLogger("PumpfunScanner")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PUMPFUN_FILE = STATE_DIR / "pumpfun_candidates.json"


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


class PumpfunScanner:
    """Best-effort Pump.fun / Solana early meme opportunity scanner."""

    def __init__(self) -> None:
        self.strategy = SolanaMomentumMemeStrategy()
        self.safety = Web3SafetyChecker()
        self.detector = PumpfunRouteDetector()
        self.dexscreener_base = os.getenv("DEXSCREENER_API_BASE", "https://api.dexscreener.com/latest/dex/search?q=")
        self.max_candidates = int(os.getenv("PUMPFUN_MAX_CANDIDATES", "40") or 40)
        self.sources = ["dexscreener", "jupiter", "pumpfun_detector"]

    def _blank_state(self) -> Dict[str, Any]:
        return {
            "updated_at": "",
            "candidates": [],
            "best_candidate": {},
            "rejected": [],
        }

    async def _fetch_json(self, url: str) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=12) as resp:
                    if resp.status != 200:
                        return {}
                    return await resp.json()
        except Exception as exc:
            logger.debug("pumpfun fetch failed: %s", exc)
            return {}

    async def _dexscreener_candidates(self) -> List[Dict[str, Any]]:
        search_terms = [
            "solana meme",
            "pump",
            "pumpfun",
            "degen",
            "usrx",
            "babytroll",
            "rocky",
            "scam",
            "buttcoin",
            "no",
        ]
        # Dynamically append operator hints symbols from state/operator_hints.json
        watchlist_file = Path(__file__).resolve().parent.parent.parent / "state" / "operator_hints.json"
        if watchlist_file.exists():
            try:
                wl = json.loads(watchlist_file.read_text(encoding="utf-8"))
                for sym in wl.get("symbols", []):
                    sym_clean = str(sym).strip().lower()
                    if sym_clean and sym_clean not in search_terms:
                        search_terms.append(sym_clean)
            except Exception as e:
                logger.debug(f"Failed to load operator hints in pumpfun scanner: {e}")

        out: List[Dict[str, Any]] = []
        for term in search_terms:
            data = await self._fetch_json(f"{self.dexscreener_base}{term}")
            for pair in data.get("pairs", []) or []:
                if str(pair.get("chainId", "")).lower() != "solana":
                    continue
                base = pair.get("baseToken", {}) or {}
                price_change = pair.get("priceChange", {}) or {}
                volume = pair.get("volume", {}) or {}
                liquidity = pair.get("liquidity", {}) or {}
                created_at = float(pair.get("pairCreatedAt") or 0)
                age_seconds = 0
                if created_at > 0:
                    age_seconds = max(0, int((datetime.now(timezone.utc).timestamp() * 1000 - created_at) / 1000))
                out.append(
                    {
                        "symbol": str(base.get("symbol") or "").upper(),
                        "mint": str(base.get("address") or ""),
                        "pair_address": str(pair.get("pairAddress") or ""),
                        "route_hint": "unknown",
                        "age_seconds": age_seconds,
                        "market_cap_idr": float(pair.get("fdv", 0) or 0) * float(os.getenv("USD_IDR_RATE", "16000") or 16000),
                        "liquidity_usd": float(liquidity.get("usd", 0) or 0),
                        "volume_5m_usd": float(volume.get("m5", 0) or 0),
                        "volume_1h_usd": float(volume.get("h1", 0) or 0),
                        "price_change_5m_pct": float(price_change.get("m5", 0) or 0),
                        "price_change_1h_pct": float(price_change.get("h1", 0) or 0),
                        "change_24h_pct": float(price_change.get("h24", 0) or 0),
                        "holders": int(pair.get("holders", 0) or 0),
                        "source": "dexscreener",
                        "pair": pair,
                    }
                )
        return out

    async def _score_candidate(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        mint = str(candidate.get("mint") or "")
        route = await self.detector.detect_best_effort(mint, pair_hint=candidate.get("pair") if isinstance(candidate.get("pair"), dict) else {})
        candidate["route_type"] = route.get("route_type", "UNSUPPORTED")
        candidate["route_in"] = "Jupiter" if route.get("buy_route_available") else "Pumpfun"
        candidate["route_out"] = "Jupiter" if route.get("sell_route_available") else "none"
        candidate["route_availability"] = "VERIFIED" if route.get("buy_route_available") else "UNVERIFIED"
        candidate["exit_route_availability"] = "VERIFIED" if route.get("sell_route_available") else "FAILED"
        candidate["route_check_source"] = "pumpfun_route_detector"
        candidate["route_state"] = route

        strategy_eval = self.strategy.evaluate_candidate(
            {
                "symbol": candidate.get("symbol"),
                "mint": mint,
                "change_5m_pct": candidate.get("price_change_5m_pct", 0),
                "change_1h_pct": candidate.get("price_change_1h_pct", 0),
                "change_24h_pct": candidate.get("change_24h_pct", 0),
                "volume_5m_usd": candidate.get("volume_5m_usd", 0),
                "volume_1h_usd": candidate.get("volume_1h_usd", 0),
                "liquidity_usd": candidate.get("liquidity_usd", 0),
                "age_minutes": float(candidate.get("age_seconds", 0) or 0) / 60.0,
                "holders": candidate.get("holders", 0),
                "slippage_pct": 0.0,
                "safety_score": candidate.get("safety_score", 0),
                "route_type": candidate.get("route_type"),
                "route_state": candidate.get("route_state", {}),
            }
        )

        candidate.update(strategy_eval)
        if candidate["route_type"] == "PUMPFUN_BONDING_CURVE":
            candidate["decision"] = "REJECT"
            candidate["reason"] = "no_exit_route"
        elif candidate["route_type"] == "UNSUPPORTED":
            candidate["decision"] = "REJECT"
            candidate["reason"] = route.get("reason") or "unsupported_route"
        elif candidate["route_type"] == "JUPITER_ROUTABLE" and candidate.get("decision") == "APPROVE":
            quote_router = Web3QuoteRouter()
            quote = await quote_router.quote(
                route="solana",
                input_asset="So11111111111111111111111111111111111111112",
                output_asset=mint,
                amount_raw=int(os.getenv("WEB3_MEME_SCAN_QUOTE_RAW", "10000000") or 10000000),
            )
            candidate["quote_ok"] = bool(quote.get("quote_ok"))
            candidate["quote_reason"] = quote.get("reason", "")
            candidate["expected_out"] = quote.get("expected_out", 0)
            candidate["slippage_pct"] = float(quote.get("slippage_pct", 0) or 0)
            safety = self.safety.evaluate(
                {
                    "liquidity": candidate.get("liquidity_usd", 0),
                    "volume": candidate.get("volume_1h_usd", 0),
                    "spread_pct": candidate.get("slippage_pct", 0),
                    "slippage_pct": candidate.get("slippage_pct", 0),
                    "contract_age_days": float(candidate.get("age_seconds", 0) or 0) / 86400.0,
                    "holder_concentration_pct": 0,
                    "token_type": "solana",
                    "mint_authority_enabled": False,
                    "freeze_authority_enabled": False,
                    "ev": candidate.get("ev_pct", 0),
                }
            )
            candidate["safety_score"] = float(safety.get("score", 0) or 0)
            candidate["safety_passed"] = bool(safety.get("passed"))
            if not (quote.get("quote_ok") and safety.get("passed")):
                candidate["decision"] = "REJECT"
                candidate["reason"] = quote.get("reason") if not quote.get("quote_ok") else safety.get("reason")
        candidate["source_proof"] = candidate.get("source_proof") or {}

        return candidate

    async def scan(self) -> Dict[str, Any]:
        raw = await self._dexscreener_candidates()
        
        # Deduplicate candidates by mint
        seen_mints = set()
        unique_raw = []
        for c in raw:
            mint = c.get("mint")
            if mint and mint not in seen_mints:
                seen_mints.add(mint)
                unique_raw.append(c)

        evaluated: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        sem = asyncio.Semaphore(10)

        async def evaluate_one(candidate: Dict[str, Any]):
            async with sem:
                try:
                    scored = await self._score_candidate(candidate)
                    return scored
                except Exception as exc:
                    logger.debug("Failed evaluating pumpfun candidate %s: %s", candidate.get("symbol"), exc)
                    return None

        tasks = [evaluate_one(c) for c in unique_raw]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for scored in results:
            if not scored or isinstance(scored, Exception):
                continue
            if scored.get("decision") == "APPROVE":
                evaluated.append(scored)
            else:
                rejected.append(
                    {
                        "symbol": scored.get("symbol"),
                        "mint": scored.get("mint"),
                        "route_type": scored.get("route_type"),
                        "reason": scored.get("reason", "rejected"),
                        "decision": scored.get("decision", "REJECT"),
                    }
                )

        evaluated.sort(
            key=lambda item: (
                float(item.get("ev_pct", 0) or 0),
                float(item.get("momentum_score", 0) or 0),
                float(item.get("safety_score", 0) or 0),
            ),
            reverse=True,
        )

        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "candidates": evaluated[: self.max_candidates],
            "best_candidate": evaluated[0] if evaluated else {},
            "rejected": rejected[: self.max_candidates * 2],
        }
        _write_json(PUMPFUN_FILE, state)
        return state
