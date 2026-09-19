"""
KiBot V2 — Parallel Multi-Variant Paper Trade Runner (P1 - P4).
Manages four isolated experimental paper trading ledgers in SG1:
- P1 (Conservative): TP +3.0%, Soft Exit 3h @ -5.0%, Hard Exit 7d
- P2 (Balanced):     TP +5.0%, Soft Exit 3h @ -5.0%, Hard Exit 7d
- P3 (Aggressive):   TP +8.0%, Hard Exit 7d
- P4 (Vol Anomaly):  TP +5.0%, Entry vol >3x + BB squeeze, Hard Exit 7d

Each variant:
- Initial capital: Rp 100,000 IDR
- Sizing: Rp 50,000 per order (max 2 positions = Rp 100,000 fully deployed)
- Maker fee: 0.10% (limit order execution)
- Filter universe: Volume 24h > 100M IDR + Spread < 0.5%
- Resets every Monday 00:00 WIB; pauses if weekly drawdown > 50%.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from executor.virtual_ledger import VirtualLedger
from config import settings
from config.fees import IDR_BUY_FEES, IDR_SELL_FEES

logger = logging.getLogger("KiBotV2.PaperRunner")

@dataclass
class VariantSpec:
    name: str
    code: str
    target_tp_pct: float
    target_sl_pct: float
    max_hold_time_s: float
    soft_exit_hours: Optional[float]
    soft_exit_loss_pct: Optional[float]
    order_sizing_idr: float = 50_000.0
    initial_capital_idr: float = 100_000.0
    max_concurrent_positions: int = 2
    buy_fee_pct: float = IDR_BUY_FEES.maker_pct         # 0.1111% — limit buy
    sell_maker_fee_pct: float = IDR_SELL_FEES.maker_pct  # 0.3211% — limit sell (TP/soft)
    sell_taker_fee_pct: float = IDR_SELL_FEES.taker_pct  # 0.4211% — market sell (SL/urgent)

SPECS: Dict[str, VariantSpec] = {
    "P1": VariantSpec(
        name="PAPER_P1_CONSERVATIVE",
        code="P1",
        target_tp_pct=3.0,
        target_sl_pct=15.0,
        max_hold_time_s=7.0 * 86400.0,
        soft_exit_hours=3.0,
        soft_exit_loss_pct=-5.0,
    ),
    "P2": VariantSpec(
        name="PAPER_P2_BALANCED",
        code="P2",
        target_tp_pct=5.0,
        target_sl_pct=15.0,
        max_hold_time_s=7.0 * 86400.0,
        soft_exit_hours=3.0,
        soft_exit_loss_pct=-5.0,
    ),
    "P3": VariantSpec(
        name="PAPER_P3_AGGRESSIVE",
        code="P3",
        target_tp_pct=8.0,
        target_sl_pct=settings.DEFAULT_STOP_LOSS_PCT,
        max_hold_time_s=7.0 * 86400.0,
        soft_exit_hours=None,
        soft_exit_loss_pct=None,
    ),
    "P4": VariantSpec(
        name="PAPER_P4_VOL_ANOMALY",
        code="P4",
        target_tp_pct=5.0,
        target_sl_pct=settings.DEFAULT_STOP_LOSS_PCT,
        max_hold_time_s=7.0 * 86400.0,
        soft_exit_hours=None,
        soft_exit_loss_pct=None,
    ),
}

class PaperTradeRunner:
    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or (settings.STATE_DIR / "paper_p1_p4.json")
        self.ledgers: Dict[str, VirtualLedger] = {}
        self.week_start_equity: Dict[str, float] = {}
        self.is_paused: Dict[str, bool] = {}
        self.pause_reason: Dict[str, str] = {}
        self.last_reset_week: str = ""

        for code, spec in SPECS.items():
            ledger = VirtualLedger(
                initial_cash_idr=spec.initial_capital_idr,
                name=spec.name,
                buy_fee_pct=spec.buy_fee_pct,
                sell_maker_fee_pct=spec.sell_maker_fee_pct,
                sell_taker_fee_pct=spec.sell_taker_fee_pct,
                max_positions=spec.max_concurrent_positions,
            )
            self.ledgers[code] = ledger
            self.week_start_equity[code] = spec.initial_capital_idr
            self.is_paused[code] = False
            self.pause_reason[code] = ""

        self._restore_state()

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_reset_week": self.last_reset_week,
                "timestamp": time.time(),
                "variants": {},
            }
            for code, ledger in self.ledgers.items():
                data["variants"][code] = {
                    "cash_idr": ledger.cash_idr,
                    "week_start_equity": self.week_start_equity.get(code, SPECS[code].initial_capital_idr),
                    "is_paused": self.is_paused.get(code, False),
                    "pause_reason": self.pause_reason.get(code, ""),
                    "open_positions": {sym: pos.to_dict() for sym, pos in ledger.open_positions.items()},
                    "closed_trades": ledger.trade_history[-200:],
                    "total_equity_idr": ledger.get_total_equity(),
                }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[PaperRunner] Error saving state: {e}")

    def _restore_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.last_reset_week = data.get("last_reset_week", "")
            variants_data = data.get("variants", {})
            for code, vdata in variants_data.items():
                if code in self.ledgers:
                    ledger = self.ledgers[code]
                    ledger.restore_state(
                        cash_idr=vdata.get("cash_idr"),
                        open_positions_data=vdata.get("open_positions"),
                        trade_history_data=vdata.get("closed_trades"),
                    )
                    self.week_start_equity[code] = float(vdata.get("week_start_equity", SPECS[code].initial_capital_idr))
                    self.is_paused[code] = bool(vdata.get("is_paused", False))
                    self.pause_reason[code] = str(vdata.get("pause_reason", ""))
            logger.info(f"[PaperRunner] 🔄 Restored state for P1-P4 variants from {self.state_file}")
        except Exception as e:
            logger.warning(f"[PaperRunner] Error restoring state: {e}")

    def check_weekly_reset(self) -> None:
        """
        Evaluates Monday 00:00 WIB (Sunday 17:00 UTC) weekly cycle:
        - Resets base equity: week_start_equity = current total equity.
        - Unpauses paused variants for fresh evaluation if balance is healthy.
        - Flags variants whose capital dropped > 50% within the week.
        """
        now_dt = datetime.now(timezone.utc)
        current_week_str = f"{now_dt.year}-W{now_dt.isocalendar().week}"

        # If week boundary changed (evaluated weekly)
        if self.last_reset_week and self.last_reset_week != current_week_str and now_dt.weekday() == 6 and now_dt.hour >= 17:
            logger.info(f"[PaperRunner] 🔄 Executing Weekly Cycle Reset for {current_week_str}...")
            for code, ledger in self.ledgers.items():
                eq = ledger.get_total_equity()
                start_eq = self.week_start_equity.get(code, eq)
                weekly_return_pct = ((eq - start_eq) / start_eq * 100.0) if start_eq > 0 else 0.0
                
                # Check 50% weekly drawdown pause gate
                if weekly_return_pct <= -50.0:
                    self.is_paused[code] = True
                    self.pause_reason[code] = f"PAUSED: Weekly drawdown {weekly_return_pct:.1f}% exceeded 50% threshold"
                    logger.warning(f"[PaperRunner] 🛑 Variant {code} PAUSED: {self.pause_reason[code]}")
                else:
                    self.is_paused[code] = False
                    self.pause_reason[code] = ""

                self.week_start_equity[code] = eq

            self.last_reset_week = current_week_str
            self._save_state()
        elif not self.last_reset_week:
            self.last_reset_week = current_week_str

    def on_ticker(
        self,
        symbol: str,
        price: float,
        binance_mom_5m: float = 0.0,
        current_ci: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Updates prices across all 4 ledgers and evaluates TP / SL / Soft Exits."""
        self.check_weekly_reset()
        closed_events = []
        for code, ledger in self.ledgers.items():
            if symbol.upper().strip() in ledger.open_positions:
                res = ledger.update_market_price(
                    symbol=symbol,
                    current_price=price,
                    binance_mom_5m=binance_mom_5m,
                    current_ci=current_ci,
                )
                if res:
                    res["variant"] = code
                    closed_events.append(res)
                    self._save_state()

                # Dynamic mid-week safety check: if equity drops > 50% from week start, pause immediately
                eq = ledger.get_total_equity()
                start_eq = self.week_start_equity.get(code, eq)
                if start_eq > 0 and ((eq - start_eq) / start_eq * 100.0) <= -50.0:
                    if not self.is_paused[code]:
                        self.is_paused[code] = True
                        self.pause_reason[code] = "PAUSED: Mid-week equity dropped > 50%"
                        logger.warning(f"[PaperRunner] 🛑 Variant {code} paused: equity Rp {eq:,.0f} < 50% of week start Rp {start_eq:,.0f}")
                        self._save_state()

        return closed_events

    def evaluate_candidate(
        self,
        candidate: Dict[str, Any],
        orderbook: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates incoming candidate ticker/indicators against P1-P4 criteria.
        Universal filter:
        - Volume 24h > 100,000,000 IDR
        - Spread < 0.5% (0.005)
        - Max 2 concurrent positions per variant
        - Sizing: Rp 50,000
        """
        sym = str(candidate.get("symbol", "")).upper().strip()
        price = float(candidate.get("price", 0.0))
        vol_24h = float(candidate.get("volume_idr", 0.0))
        spread_pct = float(candidate.get("spread_pct", 0.01))
        
        if price <= 0:
            return {"evaluated": False, "reason": "invalid_price"}

        # 1. Universe Filter
        if vol_24h <= 100_000_000.0:
            return {"evaluated": False, "reason": f"volume {vol_24h:,.0f} <= 100M IDR"}
        if spread_pct >= 0.005:
            return {"evaluated": False, "reason": f"spread {spread_pct*100:.2f}% >= 0.5%"}

        routed_orders = {}

        # Indicators
        vol_ratio = float(candidate.get("volume_ratio", 1.0))
        vol_proj = float(candidate.get("volume_projected_ratio", 1.0))
        bb_pct_b = float(candidate.get("bollinger_pct_b", 0.5))
        ci = float(candidate.get("choppiness_index", 50.0))
        rsi14 = float(candidate.get("rsi14", 50.0))
        leadlag = float(candidate.get("leadlag_score", 0.0))
        ema20 = float(candidate.get("ema20", 0.0))
        ema50 = float(candidate.get("ema50", 0.0))

        for code, spec in SPECS.items():
            ledger = self.ledgers[code]
            if self.is_paused[code]:
                continue
            if len(ledger.open_positions) >= spec.max_concurrent_positions:
                continue
            if sym in ledger.open_positions:
                continue
            if ledger.cash_idr < spec.order_sizing_idr:
                continue

            # Variant-specific entry condition
            qualifies = False
            strat_tag = f"{code}_{spec.name}"

            if code == "P1":
                # Conservative: Positive leadlag confirmation + healthy RSI + EMA bullish stack
                if leadlag >= 0.2 and 45.0 <= rsi14 <= 68.0 and (ema20 >= ema50 or ema50 == 0.0):
                    qualifies = True
            elif code == "P2":
                # Balanced: Moderate leadlag or momentum confirmation
                if (leadlag >= 0.1 or vol_ratio >= 1.5) and 40.0 <= rsi14 <= 72.0:
                    qualifies = True
            elif code == "P3":
                # Aggressive: High breakout momentum
                if vol_ratio >= 1.8 or leadlag >= 0.3 or price >= float(candidate.get("high_24h", price)) * 0.96:
                    qualifies = True
            elif code == "P4":
                # Vol Anomaly: Volume > 3x average AND Bollinger Bands Squeeze
                is_vol_spike = (vol_ratio >= 3.0 or vol_proj >= 3.0)
                is_bb_squeeze = (0.30 <= bb_pct_b <= 0.70 or ci >= 50.0)
                if is_vol_spike and is_bb_squeeze:
                    qualifies = True

            if qualifies:
                res = ledger.place_paper_buy(
                    symbol=sym,
                    price=price,
                    notional_idr=spec.order_sizing_idr,
                    stop_loss_pct=spec.target_sl_pct,
                    take_profit_pct=spec.target_tp_pct,
                    orderbook=orderbook,
                    max_hold_time_s=spec.max_hold_time_s,
                    strategy=code,
                )
                if res.get("success"):
                    logger.info(f"[PaperRunner] 🚀 Placed {code} order for {sym} (Rp {spec.order_sizing_idr:,.0f}) | TP: +{spec.target_tp_pct}%")
                    routed_orders[code] = res
                    self._save_state()

        return {"evaluated": True, "orders": routed_orders}

    def get_summary(self) -> Dict[str, Any]:
        """Returns consolidated PnL and status for all 4 variants."""
        summary = {}
        for code, spec in SPECS.items():
            ledger = self.ledgers[code]
            eq = ledger.get_total_equity()
            start_eq = self.week_start_equity.get(code, spec.initial_capital_idr)
            week_pnl_idr = eq - start_eq
            week_pnl_pct = (week_pnl_idr / start_eq * 100.0) if start_eq > 0 else 0.0
            cum_pnl_idr = eq - spec.initial_capital_idr
            cum_pnl_pct = (cum_pnl_idr / spec.initial_capital_idr * 100.0) if spec.initial_capital_idr > 0 else 0.0

            summary[code] = {
                "name": spec.name,
                "code": code,
                "equity_idr": round(eq, 2),
                "cash_idr": round(ledger.cash_idr, 2),
                "week_start_equity_idr": round(start_eq, 2),
                "week_pnl_idr": round(week_pnl_idr, 2),
                "week_pnl_pct": round(week_pnl_pct, 2),
                "cum_pnl_idr": round(cum_pnl_idr, 2),
                "cum_pnl_pct": round(cum_pnl_pct, 2),
                "open_positions": len(ledger.open_positions),
                "closed_trades": len(ledger.trade_history),
                "is_paused": self.is_paused.get(code, False),
                "pause_reason": self.pause_reason.get(code, ""),
            }
        return summary
