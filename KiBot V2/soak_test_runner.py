"""Long-running Soak Test Runner for KiBot V2 (Paper Trading Mode).

Monitors:
1. Memory Usage (RSS MB) sampled every 30s to detect leaks.
2. Signal ingestion throughput, drop rate (target <2%, toleransi <5%).
3. Latency distribution (mean, p50, p90, max) across hundreds/thousands of decisions.
4. Position lifecycles (open -> TP/SL/MaxHold closed).
5. Risk gate stability (Circuit breaker & Daily loss cap).
6. Persists periodic telemetry snapshots to logs/soak_metrics.json.
"""
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
import psutil

# Add KiBot V2 root to sys.path
V2_ROOT = Path(__file__).resolve().parent
if str(V2_ROOT) not in sys.path:
    sys.path.insert(0, str(V2_ROOT))

from main import KiBotV2Pipeline
from config import settings

LOG_DIR = V2_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SOAK_LOG_FILE = LOG_DIR / "soak_test.log"
SOAK_METRICS_FILE = LOG_DIR / "soak_metrics.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(SOAK_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("SoakTestRunner")

class SoakTestMonitor:
    def __init__(self, pipeline: KiBotV2Pipeline, sample_interval_s: float = 30.0):
        self.pipeline = pipeline
        self.sample_interval_s = sample_interval_s
        self.process = psutil.Process(os.getpid())
        self.start_time = time.time()
        self.samples = []
        self._running = False

    def get_memory_rss_mb(self) -> float:
        return round(self.process.memory_info().rss / (1024 * 1024), 2)

    async def run(self, max_duration_s: Optional[float] = None):
        self._running = True
        logger.info("=" * 70)
        logger.info(f"🚀 KIBOT V2 SOAK TEST STARTED (PID={os.getpid()})")
        logger.info(f"Target Mode: PAPER TRADING ONLY (Live Execution Locked)")
        logger.info(f"Initial Memory RSS: {self.get_memory_rss_mb()} MB")
        logger.info("=" * 70)

        # Start master pipeline
        await self.pipeline.start()

        iteration = 0
        while self._running:
            try:
                await asyncio.sleep(self.sample_interval_s)
                iteration += 1
                now = time.time()
                elapsed_s = now - self.start_time
                
                # Gather metrics
                mem_mb = self.get_memory_rss_mb()
                latency = self.pipeline.council_pool.get_latency_stats()
                total_signals = self.pipeline.router.total_signals_received
                coalesced = self.pipeline.router.total_signals_coalesced
                dropped = self.pipeline.router.total_signals_dropped_capacity
                drop_rate = self.pipeline.router.drop_rate_pct()
                decisions = self.pipeline.council_pool.total_decisions_made
                
                ledger = self.pipeline.virtual_ledger
                equity = ledger.get_total_equity()
                open_pos = len(ledger.open_positions)
                trade_history = list(ledger.trade_history)
                closed_count = len(trade_history)

                # Collect exit reasons breakdown
                exit_reasons = {}
                for tr in trade_history:
                    reason = tr.get("exit_reason", "UNKNOWN")
                    exit_reasons[reason] = exit_reasons.get(reason, 0) + 1

                # Risk gate state
                cb_tripped = self.pipeline.risk_gate.circuit_breaker.is_tripped
                daily_locked = self.pipeline.risk_gate.daily_cap.is_locked
                current_dd = self.pipeline.risk_gate.circuit_breaker.current_drawdown_pct

                sample = {
                    "timestamp": round(now, 1),
                    "elapsed_seconds": round(elapsed_s, 1),
                    "elapsed_human": f"{int(elapsed_s // 3600)}h {int((elapsed_s % 3600) // 60)}m {int(elapsed_s % 60)}s",
                    "memory_rss_mb": mem_mb,
                    "signals_received": total_signals,
                    "signals_coalesced": coalesced,
                    "signals_dropped": dropped,
                    "drop_rate_pct": round(drop_rate, 2),
                    "council_decisions_made": decisions,
                    "latency_ms": latency,
                    "equity_idr": round(equity, 2),
                    "open_positions": open_pos,
                    "closed_positions": closed_count,
                    "exit_reasons_breakdown": exit_reasons,
                    "circuit_breaker_tripped": cb_tripped,
                    "current_drawdown_pct": round(current_dd, 2),
                    "daily_loss_cap_locked": daily_locked,
                }
                self.samples.append(sample)

                # Keep max 5000 samples in memory
                if len(self.samples) > 5000:
                    self.samples.pop(0)

                # Atomic save to disk
                self._save_metrics()

                logger.info(
                    f"[Soak Iteration {iteration} | {sample['elapsed_human']}] "
                    f"RAM: {mem_mb} MB | Signals: {total_signals} | Dropped: {dropped} ({drop_rate:.2f}%) | "
                    f"Decisions: {decisions} | Latency avg: {latency['mean_ms']}ms (p90: {latency['p90_ms']}ms) | "
                    f"Equity: Rp {equity:,.0f} | Open: {open_pos} | Closed: {closed_count} {exit_reasons}"
                )

                if max_duration_s and elapsed_s >= max_duration_s:
                    logger.info(f"Target duration {max_duration_s}s reached. Concluding soak test.")
                    break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in soak monitor loop: {e}", exc_info=True)

        await self.pipeline.stop()
        logger.info(f"✅ Soak test concluded. Total duration: {time.time() - self.start_time:.1f}s")

    def _save_metrics(self):
        try:
            tmp = SOAK_METRICS_FILE.with_suffix(".tmp")
            summary = {
                "start_time": self.start_time,
                "latest_sample": self.samples[-1] if self.samples else None,
                "sample_history_count": len(self.samples),
                "samples": self.samples[-100:],  # last 100 snapshots
            }
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            tmp.replace(SOAK_METRICS_FILE)
        except Exception as err:
            logger.error(f"Failed to persist soak metrics: {err}")

    def stop(self):
        self._running = False

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=None, help="Max run duration in seconds")
    parser.add_argument("--interval", type=float, default=15.0, help="Sampling interval in seconds")
    args = parser.parse_args()

    pipeline = KiBotV2Pipeline()
    monitor = SoakTestMonitor(pipeline=pipeline, sample_interval_s=args.interval)

    loop = asyncio.get_running_loop()
    def _sig_handler():
        logger.info("Termination signal received. Gracefully stopping soak test...")
        monitor.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig_handler)
        except NotImplementedError:
            pass

    await monitor.run(max_duration_s=args.duration)

if __name__ == "__main__":
    from typing import Optional
    asyncio.run(main())
