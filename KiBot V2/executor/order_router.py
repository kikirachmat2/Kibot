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
        shadow_ledger: Optional[VirtualLedger] = None,
        capital_governor: Optional[CapitalGovernor] = None,
        venue_ledger_instance: Optional[VenueLedger] = None,
    ):
        self.risk_gate = risk_gate
        self.virtual_ledger = virtual_ledger or VirtualLedger(name="PRIMARY_TF")
        self.shadow_ledger = shadow_ledger
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
        max_hold_time_s: Optional[float] = None,
        strategy: Optional[str] = None,
        atr14: Optional[float] = None,
    ) -> Dict[str, Any]:
        sl_pct = stop_loss_pct if stop_loss_pct is not None else settings.DEFAULT_STOP_LOSS_PCT
        tp_pct = take_profit_pct if take_profit_pct is not None else settings.DEFAULT_TAKE_PROFIT_PCT

        # Determine target ledger based on strategy
        # MEAN_REVERSION is strictly isolated in shadow_ledger (per SWING_STRATEGY_DESIGN.md)
        if strategy == "MEAN_REVERSION" and self.shadow_ledger is not None:
            target_ledger = self.shadow_ledger
            is_shadow = True
        else:
            target_ledger = self.virtual_ledger
            is_shadow = False

        # 0. Check Venue Truth Reconciliation Halt (applies to primary ledger trades)
        if not is_shadow and self.venue_ledger and self.venue_ledger.is_halted:
            reason = f"BLOCKED: Trading halted by VenueLedger ({self.venue_ledger.halt_reason})"
            logger.warning(f"[OrderRouter] 🛑 Order for {symbol} rejected: {reason}")
            return {"success": False, "mode": "REJECTED_BY_VENUE_LEDGER_HALT", "reason": reason}

        # 1. Evaluate Risk Gate
        allow, reason = self.risk_gate.evaluate_new_order(symbol=symbol, notional_idr=notional_idr)
        if not allow:
            logger.warning(f"[OrderRouter] Order for {symbol} rejected by risk gate: {reason}")
            return {"success": False, "mode": "REJECTED_BY_RISK_GATE", "reason": reason}

        # Check if position already open in target ledger
        if symbol.upper().strip() in target_ledger.open_positions:
            logger.debug(f"[OrderRouter] Position already open for {symbol} in {target_ledger.name}. Skipping.")
            return {"success": False, "mode": "ALREADY_OPEN", "reason": f"Position already open for {symbol} in {target_ledger.name}"}

        # 2. Evaluate Capital Governor on target ledger's portfolio
        if self.capital_governor:
            open_count = len(target_ledger.open_positions)
            open_exposure = sum(pos.amount_coins * pos.current_price for pos in target_ledger.open_positions.values())
            total_equity = target_ledger.get_total_equity()
            open_symbols = list(target_ledger.open_positions.keys())
            trade_hist = getattr(target_ledger, "trade_history", [])
            gov_allow, gov_reason = self.capital_governor.evaluate_order_allocation(
                symbol=symbol,
                notional_idr=notional_idr,
                current_open_positions_count=open_count,
                current_open_exposure_idr=open_exposure,
                total_equity_idr=total_equity,
                open_positions_symbols=open_symbols,
                trade_history=trade_hist,
            )
            if not gov_allow:
                logger.warning(f"[OrderRouter] Order for {symbol} ({strategy}) rejected by Capital Governor: {gov_reason}")
                return {"success": False, "mode": "REJECTED_BY_CAPITAL_GOVERNOR", "reason": gov_reason}

        # 3. Check Live Trading Gate (MANDATORY ENFORCEMENT)
        # Note: Mean-Reversion is PERMANENTLY locked to shadow paper mode until N>=20 & PF>=1.25 are validated
        if not settings.LIVE_TRADING_ENABLED or is_shadow:
            ledger_desc = "ShadowLedger" if is_shadow else "VirtualLedger"
            logger.info(f"[OrderRouter] 🔒 Routing {symbol} BUY (Rp {notional_idr:,.0f}) to {ledger_desc} ({target_ledger.name} / {strategy}).")
            result = target_ledger.place_paper_buy(
                symbol=symbol,
                price=price,
                notional_idr=notional_idr,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
                orderbook=orderbook,
                max_hold_time_s=max_hold_time_s,
                strategy=strategy,
                atr14=atr14,
            )
            if result.get("success"):
                self.risk_gate.record_order_placed(symbol)
            result["mode"] = "PAPER_SHADOW_LEDGER" if is_shadow else "PAPER_VIRTUAL_LEDGER"
            result["ledger"] = target_ledger.name
            return result

        # 4. Real Live Order Path (Strictly guarded and intentionally not implemented in Phase 1)
        logger.critical(f"[OrderRouter] 🚨 LIVE TRADING FLAG DETECTED TRUE, but live execution is locked in Phase 1.")
        raise PermissionError("Live trading execution is locked in KiBot V2 Phase 1. Complete GO_LIVE_CHECKLIST first.")
