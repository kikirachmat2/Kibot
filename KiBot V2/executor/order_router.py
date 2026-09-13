import logging
from typing import Dict, Any, Optional

from .virtual_ledger import VirtualLedger
from config import settings
from risk import RiskGate, CapitalGovernor
from storage import VenueLedger, venue_ledger

logger = logging.getLogger("KiBotV2.OrderRouter")

class OrderRouter:
    """
    Absolute Live Trading Gate & Order Dispatcher.
    - Evaluates RiskGate, CapitalGovernor, and VenueLedger truth halt.
    - Default setting: LIVE_TRADING_ENABLED = False.
    - When false, ALL order mandates are strictly routed to the VirtualLedger.
    - Real Indodax order endpoints (/tapi openOrder) are physically unreachable in this mode.
    """
    def __init__(
        self,
        risk_gate: RiskGate,
        virtual_ledger: Optional[VirtualLedger] = None,
        capital_governor: Optional[CapitalGovernor] = None,
        venue_ledger_instance: Optional[VenueLedger] = None,
    ):
        self.risk_gate = risk_gate
        self.virtual_ledger = virtual_ledger or VirtualLedger()
        self.capital_governor = capital_governor or CapitalGovernor()
        self.venue_ledger = venue_ledger_instance or venue_ledger

    async def route_buy_order(
        self,
        symbol: str,
        price: float,
        notional_idr: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        orderbook: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sl_pct = stop_loss_pct if stop_loss_pct is not None else settings.DEFAULT_STOP_LOSS_PCT
        tp_pct = take_profit_pct if take_profit_pct is not None else settings.DEFAULT_TAKE_PROFIT_PCT

        # 0. Check Venue Truth Reconciliation Halt
        if self.venue_ledger and self.venue_ledger.is_halted:
            reason = f"BLOCKED: Trading halted by VenueLedger ({self.venue_ledger.halt_reason})"
            logger.warning(f"[OrderRouter] 🛑 Order for {symbol} rejected: {reason}")
            return {"success": False, "mode": "REJECTED_BY_VENUE_LEDGER_HALT", "reason": reason}

        # 1. Evaluate Risk Gate
        allow, reason = self.risk_gate.evaluate_new_order(symbol=symbol, notional_idr=notional_idr)
        if not allow:
            logger.warning(f"[OrderRouter] Order for {symbol} rejected by risk gate: {reason}")
            return {"success": False, "mode": "REJECTED_BY_RISK_GATE", "reason": reason}

        # Check if position already open in virtual ledger
        if symbol.upper().strip() in self.virtual_ledger.open_positions:
            logger.debug(f"[OrderRouter] Position already open for {symbol}. Skipping.")
            return {"success": False, "mode": "ALREADY_OPEN", "reason": f"Position already open for {symbol}"}

        # 2. Evaluate Capital Governor (Max Concurrent Positions & Max Total Exposure & Sector Limits)
        if self.capital_governor:
            open_count = len(self.virtual_ledger.open_positions)
            open_exposure = sum(pos.amount_coins * pos.current_price for pos in self.virtual_ledger.open_positions.values())
            total_equity = self.virtual_ledger.get_total_equity()
            open_symbols = list(self.virtual_ledger.open_positions.keys())
            gov_allow, gov_reason = self.capital_governor.evaluate_order_allocation(
                symbol=symbol,
                notional_idr=notional_idr,
                current_open_positions_count=open_count,
                current_open_exposure_idr=open_exposure,
                total_equity_idr=total_equity,
                open_positions_symbols=open_symbols,
            )
            if not gov_allow:
                logger.warning(f"[OrderRouter] Order for {symbol} rejected by Capital Governor: {gov_reason}")
                return {"success": False, "mode": "REJECTED_BY_CAPITAL_GOVERNOR", "reason": gov_reason}

        # 2. Check Live Trading Gate (MANDATORY ENFORCEMENT)
        if not settings.LIVE_TRADING_ENABLED:
            logger.info(f"[OrderRouter] 🔒 LIVE_TRADING_ENABLED=False. Routing {symbol} BUY (Rp {notional_idr:,.0f}) to VirtualLedger.")
            result = self.virtual_ledger.place_paper_buy(
                symbol=symbol,
                price=price,
                notional_idr=notional_idr,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                orderbook=orderbook,
            )
            if result.get("success"):
                self.risk_gate.record_order_placed(symbol)
            result["mode"] = "PAPER_VIRTUAL_LEDGER"
            return result

        # 3. Real Live Order Path (Strictly guarded and intentionally not implemented in Phase 1)
        logger.critical(f"[OrderRouter] 🚨 LIVE TRADING FLAG DETECTED TRUE, but live execution is locked in Phase 1.")
        raise PermissionError("Live trading execution is locked in KiBot V2 Phase 1. Complete GO_LIVE_CHECKLIST first.")
