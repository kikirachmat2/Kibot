"""
Test Race Condition Double-Entry Guard (C.3).
Proves that per-symbol atomic locks and pre-evaluation idempotency checks
prevent duplicate orders even when 2 concurrent signals arrive in <1ms window.
"""
import asyncio
import time
import pytest
from async_helper import run_async
from council.router import PerSymbolCoalescingRouter
from council.evaluator import FastCouncilEvaluator
from council.worker_pool import CouncilWorkerPool
from risk.idempotency import IdempotencyGuard
from enrichment.cache import EnrichmentCache

@run_async
async def test_race_condition_double_entry_same_symbol():
    """
    Simulates 2 workers picking up 2 signals for the same symbol within <1ms.
    Verifies that the per-symbol lock blocks the 2nd worker, and the atomic
    pre-evaluation idempotency check prevents duplicate order execution.
    """
    router = PerSymbolCoalescingRouter(max_capacity=20)
    cache = EnrichmentCache()
    evaluator = FastCouncilEvaluator(cache=cache)
    idempotency = IdempotencyGuard(window_seconds=10.0)
    
    orders_placed = []
    
    async def simulated_on_decision(decision, payload):
        if decision.verdict == "APPROVED":
            # Simulate real exchange network latency (e.g. 30ms)
            await asyncio.sleep(0.03)
            idempotency.record_order(decision.symbol)
            orders_placed.append({
                "symbol": decision.symbol,
                "timestamp": time.time(),
                "verdict": decision.verdict
            })

    pool = CouncilWorkerPool(
        router=router,
        worker_count=4,
        evaluator=evaluator,
        idempotency_guard=idempotency,
    )
    pool.on_decision_cb = simulated_on_decision

    await pool.start()

    # 1. Enqueue 1st candidate for BTC/IDR (strong signal -> APPROVED)
    cand_1 = {
        "symbol": "BTC/IDR",
        "price": 1000000000.0,
        "spread_pct": 0.001,
        "volume_ratio": 3.0,
        "leadlag_score": 0.6,
        "avg_win_pct": 0.05,
        "avg_loss_pct": 0.015,
    }
    await router.enqueue_candidate("BTC/IDR", cand_1, score=90.0)

    # Allow worker 1 to dequeue cand_1 and acquire the per-symbol lock (<5ms)
    await asyncio.sleep(0.005)

    # 2. Immediately enqueue 2nd candidate for BTC/IDR within <1ms window
    # Because cand_1 has already been dequeued by worker 1, cand_2 is enqueued fresh
    cand_2 = {
        "symbol": "BTC/IDR",
        "price": 1000500000.0,
        "spread_pct": 0.001,
        "volume_ratio": 3.2,
        "leadlag_score": 0.7,
        "avg_win_pct": 0.05,
        "avg_loss_pct": 0.015,
    }
    await router.enqueue_candidate("BTC/IDR", cand_2, score=92.0)

    # Wait for workers to settle
    await asyncio.sleep(0.1)
    await pool.stop()

    # VERIFICATION:
    # Exactly ONE order must have been placed
    assert len(orders_placed) == 1, f"Expected 1 order, but got {len(orders_placed)} (Double-Entry Bug Detected!)"
    assert orders_placed[0]["symbol"] == "BTC/IDR"

    # Worker pool must have blocked the race duplicate atomically
    assert pool.total_race_duplicates_blocked >= 1, (
        f"Expected total_race_duplicates_blocked >= 1, got {pool.total_race_duplicates_blocked}"
    )

@run_async
async def test_per_symbol_concurrency_different_symbols():
    """
    Verifies that per-symbol locks do NOT block distinct symbols.
    BTC/IDR and ETH/IDR can be evaluated concurrently by different workers.
    """
    router = PerSymbolCoalescingRouter(max_capacity=20)
    cache = EnrichmentCache()
    evaluator = FastCouncilEvaluator(cache=cache)
    idempotency = IdempotencyGuard(window_seconds=10.0)
    
    orders_placed = []
    
    async def simulated_on_decision(decision, payload):
        if decision.verdict == "APPROVED":
            await asyncio.sleep(0.02)
            idempotency.record_order(decision.symbol)
            orders_placed.append(decision.symbol)

    pool = CouncilWorkerPool(
        router=router,
        worker_count=4,
        evaluator=evaluator,
        idempotency_guard=idempotency,
    )
    pool.on_decision_cb = simulated_on_decision

    await pool.start()

    # Enqueue two distinct symbols simultaneously
    await asyncio.gather(
        router.enqueue_candidate("BTC/IDR", {"symbol": "BTC/IDR", "price": 1000000000.0, "volume_ratio": 3.0, "spread_pct": 0.001, "leadlag_score": 0.5, "avg_win_pct": 0.05, "avg_loss_pct": 0.015}, score=90.0),
        router.enqueue_candidate("ETH/IDR", {"symbol": "ETH/IDR", "price": 50000000.0, "volume_ratio": 2.8, "spread_pct": 0.001, "leadlag_score": 0.5, "avg_win_pct": 0.05, "avg_loss_pct": 0.015}, score=88.0),
    )

    await asyncio.sleep(0.08)
    await pool.stop()

    assert len(orders_placed) == 2
    assert "BTC/IDR" in orders_placed
    assert "ETH/IDR" in orders_placed
    assert pool.total_race_duplicates_blocked == 0
