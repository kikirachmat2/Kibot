import asyncio
import logging
import signal
import sys
import time
from typing import Dict, Any

from aiohttp import web
from config import settings
from ingestion import IndodaxWebSocketClient, BinanceWebSocketClient, metrics_registry
from council import PerSymbolCoalescingRouter, CouncilWorkerPool, CouncilDecision
from enrichment import BackgroundEnrichmentWorker
from risk import RiskGate, CapitalGovernor
from storage import setup_logging, durable_state_store, StartupReconciler, venue_ledger
from executor import OrderRouter, VirtualLedger

setup_logging()
logger = logging.getLogger("KiBotV2.Main")

class KiBotV2Pipeline:
    def __init__(self):
        self.router = PerSymbolCoalescingRouter(max_capacity=settings.MAX_SYMBOL_QUEUE_CAP)
        self.council_pool = CouncilWorkerPool(router=self.router, worker_count=settings.COUNCIL_WORKERS)
        self.enrichment_worker = BackgroundEnrichmentWorker()
        
        self.risk_gate = RiskGate()
        self.capital_governor = CapitalGovernor()
        self.venue_ledger = venue_ledger
        self.virtual_ledger = VirtualLedger(initial_cash_idr=10_000_000.0)
        self.order_router = OrderRouter(
            risk_gate=self.risk_gate,
            virtual_ledger=self.virtual_ledger,
            capital_governor=self.capital_governor,
            venue_ledger_instance=self.venue_ledger,
        )
        self.reconciler = StartupReconciler()
        
        self.indodax_ws = IndodaxWebSocketClient()
        self.binance_ws = BinanceWebSocketClient()
        self._running = False
        self._start_time = time.time()
        self._health_runner = None

    async def start(self) -> None:
        self._running = True
        logger.info("=" * 60)
        logger.info("🚀 STARTING KIBOT V2 (PHASE 1 - PAPER TRADING MODE)")
        logger.info(f"🔒 LIVE TRADING GATE: {'ENABLED (REAL CAPITAL)' if settings.LIVE_TRADING_ENABLED else 'LOCKED (PAPER VIRTUAL LEDGER ONLY)'}")
        logger.info(f"⚙️ Workers: {settings.COUNCIL_WORKERS} | Queue Cap: {settings.MAX_SYMBOL_QUEUE_CAP} | Breaker: {settings.MAX_DRAWDOWN_PCT}%")
        logger.info("=" * 60)

        # 1. Start Durable State Persistence
        await durable_state_store.start()

        # 2. Startup Reconciliation (Non-recursive)
        reconcile_res = await self.reconciler.reconcile_on_startup()
        if reconcile_res.get("cash_idr"):
            self.virtual_ledger.cash_idr = reconcile_res["cash_idr"]

        # 3. Start Out-of-band Enrichment Background Worker
        await self.enrichment_worker.start()

        # 4. Wire Council Decision to Order Router
        self.council_pool.on_decision_cb = self._on_council_decision
        await self.council_pool.start()

        # 5. Wire Ingestion Feed to Council Router
        self.indodax_ws.on_ticker_cb = self._on_indodax_ticker
        self.binance_ws.on_mini_ticker_cb = self._on_binance_ticker

        # 6. Start WebSocket Ingestion Tasks
        asyncio.create_task(self.indodax_ws.start())
        asyncio.create_task(self.binance_ws.start())

        # 7. Start Periodic Telemetry Reporter
        asyncio.create_task(self._telemetry_loop())

        # 8. Start Continuous Venue Truth Reconciliation Loop
        asyncio.create_task(self.venue_ledger.start_periodic_loop(self.virtual_ledger))

        # 9. Start Lightweight Health Server for External Watchdog (SG2)
        await self._start_health_server()

    async def _start_health_server(self) -> None:
        try:
            app = web.Application()
            async def handle_health(request):
                status_data = {
                    "status": "HEALTHY",
                    "service": "kibot-v2-paper",
                    "mode": "LIVE" if settings.LIVE_TRADING_ENABLED else "PAPER",
                    "uptime_s": round(time.time() - self._start_time, 1),
                    "timestamp": time.time(),
                    "total_equity_idr": self.virtual_ledger.get_total_equity(),
                    "open_positions": len(self.virtual_ledger.open_positions),
                    "closed_trades": len(self.virtual_ledger.trade_history),
                    "is_halted": self.venue_ledger.is_halted,
                }
                return web.json_response(status_data)

            app.router.add_get("/health", handle_health)
            app.router.add_get("/", handle_health)
            self._health_runner = web.AppRunner(app)
            await self._health_runner.setup()
            site = web.TCPSite(self._health_runner, settings.HEALTH_SERVER_HOST, settings.HEALTH_SERVER_PORT)
            await site.start()
            logger.info(
                f"[KiBotV2] 🩺 External watchdog health server listening on "
                f"http://{settings.HEALTH_SERVER_HOST}:{settings.HEALTH_SERVER_PORT}/health"
            )
        except Exception as e:
            logger.warning(f"[KiBotV2] Could not start health server on port {settings.HEALTH_SERVER_PORT}: {e}")

    async def _on_indodax_ticker(self, ticker: Dict[str, Any]) -> None:
        pair = ticker.get("pair", "")
        price = ticker.get("last_price", 0.0)
        vol = ticker.get("volume_idr", 0.0)
        
        # Update price on virtual ledger for active positions
        self.virtual_ledger.update_market_price(pair, price)
        
        # Update risk gate equity
        total_equity = self.virtual_ledger.get_total_equity()
        self.risk_gate.circuit_breaker.update_equity(total_equity)
        self.risk_gate.daily_cap.update_pnl(total_equity)
        
        # Calculate momentum priority score and market microstructure
        score = 50.0
        if vol > 50_000_000:
            score += 20.0
        high = float(ticker.get("high_24h") or price)
        low = float(ticker.get("low_24h") or price)
        if high > 0 and price >= high * 0.98:
            score += 25.0

        # Market-differentiated metrics (liquidity vs spread vs breakout thrust)
        if vol > 500_000_000:
            vol_ratio = 2.5
            spread_pct = 0.001  # Tight spread (0.1%) on high liquidity
        elif vol > 100_000_000:
            vol_ratio = 1.8
            spread_pct = 0.003  # Moderate spread (0.3%)
        else:
            vol_ratio = 1.0
            spread_pct = 0.008  # Wide spread (0.8%) on illiquid pairs

        leadlag = 0.0
        if high > 0:
            if price >= high * 0.98:
                leadlag = 0.6   # Breakout thrust near 24h high
            elif price >= high * 0.95:
                leadlag = 0.3
            elif price < high * 0.88:
                leadlag = -0.15 # Lagging downtrend
            
        candidate_payload = {
            "symbol": pair,
            "price": price,
            "high_24h": high,
            "low_24h": low,
            "volume_idr": vol,
            "volume_ratio": vol_ratio,
            "leadlag_score": leadlag,
            "spread_pct": spread_pct,
            "timestamp": time.time(),
        }
        await self.router.enqueue_candidate(symbol=pair, payload=candidate_payload, score=score)

    async def _on_binance_ticker(self, ticker: Dict[str, Any]) -> None:
        # Mini ticker stream updates data age and lead-lag metrics
        pass

    async def _on_council_decision(self, decision: CouncilDecision, candidate: Dict[str, Any]) -> None:
        if decision.verdict == "APPROVED" and decision.action == "BUY":
            price = float(candidate.get("price", 0.0))
            await self.order_router.route_buy_order(
                symbol=decision.symbol,
                price=price,
                notional_idr=decision.suggested_size_idr,
                take_profit_pct=decision.target_tp_pct,
                stop_loss_pct=decision.target_sl_pct,
            )

    async def _telemetry_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            latency = self.council_pool.get_latency_stats()
            drop_rate = self.router.drop_rate_pct()
            equity = self.virtual_ledger.get_total_equity()
            open_pos = len(self.virtual_ledger.open_positions)
            trades_done = len(self.virtual_ledger.trade_history)
            
            logger.info(
                f"[Telemetry] 📊 Council Latency (p50: {latency['p50_ms']}ms, p90: {latency['p90_ms']}ms, avg: {latency['mean_ms']}ms) | "
                f"Drop Rate: {drop_rate:.1f}% | Equity: Rp {equity:,.0f} | Open: {open_pos} | Closed: {trades_done}"
            )

    async def stop(self) -> None:
        self._running = False
        logger.info("[KiBotV2] Shutting down pipeline gracefully...")
        await self.indodax_ws.stop()
        await self.binance_ws.stop()
        await self.council_pool.stop()
        await self.enrichment_worker.stop()
        self.venue_ledger.stop()
        if self._health_runner:
            await self._health_runner.cleanup()
        await durable_state_store.stop()
        logger.info("[KiBotV2] ✅ All services stopped safely.")

async def main():
    pipeline = KiBotV2Pipeline()
    
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def _signal_handler():
        logger.info("Signal received, initiating shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    try:
        await pipeline.start()
        await stop_event.wait()
        await pipeline.stop()
    except Exception as exc:
        logger.critical(f"[KiBotV2] 💥 Pipeline crashed unexpectedly: {exc}", exc_info=True)
        try:
            from notifications import telegram_notifier
            await telegram_notifier.send_alert(
                event_type="PROCESS_CRASH",
                title="🚨 KIBOT V2 PROCESS CRASH",
                message=f"KiBot V2 process crashed with unhandled exception: `{exc}`",
                severity="CRITICAL",
                details={"error": str(exc), "type": type(exc).__name__},
                force=True,
            )
            await telegram_notifier.close()
        except Exception:
            pass
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
