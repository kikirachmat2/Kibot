import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiohttp

from Core.Intelligence.defi_metrics_fetcher import DeFiMetricsFetcher
from Core.Web3.pumpfun_route_detector import PumpfunRouteDetector
from Core.Web3.web3_quote_router import Web3QuoteRouter
from Core.Web3.web3_safety_checker import Web3SafetyChecker

logger = logging.getLogger("SolanaTrendingScanner")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
TREND_FILE = STATE_DIR / "solana_trending_candidates.json"


class SolanaTrendingScanner:
    """Collect trending Solana meme/token candidates from public market sources."""

    def __init__(self) -> None:
        self.fetcher = DeFiMetricsFetcher()
        self.dexscreener_url = os.getenv("DEXSCREENER_API_BASE", "https://api.dexscreener.com/latest/dex/search?q=")
        self.birdeye_api_key = os.getenv("BIRDEYE_API_KEY", "").strip()
        self.helius_api_key = os.getenv("HELIUS_API_KEY", "").strip()
        self.max_candidates = int(os.getenv("SOLANA_MEME_MAX_CANDIDATES", "20") or 20)
        self.route_detector = PumpfunRouteDetector()
        self.state = self._blank_state()

    def _blank_state(self) -> Dict[str, Any]:
        return {
            "updated_at": "",
            "source": ["dexscreener", "jupiter"],
            "candidates": [],
            "best_candidate": {},
            "rejected": [],
        }

    def _save(self, state: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        TREND_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    async def _quote_candidate(self, mint: str, amount_raw: int) -> Dict[str, Any]:
        router = Web3QuoteRouter()
        return await router.quote("solana", "So11111111111111111111111111111111111111112", mint, amount_raw)

    def _evaluate_safety(self, candidate: Dict[str, Any], quote: Dict[str, Any]) -> Dict[str, Any]:
        checker = Web3SafetyChecker()
        payload = {
            "ev": float(candidate.get("ev_pct", 0) or 0),
            "liquidity": float(candidate.get("liquidity_usd", 0) or 0),
            "volume": float(candidate.get("volume_1h_usd", 0) or 0),
            "spread_pct": float(quote.get("slippage_pct", candidate.get("slippage_pct", 0)) or 0),
            "slippage_pct": float(quote.get("slippage_pct", candidate.get("slippage_pct", 0)) or 0),
            "contract_age_days": float(candidate.get("age_minutes", 0) or 0) / 1440.0,
            "holder_concentration_pct": float(candidate.get("holder_concentration_pct", 0) or 0),
            "token_type": "solana",
            "mint_authority_enabled": bool(candidate.get("mint_authority_enabled", False)),
            "freeze_authority_enabled": bool(candidate.get("freeze_authority_enabled", False)),
        }
        return checker.evaluate(payload)

    async def _fetch_json(self, url: str) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=12) as resp:
                    if resp.status != 200:
                        return {}
                    return await resp.json()
        except Exception as exc:
            logger.debug("trend fetch failed: %s", exc)
            return {}

    async def _dexscreener_candidates(self) -> List[Dict[str, Any]]:
        search_terms = [
            "sol",
            "wif",
            "bonk",
            "pepe",
            "meme",
            "degen",
            "usrx",
            "babytroll",
            "scam",
            "rocky",
        ]
        raw: List[Dict[str, Any]] = []
        for term in search_terms:
            data = await self._fetch_json(f"{self.dexscreener_url}{term}")
            for pair in data.get("pairs", []) or []:
                if str(pair.get("chainId", "")).lower() != "solana":
                    continue
                base = pair.get("baseToken", {}) or {}
                quote = pair.get("quoteToken", {}) or {}
                vol_5m = float((pair.get("volume", {}) or {}).get("m5", 0) or 0)
                vol_1h = float((pair.get("volume", {}) or {}).get("h1", 0) or 0)
                vol_24h = float((pair.get("volume", {}) or {}).get("h24", 0) or 0)
                liq = float((pair.get("liquidity", {}) or {}).get("usd", 0) or 0)
                price_change = pair.get("priceChange", {}) or {}
                age_minutes = 0.0
                created_at = pair.get("pairCreatedAt")
                if created_at:
                    try:
                        age_minutes = max(0.0, (datetime.now(timezone.utc).timestamp() * 1000 - float(created_at)) / 60000.0)
                    except Exception:
                        age_minutes = 0.0
                raw.append({
                    "symbol": str(base.get("symbol") or "").upper(),
                    "mint": str(base.get("address") or ""),
                    "pair_address": str(pair.get("pairAddress") or ""),
                    "price_idr": float(pair.get("priceUsd", 0) or 0) * float(os.getenv("USD_IDR", "16000") or 16000),
                    "change_24h_pct": float(price_change.get("h24", 0) or 0),
                    "change_5m_pct": float(price_change.get("m5", 0) or 0),
                    "change_1h_pct": float(price_change.get("h1", 0) or 0),
                    "market_cap_idr": float(pair.get("fdv", 0) or 0) * float(os.getenv("USD_IDR", "16000") or 16000),
                    "liquidity_usd": liq,
                    "volume_5m_usd": vol_5m,
                    "volume_1h_usd": vol_1h,
                    "volume_24h_usd": vol_24h,
                    "holders": int(pair.get("holders", 0) or 0),
                    "age_minutes": round(age_minutes, 1),
                    "source": "dexscreener",
                    "quote": str(quote.get("symbol") or "").upper(),
                })
        return raw

    async def _jupiter_candidates(self) -> List[Dict[str, Any]]:
        try:
            data = await self.fetcher.get_aggregated_defi_intelligence()
            memes = data.get("trending_snipable_memes", []) or []
            out = []
            for item in memes:
                out.append({
                    "symbol": str(item.get("symbol") or "").upper(),
                    "mint": str(item.get("address") or ""),
                    "pair_address": "",
                    "price_idr": 0.0,
                    "change_24h_pct": 0.0,
                    "change_5m_pct": 0.0,
                    "change_1h_pct": 0.0,
                    "market_cap_idr": float(item.get("fdv", 0) or 0) * float(os.getenv("USD_IDR", "16000") or 16000),
                    "liquidity_usd": float(item.get("liquidity", 0) or 0),
                    "volume_5m_usd": 0.0,
                    "volume_1h_usd": 0.0,
                    "volume_24h_usd": float(item.get("volume_24h", 0) or 0),
                    "holders": 0,
                    "age_minutes": 0.0,
                    "source": "jupiter",
                    "quote": "SOL",
                })
            return out
        except Exception as exc:
            logger.debug("jupiter trending fetch failed: %s", exc)
            return []

    async def scan(self) -> Dict[str, Any]:
        from Core.Intelligence.strategy.solana_momentum_meme_strategy import SolanaMomentumMemeStrategy

        strategy = SolanaMomentumMemeStrategy()
        raw = await asyncio.gather(self._dexscreener_candidates(), self._jupiter_candidates(), return_exceptions=True)
        candidates: List[Dict[str, Any]] = []
        for block in raw:
            if isinstance(block, list):
                candidates.extend(block)

        scored = []
        rejected = []
        for item in candidates:
            evaluated = strategy.evaluate_candidate(item)
            merged = {**item, **evaluated}
            route_state = await self.route_detector.detect_best_effort(
                merged.get("mint", ""),
                pair_hint=item.get("pair") if isinstance(item.get("pair"), dict) else {},
            )
            merged["route_type"] = route_state.get("route_type", "UNSUPPORTED")
            merged["route_state"] = route_state
            merged["can_buy"] = bool(route_state.get("buy_route_available"))
            merged["can_sell"] = bool(route_state.get("sell_route_available"))
            mint = str(merged.get("mint") or "")
            if merged.get("decision") == "APPROVE":
                if not mint:
                    merged["decision"] = "REJECT"
                    merged["reason"] = "mint_missing"
                    rejected.append({
                        "symbol": merged.get("symbol"),
                        "mint": merged.get("mint"),
                        "reason": merged.get("reason", "mint_missing"),
                        "decision": merged.get("decision", "REJECT"),
                    })
                    continue

                amount_raw = int(os.getenv("WEB3_MEME_SCAN_QUOTE_RAW", "10000000") or 10000000)
                quote = await self._quote_candidate(mint, amount_raw)
                merged["quote_ok"] = bool(quote.get("quote_ok"))
                merged["quote_reason"] = quote.get("reason", "")
                merged["expected_out"] = quote.get("expected_out", 0)
                merged["slippage_pct"] = float(quote.get("slippage_pct", merged.get("slippage_pct", 0)) or 0)
                safety = self._evaluate_safety(merged, quote)
                merged["safety_score"] = float(safety.get("score", merged.get("safety_score", 0)) or 0)
                merged["max_trade_idr"] = int(min(int(merged.get("max_trade_idr", 0) or 0), int(safety.get("max_trade_idr", 0) or 0)) if safety.get("passed") else 0)
                if quote.get("quote_ok") and safety.get("passed"):
                    scored.append(merged)
                    continue
                merged["decision"] = "REJECT"
                merged["reason"] = safety.get("reason") if not safety.get("passed") else quote.get("reason", "quote_missing")
                if merged.get("route_type") == "PUMPFUN_BONDING_CURVE" and not merged.get("can_sell"):
                    merged["reason"] = "no_exit_route"
            else:
                rejected.append({
                    "symbol": merged.get("symbol"),
                    "mint": merged.get("mint"),
                    "reason": merged.get("reason", "rejected"),
                    "decision": merged.get("decision", "REJECT"),
                })

        scored.sort(key=lambda x: (
            float(x.get("momentum_score", 0) or 0),
            float(x.get("safety_score", 0) or 0),
            float(x.get("ev_pct", 0) or 0),
        ), reverse=True)

        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "source": ["dexscreener", "jupiter"],
            "candidates": scored[: self.max_candidates],
            "best_candidate": scored[0] if scored else {},
            "rejected": rejected[: self.max_candidates * 2],
        }
        self.state = state
        self._save(state)
        return state
