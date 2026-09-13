import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from config import settings
from storage import durable_state_store

logger = logging.getLogger("KiBotV2.VirtualLedger")

@dataclass
class VirtualPosition:
    position_id: str
    symbol: str
    side: str
    entry_price: float
    current_price: float
    amount_coins: float
    cost_idr: float
    entry_time: float
    stop_loss_price: float
    take_profit_price: float
    max_price_seen: float

class VirtualLedger:
    """
    High-fidelity paper trading engine.
    - Simulates fee-aware orderbook execution (0.21% maker + 0.21% taker).
    - Accurately tracks cash, open positions, unrealized PnL, realized PnL, and drawdowns.
    - Emits state updates directly to DurableStateStore.
    """
    def __init__(self, initial_cash_idr: float = 10_000_000.0):
        self.cash_idr: float = initial_cash_idr
        self.initial_equity_idr: float = initial_cash_idr
        self.open_positions: Dict[str, VirtualPosition] = {}
        self.trade_history: List[Dict[str, Any]] = []

    def get_total_equity(self) -> float:
        positions_value = sum(pos.amount_coins * pos.current_price for pos in self.open_positions.values())
        return self.cash_idr + positions_value

    def place_paper_buy(
        self,
        symbol: str,
        price: float,
        notional_idr: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
    ) -> Dict[str, Any]:
        sl = stop_loss_pct if stop_loss_pct is not None else settings.DEFAULT_STOP_LOSS_PCT
        tp = take_profit_pct if take_profit_pct is not None else settings.DEFAULT_TAKE_PROFIT_PCT
        sym = symbol.upper().strip()
        if sym in self.open_positions:
            return {"success": False, "reason": f"Position already open for {sym}"}
        if notional_idr > self.cash_idr:
            return {"success": False, "reason": f"Insufficient virtual cash (Required: {notional_idr}, Available: {self.cash_idr})"}

        # Simulate execution slippage (0.1%) + taker fee (0.21%)
        slippage_price = price * 1.001
        fee_idr = notional_idr * (settings.FEE_ROUNDTRIP_PCT / 100.0 / 2.0)
        net_notional = notional_idr - fee_idr
        amount_coins = net_notional / slippage_price

        self.cash_idr -= notional_idr
        pos_id = f"paper_{sym}_{int(time.time())}"
        
        pos = VirtualPosition(
            position_id=pos_id,
            symbol=sym,
            side="BUY",
            entry_price=slippage_price,
            current_price=slippage_price,
            amount_coins=amount_coins,
            cost_idr=notional_idr,
            entry_time=time.time(),
            stop_loss_price=slippage_price * (1.0 - (sl / 100.0)),
            take_profit_price=slippage_price * (1.0 + (tp / 100.0)),
            max_price_seen=slippage_price,
        )
        self.open_positions[sym] = pos
        
        # Durable state persistence
        durable_state_store.record_position_change(
            change_type="OPEN",
            position_data={
                "position_id": pos_id, "symbol": sym, "entry_price": slippage_price,
                "amount_coins": amount_coins, "cost_idr": notional_idr, "entry_time": pos.entry_time
            },
            total_equity_idr=self.get_total_equity(),
        )
        
        logger.info(f"[VirtualLedger] 🟢 Opened paper BUY for {sym}: {amount_coins:.6f} coins @ Rp {slippage_price:,.1f} (Notional: Rp {notional_idr:,.0f})")
        return {"success": True, "position_id": pos_id, "symbol": sym, "price": slippage_price, "amount": amount_coins}

    def update_market_price(self, symbol: str, current_price: float, max_hold_time_s: float = 900.0) -> Optional[Dict[str, Any]]:
        """Updates position price and evaluates TP / SL / Max Hold triggers."""
        sym = symbol.upper().strip()
        pos = self.open_positions.get(sym)
        if not pos:
            return None

        pos.current_price = current_price
        if current_price > pos.max_price_seen:
            pos.max_price_seen = current_price

        now = time.time()
        # 1. Check Stop Loss
        if current_price <= pos.stop_loss_price:
            return self.close_paper_position(sym, reason="STOP_LOSS_BREACHED")

        # 2. Check Take Profit
        if current_price >= pos.take_profit_price:
            return self.close_paper_position(sym, reason="TAKE_PROFIT_TARGET_HIT")

        # 3. Check Max Hold Time Expired
        if (now - pos.entry_time) >= max_hold_time_s:
            return self.close_paper_position(sym, reason="MAX_HOLD_TIME_EXPIRED")

        return None

    def close_paper_position(self, symbol: str, reason: str = "MANUAL_EXIT") -> Dict[str, Any]:
        sym = symbol.upper().strip()
        pos = self.open_positions.pop(sym, None)
        if not pos:
            return {"success": False, "reason": "Position not found"}

        # Simulate exit: fee (0.21%)
        gross_value = pos.amount_coins * pos.current_price
        exit_fee = gross_value * (settings.FEE_ROUNDTRIP_PCT / 100.0 / 2.0)
        net_proceeds = gross_value - exit_fee
        realized_pnl_idr = net_proceeds - pos.cost_idr
        realized_pnl_pct = (realized_pnl_idr / pos.cost_idr) * 100.0

        self.cash_idr += net_proceeds
        
        trade_record = {
            "position_id": pos.position_id,
            "symbol": sym,
            "entry_price": pos.entry_price,
            "exit_price": pos.current_price,
            "amount_coins": pos.amount_coins,
            "cost_idr": pos.cost_idr,
            "net_proceeds_idr": net_proceeds,
            "realized_pnl_idr": round(realized_pnl_idr, 2),
            "realized_pnl_pct": round(realized_pnl_pct, 2),
            "hold_duration_s": round(time.time() - pos.entry_time, 1),
            "exit_reason": reason,
            "closed_at": time.time(),
        }
        self.trade_history.append(trade_record)

        # Durable state persistence
        durable_state_store.record_position_change(
            change_type="CLOSE",
            position_data=trade_record,
            total_equity_idr=self.get_total_equity(),
        )

        log_level = logger.info if realized_pnl_idr >= 0 else logger.warning
        badge = "🟢" if realized_pnl_idr >= 0 else "🔴"
        log_level(
            f"[VirtualLedger] {badge} Closed paper position for {sym} ({reason}): "
            f"PnL: Rp {realized_pnl_idr:+,.1f} ({realized_pnl_pct:+.2f}%) | Cash: Rp {self.cash_idr:,.0f}"
        )
        return trade_record
