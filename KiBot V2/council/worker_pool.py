import asyncio
import logging
import time
from typing import Callable, Awaitable, Optional, List, Dict, Any

from .router import PerSymbolCoalescingRouter
from .evaluator import FastCouncilEvaluator, CouncilDecision
from config import settings
from risk.idempotency import IdempotencyGuard

logger = logging.getLogger("KiBotV2.CouncilWorkerPool")

class CouncilWorkerPool:
    """
    Parallel worker pool for sovereign council deliberation.
    - Spawns N concurrent workers (default 4-8).
    - Workers evaluate candidates independently without any global locks.
    - Per-Symbol Lock: Prevents double-entry race conditions by acquiring a lock
      per symbol before evaluation and releasing after order dispatch.
    - Emits approved mandates to the downstream risk gate.
    """
    def __init__(
        self,
        router: PerSymbolCoalescingRouter,
        worker_count: Optional[int] = None,
        evaluator: Optional[Any] = None,
        idempotency_guard: Optional[IdempotencyGuard] = None,
    ):
        self.router = router
        self.worker_count = worker_count or settings.COUNCIL_WORKERS
        self.evaluator = evaluator or FastCouncilEvaluator()
        self.idempotency_guard = idempotency_guard
        
        self.on_decision_cb: Optional[Callable[[CouncilDecision, Dict[str, Any]], Awaitable[None]]] = None
        self._running: bool = False
        self._workers: List[asyncio.Task] = []
        
        # Per-Symbol Locks (Strict per-symbol serialization, zero global lock)
        self._symbol_locks: Dict[str, asyncio.Lock] = {}
        self._locks_mutex = asyncio.Lock()
        
        # Performance & Latency Telemetry
        self.total_decisions_made: int = 0
        self.total_approved: int = 0
        self.total_rejected: int = 0
        self.total_race_duplicates_blocked: int = 0
        self.deliberation_durations_ms: List[float] = []

    async def _get_symbol_lock(self, symbol: str) -> asyncio.Lock:
        async with self._locks_mutex:
            if symbol not in self._symbol_locks:
                self._symbol_locks[symbol] = asyncio.Lock()
            return self._symbol_locks[symbol]

    async def start(self) -> None:
        self._running = True
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker_loop(worker_id=i + 1))
            self._workers.append(task)
        logger.info(f"[CouncilWorkerPool] Initialized {self.worker_count} parallel deliberation workers with per-symbol locks.")

    async def stop(self) -> None:
        self._running = False
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("[CouncilWorkerPool] Stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        logger.debug(f"[Worker-{worker_id}] Ready for work.")
        while self._running:
            try:
                candidate_payload = await self.router.get_next_work()
                symbol = str(candidate_payload.get("symbol") or candidate_payload.get("pair") or "UNKNOWN").upper().strip()
                
                sym_lock = await self._get_symbol_lock(symbol)
                async with sym_lock:
                    # ATOMIC IDEMPOTENCY CHECK BEFORE EVALUATION
                    if self.idempotency_guard:
                        can_place, idem_reason = self.idempotency_guard.can_place_order(symbol)
                        if not can_place:
                            self.total_race_duplicates_blocked += 1
                            logger.info(f"[Worker-{worker_id}] 🛑 Atomic check blocked race-duplicate for {symbol}: {idem_reason}")
                            continue

                    t_start = time.perf_counter()
                    # Pure in-memory deterministic evaluation (sub-millisecond)
                    decision = self.evaluator.evaluate(candidate_payload)
                    
                    total_duration_ms = (time.perf_counter() - t_start) * 1000.0
                    decision.deliberation_duration_ms = total_duration_ms
                    
                    self.total_decisions_made += 1
                    if decision.verdict == "APPROVED":
                        self.total_approved += 1
                    else:
                        self.total_rejected += 1
                    if len(self.deliberation_durations_ms) >= 1000:
                        self.deliberation_durations_ms.pop(0)
                    self.deliberation_durations_ms.append(total_duration_ms)
                    
                    logger.debug(
                        f"[Worker-{worker_id}] Evaluated {decision.symbol}: {decision.verdict} "
                        f"(duration={total_duration_ms:.2f}ms, ev={decision.ev_pct}%)"
                    )
                    
                    if self.on_decision_cb:
                        await self.on_decision_cb(decision, candidate_payload)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] Uncaught exception during deliberation: {e}")

    def get_latency_stats(self) -> Dict[str, float]:
        if not self.deliberation_durations_ms:
            return {"mean_ms": 0.0, "p50_ms": 0.0, "p90_ms": 0.0, "max_ms": 0.0}
        s = sorted(self.deliberation_durations_ms)
        n = len(s)
        mean_v = sum(s) / n
        p50_v = s[n // 2]
        p90_v = s[int(n * 0.9)]
        return {
            "mean_ms": round(mean_v, 2),
            "p50_ms": round(p50_v, 2),
            "p90_ms": round(p90_v, 2),
            "max_ms": round(s[-1], 2),
        }
