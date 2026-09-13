"""Unit tests for Enrichment cache, fallback behavior, hard timeout, and exception swallowing."""
import asyncio
import time
import pytest
from async_helper import run_async
from enrichment.cache import EnrichmentCache
from enrichment.background_worker import BackgroundEnrichmentWorker
from council.evaluator import FastCouncilEvaluator

def test_enrichment_cache_ttl_and_expiry():
    """Verify enrichment cache stores data and respects TTL."""
    cache = EnrichmentCache(default_ttl_s=0.1)
    
    data = {
        "symbol": "SOL/IDR",
        "sentiment": "BULLISH",
        "confidence": 0.85,
        "has_news": True
    }
    cache.set("SOL/IDR", data)
    
    # Immediately accessible
    fetched = cache.get("SOL/IDR")
    assert fetched is not None
    assert fetched["sentiment"] == "BULLISH"
    assert cache.has("SOL/IDR") is True

    # Sleep past TTL (0.1s)
    time.sleep(0.15)
    assert cache.get("SOL/IDR") is None
    assert cache.has("SOL/IDR") is False

def test_zero_wait_hot_path_when_cache_empty():
    """Verify evaluator proceeds immediately without waiting when enrichment cache is empty."""
    cache = EnrichmentCache()
    evaluator = FastCouncilEvaluator(cache=cache)
    
    candidate = {
        "symbol": "DOGE/IDR",
        "price": 2000.0,
        "spread_pct": 0.002,
        "volume_ratio": 2.0,
        "leadlag_score": 0.5,
    }
    
    t0 = time.perf_counter()
    decision = evaluator.evaluate(candidate)
    t_elapsed_ms = (time.perf_counter() - t0) * 1000.0
    
    # Must evaluate immediately without network wait
    assert t_elapsed_ms < 10.0
    assert decision.enrichment_status == "CACHE_MISS_FALLBACK"
    assert decision.verdict == "APPROVED"

@run_async
async def test_enrichment_worker_swallows_exceptions():
    """Verify background enrichment worker catches exceptions and stores safe fallback."""
    cache = EnrichmentCache()
    worker = BackgroundEnrichmentWorker(cache=cache, timeout_s=0.2)
    
    # Intentionally trigger an error by querying when network is unavailable/mocked
    data = await worker.fetch_symbol_sentiment("INVALID_SYMBOL_XYZ")
    assert data is not None
    assert data["symbol"] == "INVALID_SYMBOL_XYZ"
    # Even on error/mock, it returns a safe dict, never raises unhandled exception

@run_async
async def test_enrichment_worker_hard_timeout():
    """Verify background enrichment worker enforces hard timeout and does not hang."""
    cache = EnrichmentCache()
    worker = BackgroundEnrichmentWorker(cache=cache, timeout_s=0.05)
    
    t0 = time.perf_counter()
    data = await worker.fetch_symbol_sentiment("BTC/IDR")
    elapsed = time.perf_counter() - t0
    
    # Enforces timeout within bounds
    assert elapsed < 1.0
    assert data["sentiment"] in ["BULLISH", "NEUTRAL"]
