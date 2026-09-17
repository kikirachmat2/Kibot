import asyncio
import logging
import signal
import sys
import time
from typing import Dict, Any

from aiohttp import web
from config import settings
from ingestion import (
    IndodaxWebSocketClient,
    BinanceWebSocketClient,
    BinanceLeadLagTracker,
    metrics_registry,
)
from council import PerSymbolCoalescingRouter, CouncilWorkerPool, CouncilDecision, SwingEvaluator
from enrichment import BackgroundEnrichmentWorker, CandleEnrichmentManager
from risk import RiskGate, CapitalGovernor
from storage import setup_logging, durable_state_store, StartupReconciler, venue_ledger
from executor import OrderRouter, VirtualLedger

setup_logging()
logger = logging.getLogger("KiBotV2.Main")

class KiBotV2Pipeline:
    def __init__(self):
        self.router = PerSymbolCoalescingRouter(max_capacity=settings.MAX_SYMBOL_QUEUE_CAP)
        self.swing_evaluator = SwingEvaluator()
        self.council_pool = CouncilWorkerPool(
            router=self.router,
            worker_count=settings.COUNCIL_WORKERS,
            evaluator=self.swing_evaluator,
        )
        self.enrichment_worker = BackgroundEnrichmentWorker()
        self.candle_manager = CandleEnrichmentManager()
        
        self.risk_gate = RiskGate()
        self.capital_governor = CapitalGovernor()
        self.venue_ledger = venue_ledger

        # 1. Primary Virtual Ledger (Jalur 1: Trend-Following -> GO_LIVE_CHECKLIST N>=30)
        from storage.live_readiness import live_readiness_evaluator, shadow_mr_readiness_evaluator
        self.virtual_ledger = VirtualLedger(
            initial_cash_idr=10_000_000.0,
            name="PRIMARY_TF",
            readiness_evaluator=live_readiness_evaluator,
        )
        self.virtual_ledger.on_trade_closed_cb = self.capital_governor.on_trade_closed

        # 2. Shadow Virtual Ledger (Jalur 2: Mean-Reversion -> Shadow Observation N>=20, PF>=1.25)
        self.shadow_ledger = VirtualLedger(
            initial_cash_idr=10_000_000.0,
            name="SHADOW_MR",
            readiness_evaluator=shadow_mr_readiness_evaluator,
        )
        self.shadow_ledger.on_trade_closed_cb = self.capital_governor.on_trade_closed

        self.order_router = OrderRouter(
            risk_gate=self.risk_gate,
            virtual_ledger=self.virtual_ledger,
            shadow_ledger=self.shadow_ledger,
            capital_governor=self.capital_governor,
            venue_ledger_instance=self.venue_ledger,
        )
        self.reconciler = StartupReconciler()
        
        self.indodax_ws = IndodaxWebSocketClient()
        self.binance_ws = BinanceWebSocketClient()
        self.binance_tracker = BinanceLeadLagTracker()
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
        
        # Re-hydrate Primary Ledger (TF)
        primary_data = reconcile_res.get("primary", {})
        self.virtual_ledger.restore_state(
            cash_idr=primary_data.get("cash_idr", reconcile_res.get("cash_idr")),
            open_positions_data=primary_data.get("open_positions", reconcile_res.get("open_positions")),
            trade_history_data=primary_data.get("closed_trades"),
            peak_equity_idr=primary_data.get("peak_equity_idr", primary_data.get("equity_idr")),
        )

        # Re-hydrate Shadow Ledger (MR)
        shadow_data = reconcile_res.get("shadow", {})
        self.shadow_ledger.restore_state(
            cash_idr=shadow_data.get("cash_idr"),
            open_positions_data=shadow_data.get("open_positions"),
            trade_history_data=shadow_data.get("closed_trades"),
            peak_equity_idr=shadow_data.get("peak_equity_idr", shadow_data.get("equity_idr")),
        )

        # 3. Start Out-of-band Enrichment Background Worker & Candle Manager
        await self.enrichment_worker.start()
        await self.candle_manager.start()

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
                    "shadow_mr_equity_idr": self.shadow_ledger.get_total_equity(),
                    "shadow_mr_open_positions": len(self.shadow_ledger.open_positions),
                    "shadow_mr_closed_trades": len(self.shadow_ledger.trade_history),
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
        
        # Update price on primary virtual ledger (TF) and shadow ledger (MR)
        self.virtual_ledger.update_market_price(pair, price)
        if self.shadow_ledger:
            self.shadow_ledger.update_market_price(pair, price)
        
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
            
        # Binance Macro Lead-Lag Confirmation
        bin_sym = self.binance_tracker.map_indodax_to_binance(pair)
        bin_mom = self.binance_tracker.get_momentum(bin_sym)
        is_dumping, dump_reason = self.binance_tracker.is_dumping(bin_sym)

        # Update live price and get precomputed 1D candle technical indicators
        indicators = self.candle_manager.update_live_price(pair, price) or self.candle_manager.get_indicators(pair) or {}

        candidate_payload = {
            "symbol": pair,
            "price": price,
            "high_24h": high,
            "low_24h": low,
            "volume_idr": vol,
            "volume_ratio": vol_ratio,
            "leadlag_score": leadlag,
            "spread_pct": spread_pct,
            "binance_momentum_1h": bin_mom.get("return_1h", 0.0),
            "binance_momentum_5m": bin_mom.get("return_5m", 0.0),
            "binance_momentum_24h": bin_mom.get("return_24h", 0.0),
            "binance_is_dumping": is_dumping,
            "binance_dump_reason": dump_reason,
            "timestamp": time.time(),
            # Precomputed 1D Swing Indicators
            "ema20": indicators.get("ema20", 0.0),
            "ema50": indicators.get("ema50", 0.0),
            "ema100": indicators.get("ema100", 0.0),
            "rsi14": indicators.get("rsi14", 50.0),
            "atr14": indicators.get("atr14", 0.0),
            "volume": indicators.get("volume", 1.0),
            "volume_sma20": indicators.get("volume_sma20", 1.0),
            "lower_bb": indicators.get("lower_bb", 0.0),
            "middle_bb": indicators.get("middle_bb", 0.0),
            "upper_bb": indicators.get("upper_bb", 0.0),
            "adx14": indicators.get("adx14", 20.0),
            "sma20_slope": indicators.get("sma20_slope", 0.0),
            "choppiness_index": indicators.get("choppiness_index", 50.0),
            "volume_zscore": indicators.get("volume_zscore", 0.0),
            "bollinger_pct_b": indicators.get("bollinger_pct_b", 0.5),
        }
        await self.router.enqueue_candidate(symbol=pair, payload=candidate_payload, score=score)

    async def _on_binance_ticker(self, ticker: Dict[str, Any]) -> None:
        # Mini ticker stream updates data age and lead-lag metrics in memory
        self.binance_tracker.update_ticker(ticker)

    async def _on_council_decision(self, decision: CouncilDecision, candidate: Dict[str, Any]) -> None:
        if decision.verdict == "APPROVED" and decision.action == "BUY":
            price = float(candidate.get("price", 0.0))
            # Stage 2: Microstructure & Orderbook Depth Verification (GAP-01 Pre-Trade Check)
            orderbook = await self.indodax_ws.get_orderbook(decision.symbol)
            res = await self.order_router.route_buy_order(
                symbol=decision.symbol,
                price=price,
                notional_idr=decision.suggested_size_idr,
                take_profit_pct=decision.target_tp_pct,
                stop_loss_pct=decision.target_sl_pct,
                orderbook=orderbook,
                max_hold_time_s=decision.max_hold_time_s,
                strategy=decision.strategy,
            )
            if res.get("success"):
                # Dynamically subscribe to WS orderbook stream for active tracking
                await self.indodax_ws.subscribe_orderbook(decision.symbol)
            elif res.get("mode") in ("INSUFFICIENT_DEPTH", "LIQUIDITY_REJECT"):
                logger.warning(
                    f"[KiBotV2] 🛑 Stage 2 Microstructure blocked {decision.symbol}: {res.get('reason')}"
                )

    async def _telemetry_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            latency = self.council_pool.get_latency_stats()
            drop_rate = self.router.drop_rate_pct()
            tf_eq = self.virtual_ledger.get_total_equity()
            tf_open = len(self.virtual_ledger.open_positions)
            tf_closed = len(self.virtual_ledger.trade_history)

            mr_eq = self.shadow_ledger.get_total_equity() if self.shadow_ledger else 0.0
            mr_open = len(self.shadow_ledger.open_positions) if self.shadow_ledger else 0
            mr_closed = len(self.shadow_ledger.trade_history) if self.shadow_ledger else 0
            
            logger.info(
                f"[Telemetry] 📊 TF Equity: Rp {tf_eq:,.0f} (Open: {tf_open}, Closed: {tf_closed}) | "
                f"MR Shadow: Rp {mr_eq:,.0f} (Open: {mr_open}, Closed: {mr_closed}) | "
                f"Latency (p50: {latency['p50_ms']}ms, p90: {latency['p90_ms']}ms) | Drop: {drop_rate:.1f}%"
            )

    async def stop(self) -> None:
        self._running = False
        logger.info("[KiBotV2] Shutting down pipeline gracefully...")
        await self.indodax_ws.stop()
        await self.binance_ws.stop()
        await self.council_pool.stop()
        await self.enrichment_worker.stop()
        await self.candle_manager.stop()
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
