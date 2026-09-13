import asyncio
import logging
import time
from typing import Callable, Awaitable, Optional, List, Dict, Any

from .router import PerSymbolCoalescingRouter
from .evaluator import FastCouncilEvaluator, CouncilDecision
from config import settings

logger = logging.getLogger("KiBotV2.CouncilWorkerPool")

class CouncilWorkerPool:
    """
    Parallel worker pool for sovereign council deliberation.
    - Spawns N concurrent workers (default 4-8).
    - Workers evaluate candidates independently without any global locks.
    - Emits approved mandates to the downstream risk gate.
    """
    def __init__(
        self,
        router: PerSymbolCoalescingRouter,
        worker_count: Optional[int] = None,
        evaluator: Optional[FastCouncilEvaluator] = None,
    ):
        self.router = router
        self.worker_count = worker_count or settings.COUNCIL_WORKERS
        self.evaluator = evaluator or FastCouncilEvaluator()
        
        self.on_decision_cb: Optional[Callable[[CouncilDecision, Dict[str, Any]], Awaitable[None]]] = None
        self._running: bool = False
        self._workers: List[asyncio.Task] = []
        
        # Performance & Latency Telemetry
        self.total_decisions_made: int = 0
        self.deliberation_durations_ms: List[float] = []

    async def start(self) -> None:
        self._running = True
        for i in range(self.worker_count):
            task = asyncio.create_task(self._worker_loop(worker_id=i + 1))
            self._workers.append(task)
        logger.info(f"[CouncilWorkerPool] Initialized {self.worker_count} parallel deliberation workers.")

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
                t_start = time.perf_counter()
                
                # Pure in-memory deterministic evaluation (sub-millisecond)
                decision = self.evaluator.evaluate(candidate_payload)
                
                total_duration_ms = (time.perf_counter() - t_start) * 1000.0
                decision.deliberation_duration_ms = total_duration_ms
                
                self.total_decisions_made += 1
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
