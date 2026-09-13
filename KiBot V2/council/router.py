import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger("KiBotV2.CouncilRouter")

@dataclass(order=True)
class QueuedCandidate:
    priority_score: float
    symbol: str = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.time)

class PerSymbolCoalescingRouter:
    """
    Manages per-symbol candidate queuing with coalescing and capacity cap (default 20).
    - If a symbol is already queued, its payload is updated in-place (coalesced) with freshest data.
    - If queue is at capacity (20) and a higher-score candidate arrives, the lowest-score candidate is dropped.
    - Completely eliminates the global deliberation lock.
    """
    def __init__(self, max_capacity: int = 20):
        self.max_capacity = max_capacity
        self._symbol_queues: Dict[str, asyncio.Queue[Dict[str, Any]]] = {}
        self._active_symbols: set[str] = set()
        self._latest_payloads: Dict[str, Dict[str, Any]] = {}
        self._scores: Dict[str, float] = {}
        self._work_queue: asyncio.PriorityQueue[QueuedCandidate] = asyncio.PriorityQueue()
        self._lock = asyncio.Lock()
        
        # Metrics
        self.total_signals_received: int = 0
        self.total_signals_dropped_capacity: int = 0
        self.total_signals_coalesced: int = 0

    async def enqueue_candidate(self, symbol: str, payload: Dict[str, Any], score: float) -> bool:
        sym = symbol.upper().strip()
        self.total_signals_received += 1
        
        async with self._lock:
            # 1. Coalescing: If symbol is already waiting to be evaluated, update payload in-place
            if sym in self._latest_payloads:
                self._latest_payloads[sym] = payload
                self._scores[sym] = max(self._scores.get(sym, 0.0), score)
                self.total_signals_coalesced += 1
                return True
                
            # 2. Capacity Cap Check
            if len(self._active_symbols) >= self.max_capacity:
                # Find the lowest score active symbol
                lowest_sym = min(self._scores.items(), key=lambda x: x[1])[0]
                lowest_score = self._scores[lowest_sym]
                
                # If the new candidate has lower or equal score, drop it
                if score <= lowest_score:
                    self.total_signals_dropped_capacity += 1
                    logger.debug(f"[Router] Dropping {sym} (score={score:.2f} <= lowest active {lowest_sym}:{lowest_score:.2f})")
                    return False
                else:
                    # Evict the lowest score candidate to make room for superior candidate
                    logger.info(f"[Router] Evicting {lowest_sym} (score={lowest_score:.2f}) for superior candidate {sym} (score={score:.2f})")
                    self._latest_payloads.pop(lowest_sym, None)
                    self._scores.pop(lowest_sym, None)
                    self._active_symbols.discard(lowest_sym)
                    self.total_signals_dropped_capacity += 1

            # 3. Accept new candidate
            self._active_symbols.add(sym)
            self._latest_payloads[sym] = payload
            self._scores[sym] = score
            
            # Note: In PriorityQueue, lowest value is retrieved first, so we store negative score for max-priority
            item = QueuedCandidate(priority_score=-score, symbol=sym, payload=payload)
            await self._work_queue.put(item)
            return True

    async def get_next_work(self) -> Dict[str, Any]:
        """Worker retrieves highest-priority candidate. Returns freshest coalesced payload."""
        while True:
            candidate = await self._work_queue.get()
            sym = candidate.symbol
            async with self._lock:
                if sym in self._latest_payloads:
                    payload = self._latest_payloads.pop(sym)
                    self._scores.pop(sym, None)
                    self._active_symbols.discard(sym)
                    self._work_queue.task_done()
                    return payload
                else:
                    # Was evicted, discard and continue to next item
                    self._work_queue.task_done()

    def active_count(self) -> int:
        return len(self._active_symbols)

    def drop_rate_pct(self) -> float:
        if self.total_signals_received == 0:
            return 0.0
        return (self.total_signals_dropped_capacity / self.total_signals_received) * 100.0
