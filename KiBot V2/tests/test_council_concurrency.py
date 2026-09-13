"""Unit tests for Council concurrency, per-symbol queues, worker pool, and coalescing."""
import asyncio
import time
import pytest
from async_helper import run_async
from council.router import PerSymbolCoalescingRouter
from council.evaluator import FastCouncilEvaluator, CouncilDecision
from council.worker_pool import CouncilWorkerPool
from enrichment.cache import EnrichmentCache

@run_async
async def test_coalescing_and_deduplication():
    """Verify that newer candidates for the same symbol coalesce/update existing queue items."""
    router = PerSymbolCoalescingRouter(max_capacity=20)
    
    payload1 = {"symbol": "ETH/IDR", "price": 45000000.0, "volume_ratio": 1.2}
    payload2 = {"symbol": "ETH/IDR", "price": 45200000.0, "volume_ratio": 2.5}
    
    await router.enqueue_candidate("ETH/IDR", payload1, score=65.0)
    assert router.active_count() == 1
    
    # Submit updated signal for same symbol
    await router.enqueue_candidate("ETH/IDR", payload2, score=85.0)
    assert router.active_count() == 1  # Coalesced, still 1 active symbol
    assert router.total_signals_coalesced == 1
    
    item = await router.get_next_work()
    assert item["symbol"] == "ETH/IDR"
    assert item["price"] == 45200000.0
    assert item["volume_ratio"] == 2.5

@run_async
async def test_capacity_cap_and_eviction():
    """Verify router caps at 20 symbols and evicts the lowest score when full."""
    router = PerSymbolCoalescingRouter(max_capacity=20)
    
    # Fill with 20 symbols with scores 50 to 69
    for i in range(20):
        sym = f"PAIR_{i}/IDR"
        await router.enqueue_candidate(sym, {"symbol": sym, "price": 1000.0}, score=50.0 + i)
    
    assert router.active_count() == 20
    
    # Submit 21st symbol with higher score 95.0
    cand_high = {"symbol": "HIGH/IDR", "price": 5000.0}
    accepted = await router.enqueue_candidate("HIGH/IDR", cand_high, score=95.0)
    assert accepted is True
    
    # Total count remains 20
    assert router.active_count() == 20
    
    # Lowest score (PAIR_0/IDR, score 50.0) was evicted
    assert "PAIR_0/IDR" not in router._active_symbols
    assert "HIGH/IDR" in router._active_symbols

def test_fast_council_evaluator_speed():
    """Verify deliberation execution latency is purely in-memory (<20ms)."""
    cache = EnrichmentCache()
    evaluator = FastCouncilEvaluator(cache=cache)
    
    candidate = {
        "symbol": "BTC/IDR",
        "price": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 2.5,
        "leadlag_score": 0.5,
        "avg_win_pct": 0.05,
        "avg_loss_pct": 0.015,
    }
    
    t0 = time.perf_counter()
    decision = evaluator.evaluate(candidate)
    t_elapsed_ms = (time.perf_counter() - t0) * 1000.0
    
    # Must evaluate in < 20ms (purely in-memory, typically < 0.5ms)
    assert t_elapsed_ms < 20.0
    assert decision.verdict == "APPROVED"
    assert decision.action == "BUY"
    assert decision.deliberation_duration_ms < 20.0

@run_async
async def test_worker_pool_concurrency_no_global_lock():
    """Verify workers process distinct symbol signals concurrently without dropping."""
    router = PerSymbolCoalescingRouter(max_capacity=20)
    cache = EnrichmentCache()
    evaluator = FastCouncilEvaluator(cache=cache)
    
    decisions = []
    async def on_decision(dec, payload):
        decisions.append(dec)
        
    pool = CouncilWorkerPool(
        router=router,
        worker_count=4,
        evaluator=evaluator
    )
    pool.on_decision_cb = on_decision
    
    # Submit 10 distinct symbols
    for i in range(10):
        await router.enqueue_candidate(
            symbol=f"COIN_{i}/IDR",
            payload={"symbol": f"COIN_{i}/IDR", "price": 1000.0 * (i + 1), "volume_ratio": 2.0, "spread_pct": 0.001, "leadlag_score": 0.4},
            score=70.0 + i
        )
        
    await pool.start()
    
    # Allow workers to drain the queue
    for _ in range(50):
        if len(decisions) >= 10:
            break
        await asyncio.sleep(0.02)
        
    await pool.stop()
    
    assert len(decisions) == 10
    stats = pool.get_latency_stats()
    assert stats["mean_ms"] < 50.0

def test_calibrated_evaluator_rejects_substandard_ev_and_rr():
    """Verify calibrated defaults (35% win, 2.8% win, 2.4% loss) reject weak trades."""
    cache = EnrichmentCache()
    evaluator = FastCouncilEvaluator(cache=cache)
    
    # Candidate relying purely on defaults
    candidate = {
        "symbol": "WEAK/IDR",
        "price": 1000.0,
        "spread_pct": 0.002,
        "volume_ratio": 1.0,
        "leadlag_score": 0.0,
    }
    decision = evaluator.evaluate(candidate)
    assert decision.verdict == "REJECTED"
    assert "below threshold 0.30%" in decision.reason or "below minimum 1.40" in decision.reason
