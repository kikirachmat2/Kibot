"""
Continuous Venue Truth Reconciliation & Venue Ledger for KiBot V2.
Ported from KiBot V1 Core/Treasury/venue_ledger.py & pnl_reconciliation.py.

Core Principles:
1. Exchange-as-Single-Source-of-Truth:
   The internal ledger is NEVER assumed to be infallible. Periodic drift checks
   continually compare internal state against venue truth (durable state anchor
   in paper trading, REST getInfo / exchange orderbook in live trading).
2. Fail-Safe Hard Stop:
   If an unexpected drift or discrepancy exceeds tolerance (e.g. cash discrepancy > Rp 1.000
   or position mismatch), the system IMMEDIATELY halts new trades ('HALT_NEW_TRADES')
   and dispatches a CRITICAL Telegram alert.
3. Strict No-Silent-Auto-Fix Rule:
   Discrepancies are NEVER swept under the rug or auto-adjusted silently.
   Manual operator review and explicit resume are strictly required.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Any, Optional, Tuple, List, Callable, Awaitable
from pathlib import Path

from config import settings
from notifications import telegram_notifier

logger = logging.getLogger("KiBotV2.VenueLedger")


class VenueLedger:
    """
    Continuous Venue Truth Reconciler.
    Monitors drift between internal ledger state and actual venue truth.
    """
    def __init__(
        self,
        drift_tolerance_idr: Optional[float] = None,
        reconcile_interval_s: Optional[float] = None,
    ):
        self.drift_tolerance_idr = (
            drift_tolerance_idr
            if drift_tolerance_idr is not None
            else settings.RECONCILIATION_DRIFT_TOLERANCE_IDR
        )
        self.reconcile_interval_s = (
            reconcile_interval_s
            if reconcile_interval_s is not None
            else settings.RECONCILIATION_INTERVAL_SECONDS
        )

        self.is_halted: bool = False
        self.halt_reason: Optional[str] = None
        self.halted_at: Optional[float] = None
        self.last_reconciled_at: Optional[float] = None
        self.reconciliation_count: int = 0
        self.discrepancies_history: List[Dict[str, Any]] = []

        # Optional custom truth fetcher hook (e.g. for mock injection or REST api)
        self.truth_fetcher_hook: Optional[Callable[[], Awaitable[Dict[str, Any]]]] = None
        self._background_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def fetch_venue_truth(self) -> Dict[str, Any]:
        """
        Fetches ground truth from venue.
        - If custom truth hook is provided, calls it.
        - If LIVE_TRADING_ENABLED, queries Indodax REST getInfo.
        - If Paper Mode, reads durable state store snapshot as ground truth anchor.
        """
        if self.truth_fetcher_hook is not None:
            return await self.truth_fetcher_hook()

        if settings.LIVE_TRADING_ENABLED and settings.INDODAX_KEY and settings.INDODAX_SECRET:
            # Live REST query hook
            from storage.reconciler import StartupReconciler
            reconciler = StartupReconciler()
            balance = await reconciler.fetch_exchange_balance_safe()
            if balance is not None:
                cash_idr = float(balance.get("idr", 0.0))
                # Positions / coin balances
                coins = {k.upper(): float(v) for k, v in balance.items() if k != "idr" and float(v) > 0}
                return {"cash_idr": cash_idr, "positions": coins, "source": "INDODAX_REST_API"}

        # In Paper Mode: query durable state store
        from storage.durable_state import durable_state_store
        snapshot = durable_state_store.get_latest_snapshot()
        if snapshot:
            return {
                "cash_idr": float(snapshot.get("cash_idr") or snapshot.get("equity_idr", 10_000_000.0)),
                "positions": snapshot.get("open_positions", {}),
                "source": "DURABLE_STATE_SNAPSHOT",
            }

        return {
            "cash_idr": 10_000_000.0,
            "positions": {},
            "source": "DEFAULT_PAPER_ANCHOR",
        }

    async def reconcile_once(self, virtual_ledger: Any) -> Dict[str, Any]:
        """
        Performs a single atomic reconciliation between VirtualLedger and Venue Truth.
        """
        now = time.time()
        self.last_reconciled_at = now
        self.reconciliation_count += 1

        truth = await self.fetch_venue_truth()
        truth_cash = float(truth.get("cash_idr", 0.0))
        truth_positions = truth.get("positions", {})

        internal_cash = float(virtual_ledger.cash_idr)
        internal_positions = virtual_ledger.open_positions

        cash_drift = abs(internal_cash - truth_cash)
        drift_exceeded = cash_drift > self.drift_tolerance_idr

        discrepancies = []
        if drift_exceeded:
            discrepancies.append({
                "type": "CASH_BALANCE_DRIFT",
                "internal_cash_idr": internal_cash,
                "truth_cash_idr": truth_cash,
                "drift_idr": round(cash_drift, 2),
                "tolerance_idr": self.drift_tolerance_idr,
            })

        # Check for symbol discrepancies if truth has explicit positions
        if isinstance(truth_positions, dict) and truth_positions:
            internal_symbols = set(k.upper().strip() for k in internal_positions.keys())
            truth_symbols = set(k.upper().strip() for k in truth_positions.keys())
            
            missing_in_internal = truth_symbols - internal_symbols
            missing_in_truth = internal_symbols - truth_symbols
            
            if missing_in_internal or missing_in_truth:
                discrepancies.append({
                    "type": "POSITION_MISMATCH",
                    "missing_in_internal": list(missing_in_internal),
                    "missing_in_truth": list(missing_in_truth),
                })

        result = {
            "reconciled_at": now,
            "reconciliation_count": self.reconciliation_count,
            "internal_cash_idr": internal_cash,
            "truth_cash_idr": truth_cash,
            "cash_drift_idr": round(cash_drift, 2),
            "discrepancies": discrepancies,
            "status": "PASS" if not discrepancies else "FAIL",
        }

        if discrepancies and not self.is_halted:
            self._trigger_halt(
                reason=(
                    f"Venue truth reconciliation drift detected: "
                    f"Cash drift Rp {cash_drift:+,.0f} (Internal: Rp {internal_cash:,.0f} vs Truth: Rp {truth_cash:,.0f}), "
                    f"tolerance: Rp {self.drift_tolerance_idr:,.0f}. Discrepancies: {discrepancies}"
                ),
                details=result,
            )

        return result

    def _trigger_halt(self, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
        """
        Activates HALT_NEW_TRADES mode and dispatches Telegram CRITICAL alert.
        Strictly NO silent auto-fix.
        """
        self.is_halted = True
        self.halt_reason = reason
        self.halted_at = time.time()
        self.discrepancies_history.append({
            "timestamp": self.halted_at,
            "reason": reason,
            "details": details or {},
        })

        logger.critical(f"🚨 [VENUE LEDGER RECONCILIATION HALT] {reason}")

        telegram_notifier.send_alert_non_blocking(
            event_type="RECONCILIATION_DRIFT_HALT",
            title="🚨 CRITICAL: VENUE RECONCILIATION DRIFT - TRADING HALTED",
            message=(
                f"Sovereign venue reconciliation detected an unverified drift against venue truth!\n\n"
                f"• Mode: `HALT_NEW_TRADES` (All new buy orders are locked)\n"
                f"• Reason: {reason}\n\n"
                f"⚠️ STRICT RULE: Auto-fix is disabled. Manual operator review is required."
            ),
            severity="CRITICAL",
            details=details,
            force=True,
        )

    def resume_trading(self, operator_note: str) -> None:
        """
        Manual override by operator to clear the halt after review.
        """
        logger.warning(f"⚠️ [VENUE LEDGER RESUMED] Trading resumed by operator. Note: {operator_note}")
        self.is_halted = False
        self.halt_reason = None
        self.halted_at = None

    async def start_periodic_loop(self, virtual_ledger: Any) -> None:
        """
        Starts the periodic continuous reconciliation loop.
        """
        self._running = True
        logger.info(f"[VenueLedger] Starting continuous truth reconciliation every {self.reconcile_interval_s:.0f}s...")
        while self._running:
            try:
                await asyncio.sleep(self.reconcile_interval_s)
                if not self._running:
                    break
                await self.reconcile_once(virtual_ledger)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[VenueLedger] Exception during periodic reconciliation: {e}")

    def stop(self) -> None:
        self._running = False
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()

    def state_dict(self) -> Dict[str, Any]:
        return {
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "halted_at": self.halted_at,
            "last_reconciled_at": self.last_reconciled_at,
            "reconciliation_count": self.reconciliation_count,
            "drift_tolerance_idr": self.drift_tolerance_idr,
            "reconcile_interval_s": self.reconcile_interval_s,
        }


venue_ledger = VenueLedger()
