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
    max_hold_time_s: float = 21 * 86400.0
    strategy: str = "SWING"
    partial_tp_pct: float = 50.0
    partial_tp_price: float = 0.0
    tp1_executed: bool = False
    partial_pnl_idr: float = 0.0
    initial_cost_idr: float = 0.0
    atr14: float = 0.0
    current_ci: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "position_id": self.position_id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "amount_coins": self.amount_coins,
            "cost_idr": self.cost_idr,
            "initial_cost_idr": self.initial_cost_idr or self.cost_idr,
            "entry_time": self.entry_time,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "max_price_seen": self.max_price_seen,
            "max_hold_time_s": self.max_hold_time_s,
            "strategy": self.strategy,
            "partial_tp_pct": self.partial_tp_pct,
            "partial_tp_price": self.partial_tp_price,
            "tp1_executed": self.tp1_executed,
            "partial_pnl_idr": self.partial_pnl_idr,
            "atr14": self.atr14,
            "current_ci": self.current_ci,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VirtualPosition":
        sym = str(data.get("symbol", "")).upper().strip()
        entry_price = float(data.get("entry_price", 0.0))
        current_price = float(data.get("current_price", entry_price))
        amount_coins = float(data.get("amount_coins", 0.0))
        cost_idr = float(data.get("cost_idr", 0.0))
        if cost_idr <= 0.0 and amount_coins > 0.0 and entry_price > 0.0:
            cost_idr = amount_coins * entry_price

        initial_cost_idr = float(data.get("initial_cost_idr", cost_idr))

        sl = float(data.get("stop_loss_price", 0.0))
        tp = float(data.get("take_profit_price", 0.0))
        if sl <= 0.0 and entry_price > 0.0:
            sl = entry_price * (1.0 - (settings.DEFAULT_STOP_LOSS_PCT / 100.0))
        if tp <= 0.0 and entry_price > 0.0:
            tp = entry_price * (1.0 + (settings.DEFAULT_TAKE_PROFIT_PCT / 100.0))

        strategy = str(data.get("strategy", "SWING"))
        default_hold = 10 * 86400.0 if "MEAN_REVERSION" in strategy else 21 * 86400.0
        max_hold_time_s = float(data.get("max_hold_time_s", default_hold))

        pos_id = str(data.get("position_id", f"paper_{sym}_{int(data.get('entry_time', time.time()))}"))
        side = str(data.get("side", "BUY"))
        entry_time = float(data.get("entry_time", time.time()))
        max_seen = float(data.get("max_price_seen", max(entry_price, current_price)))

        partial_tp_pct = float(data.get("partial_tp_pct", 50.0))
        tp1_executed = bool(data.get("tp1_executed", False))
        partial_pnl_idr = float(data.get("partial_pnl_idr", 0.0))
        partial_tp_price = float(data.get("partial_tp_price", 0.0))
        if partial_tp_price <= 0.0 and entry_price > 0.0 and tp > entry_price:
            tp_delta = tp - entry_price
            partial_tp_price = entry_price + (tp_delta * (partial_tp_pct / 100.0))

        atr14 = float(data.get("atr14", 0.0))
        current_ci = float(data.get("current_ci", 50.0))

        return cls(
            position_id=pos_id,
            symbol=sym,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            amount_coins=amount_coins,
            cost_idr=cost_idr,
            entry_time=entry_time,
            stop_loss_price=sl,
            take_profit_price=tp,
            max_price_seen=max_seen,
            max_hold_time_s=max_hold_time_s,
            strategy=strategy,
            partial_tp_pct=partial_tp_pct,
            partial_tp_price=partial_tp_price,
            tp1_executed=tp1_executed,
            partial_pnl_idr=partial_pnl_idr,
            initial_cost_idr=initial_cost_idr,
            atr14=atr14,
            current_ci=current_ci,
        )

class VirtualLedger:
    """
    High-fidelity paper trading engine.
    - Simulates fee-aware orderbook execution (0.21% maker + 0.21% taker).
    - Accurately tracks cash, open positions, unrealized PnL, realized PnL, and drawdowns.
    - Emits state updates directly to DurableStateStore.
    """
    def __init__(
        self,
        initial_cash_idr: float = 10_000_000.0,
        name: str = "PRIMARY_TF",
        readiness_evaluator: Optional[Any] = None,
        fee_pct: Optional[float] = None,
        max_positions: int = 10,
    ):
        self.name = name
        self.readiness_evaluator = readiness_evaluator
        self.fee_pct = fee_pct
        self.max_positions = max_positions
        self.cash_idr: float = initial_cash_idr
        self.initial_equity_idr: float = initial_cash_idr
        self.peak_equity_idr: float = initial_cash_idr
        self.open_positions: Dict[str, VirtualPosition] = {}
        self.trade_history: List[Dict[str, Any]] = []
        self.on_trade_closed_cb: Optional[Any] = None

    def get_total_equity(self) -> float:
        positions_value = sum(pos.amount_coins * pos.current_price for pos in self.open_positions.values())
        total = self.cash_idr + positions_value
        if total > self.peak_equity_idr:
            self.peak_equity_idr = total
        return total

    def restore_state(
        self,
        cash_idr: Optional[float] = None,
        open_positions_data: Optional[Dict[str, Any]] = None,
        trade_history_data: Optional[List[Dict[str, Any]]] = None,
        peak_equity_idr: Optional[float] = None,
    ) -> None:
        """
        Restores ledger state from durable storage on startup.
        Re-hydrates open_positions as VirtualPosition dataclass instances,
        restores trade_history, updates cash, and re-evaluates live readiness.
        """
        if cash_idr is not None and cash_idr >= 0:
            self.cash_idr = float(cash_idr)

        if open_positions_data:

            self.open_positions.clear()
            for sym, pos_data in open_positions_data.items():
                if isinstance(pos_data, dict):
                    pos = VirtualPosition.from_dict(pos_data)
                    self.open_positions[pos.symbol] = pos
                elif isinstance(pos_data, VirtualPosition):
                    self.open_positions[pos_data.symbol] = pos_data

        if trade_history_data:
            self.trade_history = list(trade_history_data)
            self._prune_trade_history_if_needed()

        # Recalculate total equity and peak equity
        current_eq = self.get_total_equity()
        if peak_equity_idr is not None and peak_equity_idr > 0:
            self.peak_equity_idr = max(peak_equity_idr, current_eq, self.peak_equity_idr)
        else:
            self.peak_equity_idr = max(self.peak_equity_idr, current_eq)

        # Re-evaluate live readiness if evaluator present and trade history exists
        if self.trade_history:
            try:
                evaluator = self.readiness_evaluator
                if not evaluator:
                    from storage.live_readiness import live_readiness_evaluator
                    evaluator = live_readiness_evaluator
                dd_pct = ((self.peak_equity_idr - current_eq) / self.peak_equity_idr * 100.0) if self.peak_equity_idr > 0 else 0.0
                evaluator.evaluate_trades(
                    trade_history=self.trade_history,
                    current_equity_idr=current_eq,
                    initial_bankroll_idr=self.initial_equity_idr,
                    peak_equity_idr=self.peak_equity_idr,
                    current_drawdown_pct=max(0.0, dd_pct),
                )
            except Exception as exc:
                logger.warning(f"[VirtualLedger:{self.name}] Error re-evaluating readiness on restore: {exc}")

        logger.info(
            f"[VirtualLedger:{self.name}] 🔄 Restored state: Cash=Rp {self.cash_idr:,.0f} | "
            f"Open Positions={len(self.open_positions)} | Trades History={len(self.trade_history)} | "
            f"Equity=Rp {current_eq:,.0f}"
        )

    def place_paper_buy(
        self,
        symbol: str,
        price: float,
        notional_idr: float,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        orderbook: Optional[Dict[str, Any]] = None,
        max_hold_time_s: Optional[float] = None,
        strategy: Optional[str] = None,
        partial_tp_pct: Optional[float] = None,
        partial_tp_price: Optional[float] = None,
        atr14: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Executes a paper BUY order.
        Simulates realistic execution:
        - If L2 orderbook is supplied: walks depth to calculate true VWAP and market-impact slippage.
        - Enforces minimum executable liquidity before filling.
        - Deducts roundtrip exchange fee (0.21%).
        """
        sym = symbol.upper().strip()
        if notional_idr <= 0:
            return {"success": False, "mode": "INVALID_NOTIONAL", "reason": "Target notional must be strictly positive"}

        if self.cash_idr < notional_idr:
            return {"success": False, "mode": "INSUFFICIENT_FUNDS", "reason": f"Cash Rp {self.cash_idr:,.0f} < required Rp {notional_idr:,.0f}"}

        if sym in self.open_positions:
            return {"success": False, "reason": f"Position already open for {sym}"}

        sl = stop_loss_pct if stop_loss_pct is not None else settings.DEFAULT_STOP_LOSS_PCT
        tp = take_profit_pct if take_profit_pct is not None else settings.DEFAULT_TAKE_PROFIT_PCT

        # Calculate realistic execution price (Real orderbook depth VWAP or fallback to 0.1% static slippage)
        slippage_price = price * 1.001
        slippage_pct = 0.1

        # Stage 2 Execution: Real depth & VWAP modeling
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
                logger.warning(f"[VirtualLedger:{self.name}] 🛑 Order rejected for {sym}: {analysis.reason}")
                return {
                    "success": False,
                    "mode": "LIQUIDITY_REJECT",
                    "reason": analysis.reason,
                }
            slippage_price = analysis.avg_fill_price
            slippage_pct = analysis.slippage_pct

        effective_fee_rate = (self.fee_pct / 100.0) if self.fee_pct is not None else (settings.FEE_ROUNDTRIP_PCT / 100.0 / 2.0)
        fee_idr = notional_idr * effective_fee_rate
        net_notional = notional_idr - fee_idr
        amount_coins = net_notional / slippage_price

        self.cash_idr -= notional_idr
        pos_id = f"paper_{sym}_{int(time.time())}"
        
        hold_time = float(max_hold_time_s) if (max_hold_time_s is not None and max_hold_time_s > 0) else (21.0 * 86400.0)
        strat_name = strategy or "SWING"

        tp_target_price = slippage_price * (1.0 + (tp / 100.0))
        is_p_variant = self.name.startswith("PAPER_P") or (strat_name in ("P1", "P2", "P3", "P4"))
        p_tp_pct = float(partial_tp_pct) if partial_tp_pct is not None else (0.0 if is_p_variant else 50.0)
        if partial_tp_price is not None and partial_tp_price > 0:
            p_tp_price = float(partial_tp_price)
        elif is_p_variant:
            p_tp_price = 0.0
        else:
            tp_delta = tp_target_price - slippage_price
            p_tp_price = slippage_price + (tp_delta * (p_tp_pct / 100.0))

        calc_atr = float(atr14) if (atr14 is not None and atr14 > 0) else (slippage_price * 0.035)

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
            take_profit_price=tp_target_price,
            max_price_seen=slippage_price,
            max_hold_time_s=hold_time,
            strategy=strat_name,
            partial_tp_pct=p_tp_pct,
            partial_tp_price=p_tp_price,
            tp1_executed=False,
            partial_pnl_idr=0.0,
            initial_cost_idr=notional_idr,
            atr14=calc_atr,
        )
        self.open_positions[sym] = pos
        
        # Durable state persistence (strictly isolated to core PRIMARY_TF and SHADOW_MR)
        if self.name in ("PRIMARY_TF", "SHADOW_MR"):
            pos_dict = pos.to_dict()
            pos_dict["ledger"] = self.name
            durable_state_store.record_position_change(
                change_type="OPEN",
                position_data=pos_dict,
                total_equity_idr=self.get_total_equity(),
                ledger_name=self.name,
                cash_idr=self.cash_idr,
            )

        
        logger.info(
            f"[VirtualLedger:{self.name}] 🟢 Opened paper BUY for {sym}: {amount_coins:.6f} coins @ Rp {slippage_price:,.1f} "
            f"(Notional: Rp {notional_idr:,.0f}) | Strat: {strat_name} | TP1: Rp {p_tp_price:,.1f} ({p_tp_pct:.0f}%) | "
            f"TP2: Rp {tp_target_price:,.1f} | MaxHold: {hold_time/86400:.1f}d"
        )
        return {"success": True, "position_id": pos_id, "symbol": sym, "price": slippage_price, "amount": amount_coins}

    def execute_partial_tp(self, symbol: str, current_price: float) -> Optional[Dict[str, Any]]:
        """
        Executes Tier 1 Partial Take Profit (Capital Recycling):
        - Closes 50% of the position coins.
        - Returns recycled capital + realized profit back into cash ledger.
        - Ratchets stop-loss of remaining 50% runner to Break-Even (Entry + 0.52% fee buffer).
        - Position remains OPEN for the runner to catch fat tails.
        """
        sym = symbol.upper().strip()
        pos = self.open_positions.get(sym)
        if not pos or pos.tp1_executed:
            return None

        frac = pos.partial_tp_pct / 100.0
        coins_to_close = pos.amount_coins * frac
        cost_of_closed = pos.cost_idr * frac

        gross_proceeds = coins_to_close * current_price
        remaining_coins = pos.amount_coins - coins_to_close
        remaining_val = remaining_coins * current_price
        if gross_proceeds < 10_000.0 or remaining_val < 10_000.0:
            logger.warning(
                f"[VirtualLedger:{self.name}] ⚠️ Partial TP skipped for {sym}: "
                f"lot value (close: Rp {gross_proceeds:,.0f}, remain: Rp {remaining_val:,.0f}) < Rp 10,000 minimum lot size."
            )
            return None

        effective_fee_rate = (self.fee_pct / 100.0) if self.fee_pct is not None else (settings.FEE_ROUNDTRIP_PCT / 100.0 / 2.0)
        exit_fee = gross_proceeds * effective_fee_rate
        net_proceeds = gross_proceeds - exit_fee
        partial_pnl_idr = net_proceeds - cost_of_closed
        partial_pnl_pct = (partial_pnl_idr / cost_of_closed * 100.0) if cost_of_closed > 0 else 0.0

        # Adjust position in memory
        pos.amount_coins -= coins_to_close
        pos.cost_idr -= cost_of_closed
        pos.tp1_executed = True
        pos.partial_pnl_idr = partial_pnl_idr

        # Break-Even Ratchet: Entry + roundtrip fee buffer (fee_pct*2 + 0.1% slippage)
        bep_price = pos.entry_price * 1.0052
        pos.stop_loss_price = round(max(pos.stop_loss_price, bep_price), 2)

        # Capital Recycling: Inject recycled cash back into ledger
        self.cash_idr += net_proceeds

        partial_record = {
            "position_id": pos.position_id,
            "symbol": sym,
            "closed_coins": coins_to_close,
            "remaining_coins": pos.amount_coins,
            "tp1_price": current_price,
            "net_proceeds_idr": net_proceeds,
            "partial_pnl_idr": round(partial_pnl_idr, 2),
            "partial_pnl_pct": round(partial_pnl_pct, 2),
            "ratcheted_sl": pos.stop_loss_price,
            "timestamp": time.time(),
            "ledger": self.name,
        }

        # Durable state persistence (strictly isolated to core PRIMARY_TF and SHADOW_MR)
        if self.name in ("PRIMARY_TF", "SHADOW_MR"):
            pos_dict = pos.to_dict()
            pos_dict["ledger"] = self.name
            durable_state_store.record_position_change(
                change_type="PARTIAL",
                position_data=pos_dict,
                total_equity_idr=self.get_total_equity(),
                ledger_name=self.name,
                cash_idr=self.cash_idr,
            )


        logger.info(
            f"[VirtualLedger:{self.name}] 🎯 Tier 1 TP1 Executed for {sym}: "
            f"Closed {frac*100:.0f}% @ Rp {current_price:,.1f} | Recycled Cash: +Rp {net_proceeds:,.0f} "
            f"| Profit: Rp {partial_pnl_idr:+,.1f} ({partial_pnl_pct:+.2f}%) | "
            f"SL Ratcheted to BEP: Rp {pos.stop_loss_price:,.1f}"
        )
        return partial_record

    def update_market_price(
        self,
        symbol: str,
        current_price: float,
        max_hold_time_s: Optional[float] = None,
        binance_mom_5m: float = 0.0,
        current_ci: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Updates position price and evaluates TP / SL / Emergency Ratchet / Stagnation / Max Hold triggers."""
        sym = symbol.upper().strip()
        pos = self.open_positions.get(sym)
        if not pos:
            return None

        pos.current_price = current_price
        if current_ci is not None:
            pos.current_ci = current_ci
        if current_price > pos.max_price_seen:
            pos.max_price_seen = current_price

        now = time.time()

        # Cross-Market Emergency De-Risking Ratchet (Lead-Lag Protection)
        if binance_mom_5m <= -0.020:
            emergency_sl = round(current_price * 0.990, 2)
            if emergency_sl > pos.stop_loss_price:
                logger.warning(
                    f"[VirtualLedger:{self.name}] 🚨 Cross-market flash crash detected on {sym} "
                    f"(Binance 5m: {binance_mom_5m*100:.2f}%). Emergency ratcheting SL from "
                    f"Rp {pos.stop_loss_price:,.2f} to Rp {emergency_sl:,.2f}"
                )
                pos.stop_loss_price = emergency_sl

        # Dynamic Chandelier ATR Trailing Stop Ratchet for Runner Tier 2
        if pos.tp1_executed and pos.max_price_seen > pos.entry_price:
            effective_atr = getattr(pos, "atr14", 0.0)
            if effective_atr <= 0 or effective_atr > pos.current_price:
                effective_atr = pos.entry_price * 0.035

            # Chandelier trail: 1.5x ATR below peak price seen
            trailing_stop = pos.max_price_seen - (1.5 * effective_atr)
            # Stop loss only moves UP monotonically, never moves down
            if trailing_stop > pos.stop_loss_price:
                pos.stop_loss_price = round(trailing_stop, 2)

        # 1. Check Stop Loss (Evaluated against ratcheted BEP, Chandelier Stop, or Emergency Ratchet)
        if current_price <= pos.stop_loss_price:
            bep_price = pos.entry_price * 1.0052
            if pos.tp1_executed and pos.stop_loss_price > (bep_price + 1.0):
                reason = "CHANDELIER_TRAILING_STOP_HIT"
            elif pos.tp1_executed:
                reason = "BREAKEVEN_STOP_BREACHED"
            else:
                reason = "STOP_LOSS_BREACHED"
            return self.close_paper_position(sym, reason=reason)

        # 2. Check Take Profit Target (Full exit or Tier 2 Runner exit)
        if current_price >= pos.take_profit_price:
            return self.close_paper_position(sym, reason="TAKE_PROFIT_TARGET_HIT")

        # 3. Check Tier 1 Partial Take Profit (Capital Recycling)
        if (
            not pos.tp1_executed
            and pos.partial_tp_price > 0
            and current_price >= pos.partial_tp_price
            and current_price < pos.take_profit_price
        ):
            self.execute_partial_tp(sym, current_price)

        # 4. Check Soft Exit (3h at <= -5.0% for P1/P2 variants)
        pnl_pct = ((current_price - pos.entry_price) / pos.entry_price * 100.0) if pos.entry_price > 0 else 0.0
        if getattr(pos, "strategy", "") in ("P1", "P2", "P1_CONSERVATIVE", "P2_BALANCED", "CONSERVATIVE", "BALANCED"):
            if (now - pos.entry_time) >= (3.0 * 3600.0) and pnl_pct <= -5.0:
                logger.info(
                    f"[VirtualLedger:{self.name}] ⏱️ Soft Exit triggered for {sym}: "
                    f"Held {(now - pos.entry_time)/3600.0:.1f}h >= 3h with PnL {pnl_pct:.2f}% <= -5.0%"
                )
                return self.close_paper_position(sym, reason="SOFT_EXIT_3H_DRAWDOWN")

        # 5. Check Stagnation Exit (Dead Capital Protection: >= 5 days, CI >= 65.0, move <= 0.60%)
        days_held = (now - pos.entry_time) / 86400.0
        ci = current_ci if current_ci is not None else getattr(pos, "current_ci", 50.0)
        unrealized_pct = abs(pnl_pct)
        if days_held >= 5.0 and ci >= 65.0 and unrealized_pct <= 0.60:
            logger.info(
                f"[VirtualLedger:{self.name}] ⏱️ Stagnation Exit triggered for {sym} "
                f"(Held {days_held:.1f}d >= 5d, CI {ci:.1f} >= 65, Move {unrealized_pct:.2f}% <= 0.6%)"
            )
            return self.close_paper_position(sym, reason="STAGNATION_DEAD_CAPITAL_EXIT")

        # 6. Check Max Hold Time Expired
        # Use position-specific max_hold_time_s (e.g. 21d for TF, 10d for MR) or override if explicitly passed
        effective_max_hold = max_hold_time_s if max_hold_time_s is not None else getattr(pos, "max_hold_time_s", 21.0 * 86400.0)
        if (now - pos.entry_time) >= effective_max_hold:
            return self.close_paper_position(sym, reason="MAX_HOLD_TIME_EXPIRED")

        return None

    def close_paper_position(self, symbol: str, reason: str = "MANUAL_EXIT") -> Dict[str, Any]:
        sym = symbol.upper().strip()
        pos = self.open_positions.pop(sym, None)
        if not pos:
            return {"success": False, "reason": "Position not found"}

        # Simulate exit: fee (custom fee_pct e.g. 0.10% maker or 0.21% default)
        gross_value = pos.amount_coins * pos.current_price
        effective_fee_rate = (self.fee_pct / 100.0) if self.fee_pct is not None else (settings.FEE_ROUNDTRIP_PCT / 100.0 / 2.0)
        exit_fee = gross_value * effective_fee_rate
        net_proceeds = gross_value - exit_fee
        remaining_pnl_idr = net_proceeds - pos.cost_idr

        self.cash_idr += net_proceeds

        # Cumulative PnL accounting (TP1 realized profit + final remaining exit)
        total_pnl_idr = remaining_pnl_idr + getattr(pos, "partial_pnl_idr", 0.0)
        initial_cost = getattr(pos, "initial_cost_idr", 0.0)
        if initial_cost <= 0:
            initial_cost = pos.cost_idr + (pos.cost_idr if pos.tp1_executed else 0.0)
        total_pnl_pct = (total_pnl_idr / initial_cost * 100.0) if initial_cost > 0 else 0.0

        trade_record = {
            "position_id": pos.position_id,
            "symbol": sym,
            "entry_price": pos.entry_price,
            "exit_price": pos.current_price,
            "amount_coins": pos.amount_coins,
            "cost_idr": pos.cost_idr,
            "initial_cost_idr": initial_cost,
            "net_proceeds_idr": net_proceeds,
            "realized_pnl_idr": round(total_pnl_idr, 2),
            "realized_pnl_pct": round(total_pnl_pct, 2),
            "remaining_pnl_idr": round(remaining_pnl_idr, 2),
            "partial_pnl_idr": round(getattr(pos, "partial_pnl_idr", 0.0), 2),
            "tp1_executed": getattr(pos, "tp1_executed", False),
            "hold_duration_s": round(time.time() - pos.entry_time, 1),
            "exit_reason": reason,
            "closed_at": time.time(),
            "strategy": getattr(pos, "strategy", "SWING"),
            "ledger": self.name,
        }
        self.trade_history.append(trade_record)
        self._prune_trade_history_if_needed()

        # Durable state persistence (strictly isolated to core PRIMARY_TF and SHADOW_MR)
        if self.name in ("PRIMARY_TF", "SHADOW_MR"):
            durable_state_store.record_position_change(
                change_type="CLOSE",
                position_data=trade_record,
                total_equity_idr=self.get_total_equity(),
                ledger_name=self.name,
                cash_idr=self.cash_idr,
            )


        # Automatic live readiness evaluation & milestone tracking
        try:
            evaluator = self.readiness_evaluator
            if not evaluator:
                from storage.live_readiness import live_readiness_evaluator
                evaluator = live_readiness_evaluator
            current_eq = self.get_total_equity()
            dd_pct = ((self.peak_equity_idr - current_eq) / self.peak_equity_idr * 100.0) if self.peak_equity_idr > 0 else 0.0
            evaluator.evaluate_trades(
                trade_history=self.trade_history,
                current_equity_idr=current_eq,
                initial_bankroll_idr=self.initial_equity_idr,
                peak_equity_idr=self.peak_equity_idr,
                current_drawdown_pct=max(0.0, dd_pct),
            )
        except Exception as eval_exc:
            logger.error(f"[VirtualLedger:{self.name}] Live readiness evaluation error: {eval_exc}")

        realized_pnl_idr = round(total_pnl_idr, 2)
        realized_pnl_pct = round(total_pnl_pct, 2)

        # Notify risk subsystems (PairQuarantine & ChurnGuard via CapitalGovernor)
        if self.on_trade_closed_cb:
            try:
                self.on_trade_closed_cb(sym, realized_pnl_idr, reason, exit_fee)
            except Exception as cb_exc:
                logger.error(f"[VirtualLedger] on_trade_closed_cb error: {cb_exc}")

        log_level = logger.info if realized_pnl_idr >= 0 else logger.warning
        badge = "🟢" if realized_pnl_idr >= 0 else "🔴"
        tp_status = " [TP1 Recycled + Runner]" if getattr(pos, "tp1_executed", False) else ""
        log_level(
            f"[VirtualLedger] {badge} Closed paper position for {sym} ({reason}{tp_status}): "
            f"Total PnL: Rp {realized_pnl_idr:+,.1f} ({realized_pnl_pct:+.2f}%) | Cash: Rp {self.cash_idr:,.0f}"
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

