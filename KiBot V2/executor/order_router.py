import logging
from typing import Dict, Any, Optional

from .virtual_ledger import VirtualLedger
from config import settings
from risk import RiskGate

logger = logging.getLogger("KiBotV2.OrderRouter")

class OrderRouter:
    """
    Absolute Live Trading Gate & Order Dispatcher.
    - Default setting: LIVE_TRADING_ENABLED = False.
    - When false, ALL order mandates are strictly routed to the VirtualLedger.
    - Real Indodax order endpoints (/tapi openOrder) are physically unreachable in this mode.
    """
    def __init__(
        self,
        risk_gate: RiskGate,
        virtual_ledger: Optional[VirtualLedger] = None,
    ):
        self.risk_gate = risk_gate
        self.virtual_ledger = virtual_ledger or VirtualLedger()

    async def route_buy_order(
        self,
        symbol: str,
        price: float,
        notional_idr: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        sl_pct = stop_loss_pct if stop_loss_pct is not None else settings.DEFAULT_STOP_LOSS_PCT
        tp_pct = take_profit_pct if take_profit_pct is not None else settings.DEFAULT_TAKE_PROFIT_PCT
        # 1. Evaluate Risk Gate
        allow, reason = self.risk_gate.evaluate_new_order(symbol=symbol, notional_idr=notional_idr)
        if not allow:
            logger.warning(f"[OrderRouter] Order for {symbol} rejected by risk gate: {reason}")
            return {"success": False, "mode": "REJECTED_BY_RISK_GATE", "reason": reason}

        # Check if position already open in virtual ledger
        if symbol.upper().strip() in self.virtual_ledger.open_positions:
            logger.debug(f"[OrderRouter] Position already open for {symbol}. Skipping.")
            return {"success": False, "mode": "ALREADY_OPEN", "reason": f"Position already open for {symbol}"}

        # 2. Check Live Trading Gate (MANDATORY ENFORCEMENT)
        if not settings.LIVE_TRADING_ENABLED:
            logger.info(f"[OrderRouter] 🔒 LIVE_TRADING_ENABLED=False. Routing {symbol} BUY (Rp {notional_idr:,.0f}) to VirtualLedger.")
            result = self.virtual_ledger.place_paper_buy(
                symbol=symbol,
                price=price,
                notional_idr=notional_idr,
                stop_loss_pct=sl_pct,
                take_profit_pct=tp_pct,
            )
            if result.get("success"):
                self.risk_gate.record_order_placed(symbol)
            result["mode"] = "PAPER_VIRTUAL_LEDGER"
            return result

        # 3. Real Live Order Path (Strictly guarded and intentionally not implemented in Phase 1)
        logger.critical(f"[OrderRouter] 🚨 LIVE TRADING FLAG DETECTED TRUE, but live execution is locked in Phase 1.")
        raise PermissionError("Live trading execution is locked in KiBot V2 Phase 1. Complete GO_LIVE_CHECKLIST first.")
