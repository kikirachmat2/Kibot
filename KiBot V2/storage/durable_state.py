import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional

from config import settings

logger = logging.getLogger("KiBotV2.DurableState")

class DurableStateStore:
    """
    Asynchronous, non-blocking durable state persistence.
    Position changes (open, close, partial fill) are enqueued and persisted to disk
    in a background task using atomic file replacement to prevent corruption and zero hot-path I/O delay.
    """
    def __init__(self, state_file_path: Optional[Path] = None):
        self.state_file = state_file_path or (settings.STATE_DIR / "durable_state.json")
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._running: bool = False
        self._flusher_task: Optional[asyncio.Task] = None
        self._latest_state: Dict[str, Any] = {
            "version": "2.0.0",
            "updated_at": 0.0,
            "equity_idr": 0.0,
            "cash_idr": 0.0,
            "open_positions": {},
            "closed_trades": [],
        }

    async def start(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.load_sync()
        self._running = True
        self._flusher_task = asyncio.create_task(self._flusher_loop())
        logger.info(f"[DurableState] Persistence store initialized at {self.state_file}")

    async def stop(self) -> None:
        self._running = False
        if self._flusher_task:
            self._flusher_task.cancel()
            try:
                await self._flusher_task
            except asyncio.CancelledError:
                pass
        # Final atomic flush before exit
        self._write_atomic(self._latest_state)
        logger.info("[DurableState] Stopped & flushed final state to disk.")

    def load_sync(self) -> Dict[str, Any]:
        """Loads state synchronously on startup."""
        if self.state_file.is_file():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self._latest_state = json.load(f)
                logger.info(f"[DurableState] Loaded existing state from disk (Open positions: {len(self._latest_state.get('open_positions', {}))})")
            except Exception as e:
                logger.error(f"[DurableState] Error reading state file, starting fresh: {e}")
        return self._latest_state

    def get_state(self) -> Dict[str, Any]:
        return dict(self._latest_state)

    def record_position_change(
        self,
        change_type: str,
        position_data: Dict[str, Any],
        total_equity_idr: float,
        ledger_name: str = "PRIMARY_TF",
    ) -> None:
        """
        Hot-path non-blocking call.
        Enqueues state update in < 2 microseconds.
        Isolates state buckets between PRIMARY_TF and SHADOW_MR.
        """
        sym = position_data.get("symbol", "").upper()
        self._latest_state["updated_at"] = time.time()

        prefix = "shadow_mr_" if ledger_name == "SHADOW_MR" else ""
        equity_key = f"{prefix}equity_idr" if prefix else "equity_idr"
        open_key = f"{prefix}open_positions" if prefix else "open_positions"
        closed_key = f"{prefix}closed_trades" if prefix else "closed_trades"

        self._latest_state[equity_key] = total_equity_idr
        
        if change_type == "OPEN":
            self._latest_state.setdefault(open_key, {})[sym] = position_data
        elif change_type == "CLOSE":
            self._latest_state.setdefault(open_key, {}).pop(sym, None)
            closed = self._latest_state.setdefault(closed_key, [])
            closed.append(position_data)
            max_trades = getattr(settings, "MAX_IN_MEMORY_TRADES", 500)
            if len(closed) > max_trades:
                self._latest_state[closed_key] = closed[-max_trades:]
        elif change_type == "PARTIAL":
            self._latest_state.setdefault(open_key, {})[sym] = position_data

        # Non-blocking enqueue
        try:
            self._queue.put_nowait(dict(self._latest_state))
        except asyncio.QueueFull:
            pass

    async def _flusher_loop(self) -> None:
        while self._running:
            state_to_save = await self._queue.get()
            try:
                # Discard intermediate updates if queue has multiple pending items (coalesce writes)
                while not self._queue.empty():
                    state_to_save = self._queue.get_nowait()
                    self._queue.task_done()
                
                # Execute atomic write on thread pool so event loop never blocks
                await asyncio.to_thread(self._write_atomic, state_to_save)
            except Exception as exc:
                logger.error(f"[DurableState] Write error: {exc}")
            finally:
                self._queue.task_done()

    def _write_atomic(self, state: Dict[str, Any]) -> None:
        tmp_file = self.state_file.with_name(f"{self.state_file.stem}_{os.getpid()}_{time.time_ns()}.tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            tmp_file.replace(self.state_file)
        except Exception:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass
            raise

# Global singleton durable state store
durable_state_store = DurableStateStore()
