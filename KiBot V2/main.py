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
from datetime import datetime, timezone
from storage import setup_logging, durable_state_store, StartupReconciler, venue_ledger
from storage.performance_tracker import DailyPerformanceTracker
from executor import OrderRouter, VirtualLedger
from executor.deadman import deadman_switch, cancel_all_if_dead
from paper_trade_runner import PaperTradeRunner
from paper_rotation_runner import RotationPaperRunner
from council.external_regime_consensus import fetch_external_regime, compute_consensus
from council.regime_detector import MarketRegime, detect_regime
from notifications.weekly_reporter import weekly_reporter

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
        self.paper_runner = PaperTradeRunner()
        self.rotation_runner = RotationPaperRunner()
        
        self.indodax_ws = IndodaxWebSocketClient()
        self.binance_ws = BinanceWebSocketClient()
        self.binance_tracker = BinanceLeadLagTracker()
        self.performance_tracker = DailyPerformanceTracker()
        self._last_snapshot_date: str = ""
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

        # 10. Start Daily Telegram Reporter (00:00 WIB)
        weekly_reporter.start(lambda: (self.paper_runner, self.rotation_runner))

        # 11. Start Indodax Deadman Switch Periodic Heartbeat (5m interval, 15m timeout)
        deadman_switch.start()

        # 12. Start External Regime Consensus Loop (getregime.com, 5m interval)
        self._regime_consensus_task = asyncio.create_task(self._regime_consensus_loop())

    async def _regime_consensus_loop(self) -> None:
        """Periodically polls getregime.com (every 300s) and updates consensus for P5 Rotation."""
        while self._running:
            try:
                # 1. Internal regime assessment
                btc_candles = self.candle_manager.get_candles("BTCIDR") if hasattr(self, "candle_manager") else None
                if btc_candles and "closes" in btc_candles and len(btc_candles["closes"]) >= 30:
                    import pandas as pd
                    btc_df = pd.DataFrame({
                        "open": btc_candles.get("opens", btc_candles["closes"]),
                        "high": btc_candles.get("highs", btc_candles["closes"]),
                        "low": btc_candles.get("lows", btc_candles["closes"]),
                        "close": btc_candles["closes"],
                        "volume": btc_candles.get("volumes", [1000.0] * len(btc_candles["closes"])),
                    })
                    internal = detect_regime(btc_ohlcv_1h=btc_df)
                else:
                    internal = getattr(self.rotation_runner, "latest_regime_info", {"regime": MarketRegime.RANGE, "strength": 50.0})

                # 2. Fetch external regime
                external = await fetch_external_regime()

                # 3. Compute consensus
                consensus = compute_consensus(internal, external)

                # 4. Log differences for observability
                int_reg = consensus.get("internal_regime")
                ext_reg = consensus.get("external_regime")
                if ext_reg and int_reg != ext_reg:
                    logger.info(
                        f"[CouncilConsensus] ⚖️ Regime divergence: Internal={int_reg.value.upper() if hasattr(int_reg, 'value') else int_reg} "
                        f"vs External={ext_reg.value.upper() if hasattr(ext_reg, 'value') else ext_reg}. "
                        f"Status: {consensus['consensus_status']} (Damping multiplier: {consensus['damping_multiplier']})"
                    )

                # 5. Apply consensus to rotation runner
                if hasattr(self, "rotation_runner"):
                    curr = dict(self.rotation_runner.latest_regime_info)
                    curr["regime"] = consensus["regime"]
                    curr["strength"] = consensus["strength"]
                    curr["consensus_status"] = consensus["consensus_status"]
                    curr["damping_multiplier"] = consensus["damping_multiplier"]
                    curr["external_regime"] = ext_reg
                    self.rotation_runner.latest_regime_info = curr
                    self.rotation_runner._save_state()
            except Exception as e:
                logger.warning(f"[CouncilConsensus] Error in regime consensus cycle: {e}")

            await asyncio.sleep(300)

    async def _start_health_server(self) -> None:
        try:
            app = web.Application()
            async def handle_health(request):
                tf_equity = self.virtual_ledger.get_total_equity()
                open_positions_detail = []
                total_open_exposure = 0.0

                for sym, pos in self.virtual_ledger.open_positions.items():
                    exposure = pos.amount_coins * pos.current_price
                    total_open_exposure += exposure
                    floating_pnl_idr = exposure - pos.cost_idr
                    floating_pnl_pct = (floating_pnl_idr / pos.cost_idr * 100.0) if pos.cost_idr > 0 else 0.0
                    open_positions_detail.append({
                        "symbol": sym,
                        "side": pos.side,
                        "entry_price": pos.entry_price,
                        "current_price": pos.current_price,
                        "exposure_idr": round(exposure, 2),
                        "floating_pnl_idr": round(floating_pnl_idr, 2),
                        "floating_pnl_pct": round(floating_pnl_pct, 2),
                        "stop_loss_price": pos.stop_loss_price,
                        "take_profit_price": pos.take_profit_price,
                        "tp1_price": pos.partial_tp_price,
                        "tp1_executed": pos.tp1_executed,
                        "strategy": pos.strategy,
                    })

                exposure_pct = round((total_open_exposure / tf_equity * 100.0), 2) if tf_equity > 0 else 0.0

                status_data = {
                    "status": "HEALTHY",
                    "service": "kibot-v2-paper",
                    "mode": "LIVE" if settings.LIVE_TRADING_ENABLED else "PAPER",
                    "uptime_s": round(time.time() - self._start_time, 1),
                    "timestamp": time.time(),
                    "total_equity_idr": tf_equity,
                    "exposure_pct": exposure_pct,
                    "open_positions": len(self.virtual_ledger.open_positions),
                    "active_positions_detail": open_positions_detail,
                    "closed_trades": len(self.virtual_ledger.trade_history),
                    "shadow_mr_equity_idr": self.shadow_ledger.get_total_equity(),
                    "shadow_mr_open_positions": len(self.shadow_ledger.open_positions),
                    "shadow_mr_closed_trades": len(self.shadow_ledger.trade_history),
                    "paper_p1_p4_summary": self.paper_runner.get_summary(),
                    "paper_p5_summary": self.rotation_runner.get_summary() if hasattr(self, "rotation_runner") else None,
                    "is_halted": self.venue_ledger.is_halted,
                    "window_7d_summary": self.performance_tracker.get_7d_summary(
                        current_equity_idr=tf_equity,
                        trade_history=self.virtual_ledger.trade_history,
                    ),
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
        
        # Cross-market momentum & CI enrichment for open positions
        binance_sym = self.binance_tracker.map_indodax_to_binance(pair)
        mom = self.binance_tracker.get_momentum(binance_sym)
        binance_mom_5m = mom.get("return_5m", 0.0)
        
        inds = self.candle_manager.get_indicators(pair) if hasattr(self, "candle_manager") else None
        current_ci = inds.get("choppiness_index") if inds else None

        # Update price on primary virtual ledger (TF) and shadow ledger (MR)
        self.virtual_ledger.update_market_price(
            pair, price, binance_mom_5m=binance_mom_5m, current_ci=current_ci
        )
        if self.shadow_ledger:
            self.shadow_ledger.update_market_price(
                pair, price, binance_mom_5m=binance_mom_5m, current_ci=current_ci
            )
        if hasattr(self, "paper_runner"):
            self.paper_runner.on_ticker(
                symbol=pair, price=price, binance_mom_5m=binance_mom_5m, current_ci=current_ci
            )
        if hasattr(self, "rotation_runner"):
            self.rotation_runner.on_ticker(
                symbol=pair, price=price, binance_mom_5m=binance_mom_5m, current_ci=current_ci
            )
        
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

        # D-08 Fix A: update_live_price patches live cache for valuation only (NOT for entry)
        self.candle_manager.update_live_price(pair, price)
        # D-08 Fix A: get_strategy_indicators() returns CLOSED-bar-only indicators for entry logic
        strategy_inds = self.candle_manager.get_strategy_indicators(pair) or {}
        # get_indicators() returns live-patched snapshot for health/valuation monitoring
        live_inds = self.candle_manager.get_indicators(pair) or {}

        # D-08 Fix B: Determine Binance data freshness status
        binance_sym_freshness = self.binance_tracker.map_indodax_to_binance(pair)
        binance_data_status = "OK" if self.binance_tracker.is_data_fresh(binance_sym_freshness) else "UNKNOWN"

        # Strategy indicators (closed bars only) drive entry decisions
        # Live indicators drive health/valuation display
        candidate_payload = {
            "symbol": pair,
            "price": price,
            "high_24h": high,
            "low_24h": low,
            "volume_idr": vol,
            "volume_ratio": vol_ratio,
            "leadlag_score": leadlag,
            "spread_pct": spread_pct,
            "binance_momentum_1h": bin_mom.get("return_1h") or 0.0,
            "binance_momentum_5m": bin_mom.get("return_5m") or 0.0,
            "binance_momentum_24h": bin_mom.get("return_24h") or 0.0,
            "binance_is_dumping": is_dumping,
            "binance_dump_reason": dump_reason,
            "binance_data_status": binance_data_status,   # D-08 Fix B
            "timestamp": time.time(),
            # Precomputed 1D Swing Indicators — from CLOSED bars only (D-08 Fix A)
            "ema20": strategy_inds.get("ema20", 0.0),
            "ema50": strategy_inds.get("ema50", 0.0),
            "ema100": strategy_inds.get("ema100", 0.0),
            "rsi14": strategy_inds.get("rsi14", 50.0),
            "atr14": strategy_inds.get("atr14", 0.0),
            "volume": strategy_inds.get("volume", 1.0),
            "volume_sma20": strategy_inds.get("volume_sma20", 1.0),
            "lower_bb": strategy_inds.get("lower_bb", 0.0),
            "middle_bb": strategy_inds.get("middle_bb", 0.0),
            "upper_bb": strategy_inds.get("upper_bb", 0.0),
            "adx14": strategy_inds.get("adx14", 20.0),
            "sma20_slope": strategy_inds.get("sma20_slope", 0.0),
            "choppiness_index": strategy_inds.get("choppiness_index", 50.0),
            "volume_zscore": strategy_inds.get("volume_zscore", 0.0),
            "bollinger_pct_b": strategy_inds.get("bollinger_pct_b", 0.5),
            "volume_projected_ratio": strategy_inds.get("volume_projected_ratio", 1.0),
            "prior_bar_volume_ratio": strategy_inds.get("prior_bar_volume_ratio", 1.0),
            "prior_bar_zscore": strategy_inds.get("prior_bar_zscore", 0.0),
            "intraday_tau": live_inds.get("intraday_tau", 1.0),  # live-only field for monitoring
        }
        await self.router.enqueue_candidate(symbol=pair, payload=candidate_payload, score=score)
        if hasattr(self, "paper_runner"):
            self.paper_runner.evaluate_candidate(candidate_payload)
        if hasattr(self, "rotation_runner"):
            self.rotation_runner.evaluate_candidate(candidate_payload)

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
                atr14=getattr(decision, "atr14", 0.0) or float(candidate.get("atr14") or 0.0),
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

            mr_eq = self.shadow_ledger.get_total_equity()
            mr_open = len(self.shadow_ledger.open_positions)
            mr_closed = len(self.shadow_ledger.trade_history)

            total_open_exp = 0.0
            open_summary = []
            for sym, pos in self.virtual_ledger.open_positions.items():
                exp = pos.amount_coins * pos.current_price
                total_open_exp += exp
                pnl_idr = exp - pos.cost_idr
                pnl_pct = (pnl_idr / pos.cost_idr * 100.0) if pos.cost_idr > 0 else 0.0
                open_summary.append(f"{sym}:{pnl_pct:+.2f}%(Rp {pnl_idr:+,.0f})")
            pos_str = f" | Positions: {', '.join(open_summary)}" if open_summary else ""
            exposure_pct = (total_open_exp / tf_eq * 100.0) if tf_eq > 0 else 0.0

            paper_sum = self.paper_runner.get_summary() if hasattr(self, "paper_runner") else {}
            p5_sum = self.rotation_runner.get_summary() if hasattr(self, "rotation_runner") else {}
            p5_str = f" | P5:Rp {p5_sum.get('equity_idr', 100000):,.0f}({p5_sum.get('open_positions', 0)})" if p5_sum else ""
            paper_log_str = " | ".join([f"{c}:Rp {v['equity_idr']:,.0f}({v['open_positions']})" for c, v in paper_sum.items()]) + p5_str
            logger.info(
                f"[Telemetry] 📊 TF Equity: Rp {tf_eq:,.0f} (Open: {tf_open}, Exp: {exposure_pct:.1f}%, Closed: {tf_closed}{pos_str}) | "
                f"MR Shadow: Rp {mr_eq:,.0f} (Open: {mr_open}, Closed: {mr_closed}) | "
                f"Paper P1-P5: {paper_log_str} | "
                f"Latency (p50: {latency['p50_ms']}ms, p90: {latency['p90_ms']}ms) | Drop: {drop_rate:.1f}%"
            )

            # Record daily equity snapshot if date changed or on initial telemetry cycle
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._last_snapshot_date != today_utc:
                try:
                    open_positions_snap = dict(self.virtual_ledger.open_positions)
                    cost_sum = sum(p.cost_idr for p in open_positions_snap.values())
                    snap_open_exp = sum(
                        p.amount_coins * p.current_price for p in open_positions_snap.values()
                    )
                    unrealized_pnl = snap_open_exp - cost_sum
                    self.performance_tracker.record_daily_snapshot(
                        total_equity_idr=tf_eq,
                        cash_idr=self.virtual_ledger.cash_idr,
                        open_positions_count=len(open_positions_snap),
                        unrealized_pnl_idr=unrealized_pnl,
                        trade_history=self.virtual_ledger.trade_history,
                        date_str=today_utc,
                    )
                    self._last_snapshot_date = today_utc
                except Exception as snap_err:
                    logger.warning(f"[Telemetry] Daily snapshot failed (non-fatal): {snap_err}")

    async def stop(self) -> None:
        self._running = False
        logger.info("[KiBotV2] Shutting down pipeline gracefully...")
        await self.indodax_ws.stop()
        await self.binance_ws.stop()
        await self.council_pool.stop()
        await self.enrichment_worker.stop()
        await self.candle_manager.stop()
        self.venue_ledger.stop()
        if hasattr(self, "_regime_consensus_task") and not self._regime_consensus_task.done():
            self._regime_consensus_task.cancel()
        try:
            await cancel_all_if_dead()
            await deadman_switch.stop()
        except Exception as dm_err:
            logger.warning(f"[KiBotV2] Deadman shutdown error: {dm_err}")
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
