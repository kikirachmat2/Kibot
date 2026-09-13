import json
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
        self.peak_equity_idr: float = initial_cash_idr
        self.open_positions: Dict[str, VirtualPosition] = {}
        self.trade_history: List[Dict[str, Any]] = []

    def get_total_equity(self) -> float:
        positions_value = sum(pos.amount_coins * pos.current_price for pos in self.open_positions.values())
        total = self.cash_idr + positions_value
        if total > self.peak_equity_idr:
            self.peak_equity_idr = total
        return total

    def place_paper_buy(
        self,
        symbol: str,
        price: float,
        notional_idr: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        orderbook: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sl = stop_loss_pct if stop_loss_pct is not None else settings.DEFAULT_STOP_LOSS_PCT
        tp = take_profit_pct if take_profit_pct is not None else settings.DEFAULT_TAKE_PROFIT_PCT
        sym = symbol.upper().strip()
        if sym in self.open_positions:
            return {"success": False, "reason": f"Position already open for {sym}"}
        if notional_idr > self.cash_idr:
            return {"success": False, "reason": f"Insufficient virtual cash (Required: {notional_idr}, Available: {self.cash_idr})"}

        # Calculate realistic execution price (Real orderbook depth VWAP or fallback to 0.1% static slippage)
        slippage_price = price * 1.001
        slippage_pct = 0.1

        if orderbook:
            from enrichment.microstructure import microstructure_analyzer
            analysis = microstructure_analyzer.analyze_orderbook(orderbook, notional_idr, side="BUY")
            if not analysis.is_depth_sufficient:
                # GAP-01 Pre-trade check: Reject orders exceeding available orderbook depth
                return {
                    "success": False,
                    "mode": "INSUFFICIENT_DEPTH",
                    "reason": analysis.reason,
                }
            if not analysis.pass_liquidity:
                return {
                    "success": False,
                    "mode": "LIQUIDITY_REJECT",
                    "reason": analysis.reason,
                }
            slippage_price = analysis.avg_fill_price
            slippage_pct = analysis.slippage_pct

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
        self._prune_trade_history_if_needed()

        # Durable state persistence
        durable_state_store.record_position_change(
            change_type="CLOSE",
            position_data=trade_record,
            total_equity_idr=self.get_total_equity(),
        )

        # Automatic live readiness evaluation & milestone tracking
        try:
            from storage.live_readiness import live_readiness_evaluator
            current_eq = self.get_total_equity()
            dd_pct = ((self.peak_equity_idr - current_eq) / self.peak_equity_idr * 100.0) if self.peak_equity_idr > 0 else 0.0
            live_readiness_evaluator.evaluate_trades(
                trade_history=self.trade_history,
                current_equity_idr=current_eq,
                initial_bankroll_idr=self.initial_equity_idr,
                peak_equity_idr=self.peak_equity_idr,
                current_drawdown_pct=max(0.0, dd_pct),
            )
        except Exception as eval_exc:
            logger.error(f"[VirtualLedger] Live readiness evaluation error: {eval_exc}")

        log_level = logger.info if realized_pnl_idr >= 0 else logger.warning
        badge = "🟢" if realized_pnl_idr >= 0 else "🔴"
        log_level(
            f"[VirtualLedger] {badge} Closed paper position for {sym} ({reason}): "
            f"PnL: Rp {realized_pnl_idr:+,.1f} ({realized_pnl_pct:+.2f}%) | Cash: Rp {self.cash_idr:,.0f}"
        )
        return trade_record

    def _prune_trade_history_if_needed(self) -> None:
        max_trades = getattr(settings, "MAX_IN_MEMORY_TRADES", 500)
        if len(self.trade_history) > max_trades:
            excess = len(self.trade_history) - max_trades
            to_archive = self.trade_history[:excess]
            # WHAT IF: Archive I/O fails? We slice in-memory list first to strictly protect process RAM.
            self.trade_history = self.trade_history[excess:]
            self._write_archive(to_archive)

    def _write_archive(self, trades: List[Dict[str, Any]]) -> None:
        try:
            archive_path = settings.STATE_DIR / "trades_archive.jsonl"
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with open(archive_path, "a", encoding="utf-8") as f:
                for trade in trades:
                    f.write(json.dumps(trade) + "\n")
        except Exception as exc:
            # Failure scenario: disk full or permission error.
            # In-memory list is already safely pruned; log error and do not crash trading engine.
            logger.error(f"[VirtualLedger] Failed to write {len(trades)} trades to archive: {exc}")

