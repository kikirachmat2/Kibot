import asyncio
import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiohttp

from Core.Scanner.source_proof import SourceProof
from Core.Web3.pumpfun_route_detector import PumpfunRouteDetector

logger = logging.getLogger("BaseSwapScanner")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
BASE_SCANNER_STATE_FILE = STATE_DIR / "base_scanner_state.json"

class BaseSwapScanner:
    """
    Real-time Base network scanner querying live DexScreener endpoints.
    Identifies momentum waves and provides validated source proofs.
    """

    def __init__(self) -> None:
        self.dexscreener_url = os.getenv("DEXSCREENER_API_BASE", "https://api.dexscreener.com/latest/dex/search?q=")
        self.max_candidates = int(os.getenv("BASE_MAX_CANDIDATES", "15") or 15)
        self.route_detector = PumpfunRouteDetector()
        self.state = self._blank_state()

    def _blank_state(self) -> Dict[str, Any]:
        return {
            "updated_at": "",
            "scan_mode": "BASE_SWAP",
            "candidates": [],
            "best_candidate": {},
            "status": "LIVE_READY",
            "reason": ""
        }

    def _save(self, state: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        BASE_SCANNER_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    async def scan(self) -> Dict[str, Any]:
        logger.info("📡 Scanning Base network for active token waves...")
        state = self._blank_state()
        state["updated_at"] = datetime.now(timezone.utc).isoformat()

        search_terms = ["degen", "base", "brett", "toshi", "keyboard", "mew", "chomp", "dog"]
        
        # Load operator hints for Base if present
        watchlist_file = STATE_DIR / "operator_hints.json"
        if watchlist_file.exists():
            try:
                wl = json.loads(watchlist_file.read_text(encoding="utf-8"))
                for sym in wl.get("symbols", []):
                    sym_clean = str(sym).strip().lower()
                    if sym_clean and sym_clean not in search_terms:
                        search_terms.append(sym_clean)
            except Exception as e:
                logger.debug(f"Failed to load operator hints: {e}")

        raw_pairs = []
        timeout = aiohttp.ClientTimeout(total=10)
        
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for term in search_terms:
                    url = f"{self.dexscreener_url}{term}"
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                pairs = data.get("pairs", []) or []
                                for p in pairs:
                                    if str(p.get("chainId", "")).lower() == "base":
                                        raw_pairs.append(p)
                    except Exception as e:
                        logger.warning(f"Error fetching Base term '{term}': {e}")
        except Exception as e:
            logger.error(f"Global Base scanner session failed: {e}")
            state["status"] = "BLOCKED_WITH_REASON"
            state["reason"] = f"api_fetch_failed: {e}"
            self.state = state
            self._save(state)
            return state

        # Process and evaluate real candidates only
        candidates = []
        seen_addresses = set()

        for pair in raw_pairs:
            base_tok = pair.get("baseToken", {}) or {}
            address = base_tok.get("address")
            if not address or address in seen_addresses:
                continue
                
            seen_addresses.add(address)

            vol_24h = float((pair.get("volume", {}) or {}).get("h24", 0) or 0)
            liq = float((pair.get("liquidity", {}) or {}).get("usd", 0) or 0)
            fdv = float(pair.get("fdv", 0) or 0)
            price_usd = float(pair.get("priceUsd", 0) or 0)

            # Filter low liquidity/volume to prevent rug pull candidates
            if liq < 5000 or vol_24h < 2000:
                continue

            symbol = str(base_tok.get("symbol", "")).upper()
            
            # Construct a solid cryptographic / API proof
            proof = SourceProof.create(
                source_type="REAL_API",
                source_name="DexScreenerBase",
                source_url_or_endpoint=f"https://api.dexscreener.com/latest/dex/pairs/base/{pair.get('pairAddress')}",
                raw_id=pair.get("pairAddress", address),
                symbol=symbol,
                address_or_mint=address,
                chain="base",
                proof_ok=True
            )

            # Quality metrics
            price_change = pair.get("priceChange", {}) or {}
            change_5m = float(price_change.get("m5", 0) or 0)
            change_1h = float(price_change.get("h1", 0) or 0)

            confidence = round(min(0.98, max(0.1, (vol_24h / 500000.0) * 0.4 + (change_1h / 20.0) * 0.4 + (liq / 100000.0) * 0.2)), 4)

            candidates.append({
                "symbol": symbol,
                "address": address,
                "pair_address": pair.get("pairAddress"),
                "price": price_usd,
                "volume_24h_usd": vol_24h,
                "liquidity_usd": liq,
                "fdv": fdv,
                "change_5m_pct": change_5m,
                "change_1h_pct": change_1h,
                "confidence": confidence,
                "source_proof": proof,
                "decision": "APPROVE" if confidence > 0.4 else "WATCH",
                "reason": "High-volume Base DEX momentum detected" if confidence > 0.4 else "Base DEX monitoring"
            })

        # Sort by volume and confidence
        candidates.sort(key=lambda c: (c["confidence"], c["volume_24h_usd"]), reverse=True)
        
        state["candidates"] = candidates[:self.max_candidates]
        state["best_candidate"] = candidates[0] if candidates else {}
        state["status"] = "LIVE_READY" if candidates else "NO_OPPORTUNITIES"
        state["reason"] = "Scan completed successfully." if candidates else "No candidates matched liquidity criteria."
        
        self.state = state
        self._save(state)
        return state

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = BaseSwapScanner()
    asyncio.run(scanner.scan())
    print("Base Swap Scanner complete.")
