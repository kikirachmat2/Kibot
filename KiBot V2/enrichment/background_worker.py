import asyncio
import logging
from typing import Dict, Any, List, Optional
import aiohttp

from .cache import enrichment_cache, EnrichmentCache
from config import settings

logger = logging.getLogger("KiBotV2.EnrichmentWorker")

class BackgroundEnrichmentWorker:
    """
    Out-of-band news and market intelligence worker.
    Runs periodically in the background completely isolated from the execution hot path.
    Enforces a strict 2-second timeout per external request and gracefully swallows all errors.
    """
    def __init__(
        self,
        cache: Optional[EnrichmentCache] = None,
        interval_s: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ):
        self.cache = cache or enrichment_cache
        self.interval_s = interval_s or settings.ENRICHMENT_INTERVAL_SECONDS
        self.timeout_s = timeout_s or settings.ENRICHMENT_TIMEOUT_SECONDS
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"[EnrichmentWorker] Started background enrichment loop (interval={self.interval_s}s, timeout={self.timeout_s}s)")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("[EnrichmentWorker] Stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.refresh_active_watchlist()
            except Exception as e:
                logger.warning(f"[EnrichmentWorker] Cycle error (gracefully swallowed): {e}")
            await asyncio.sleep(self.interval_s)

    async def fetch_symbol_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Fetches sentiment/news for a single symbol with strict 2s hard timeout."""
        sym = symbol.upper().strip()
        default_fallback = {
            "symbol": sym,
            "sentiment": "NEUTRAL",
            "confidence": 0.5,
            "has_news": False,
            "status": "FALLBACK_NO_DATA",
        }
        
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        try:
            # Enforce 2s hard timeout strictly
            async with asyncio.timeout(self.timeout_s):
                # Placeholder external endpoint / feed mock
                # Any network failure, 429, 403, or timeout is caught below
                return {
                    "symbol": sym,
                    "sentiment": "BULLISH",
                    "confidence": 0.65,
                    "has_news": True,
                    "status": "FRESH",
                }
        except (TimeoutError, asyncio.TimeoutError):
            logger.debug(f"[EnrichmentWorker] Timeout fetching news for {sym} ({self.timeout_s}s exceeded)")
            return default_fallback
        except Exception as exc:
            logger.debug(f"[EnrichmentWorker] Error fetching news for {sym}: {exc}")
            return default_fallback

    async def refresh_active_watchlist(self, symbols: Optional[List[str]] = None) -> None:
        target_symbols = symbols or ["BTC/IDR", "ETH/IDR", "SOL/IDR", "DOGE/IDR", "PEPE/IDR"]
        for sym in target_symbols:
            data = await self.fetch_symbol_sentiment(sym)
            self.cache.set(sym, data, ttl_s=settings.ENRICHMENT_TTL_SECONDS)
