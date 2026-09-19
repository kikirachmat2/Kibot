"""
KiBot V2 — P5 Rotation Strategy with Market Regime & BTC Dominance Routing.
Implements the 4-quadrant regime routing matrix:
1. BULL + BTC.D naik (> +0.5%)  -> Entry BTC/ETH only (Major focus)
2. RANGE + BTC.D turun (< -0.5%) -> Scan altcoins (Volume anomaly + Correlation <= 0.70)
3. BEAR + BTC.D naik (> +0.5%)  -> Risk-Off Hold Cash (No entry)
4. BEAR + BTC.D turun (< -0.5%) -> Scan independent altcoins (Correlation < 0.50)

Specifications:
- Initial capital: Rp 100,000 IDR
- Sizing: Rp 50,000 per order (max 2 positions = Rp 100,000 fully deployed)
- TP target: +5.0%
- Hard exit: 7 days (7 * 86400s)
- Maker fee: 0.10% (limit order execution)
- Filter universe: Volume 24h > 100M IDR + Spread < 0.5%
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

import pandas as pd
from config import settings
from council.regime_detector import MarketRegime, detect_regime
from executor.virtual_ledger import VirtualLedger

logger = logging.getLogger("KiBotV2.RotationRunner")


class RotationPaperRunner:
    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or (settings.STATE_DIR / "paper_p5_rotation.json")
        self.initial_capital_idr = 100_000.0
        self.order_sizing_idr = 50_000.0
        self.max_positions = 2
        self.target_tp_pct = 5.0
        self.target_sl_pct = 15.0
        self.max_hold_time_s = 7.0 * 86400.0
        self.maker_fee_pct = 0.10

        self.ledger = VirtualLedger(
            initial_cash_idr=self.initial_capital_idr,
            name="PAPER_P5_ROTATION",
            fee_pct=self.maker_fee_pct,
            max_positions=self.max_positions,
        )
        self.week_start_equity = self.initial_capital_idr
        self.is_paused = False
        self.pause_reason = ""
        self.last_reset_week = ""
        self.btc_correlations: Dict[str, float] = {}

        # Cached latest regime
        self.latest_regime_info: Dict[str, Any] = {
            "regime": MarketRegime.RANGE,
            "strength": 0.0,
            "btc_trend_7h": 0.0,
            "btc_dominance_trend_7h": 0.0,
            "altcoin_rotation_score": 0.0,
        }

        self._restore_state()

    def set_btc_correlation(self, symbol: str, correlation: float) -> None:
        self.btc_correlations[symbol.upper().strip()] = float(correlation)

    def get_btc_correlation(self, symbol: str) -> float:
        sym = symbol.upper().strip()
        if sym in ("BTCIDR", "BTC"):
            return 1.0
        return self.btc_correlations.get(sym, 0.50)

    def update_market_regime(
        self,
        btc_ohlcv_1h: pd.DataFrame,
        btc_dominance_series: Optional[pd.Series] = None,
        alt_volume_ratio: float = 1.0,
    ) -> Dict[str, Any]:
        info = detect_regime(
            btc_ohlcv_1h=btc_ohlcv_1h,
            btc_dominance_series=btc_dominance_series,
            alt_volume_ratio=alt_volume_ratio,
        )
        self.latest_regime_info = info
        return info

    def check_weekly_reset(self) -> None:
        now_dt = datetime.now(timezone.utc)
        current_week_str = f"{now_dt.year}-W{now_dt.isocalendar().week}"

        if self.last_reset_week and self.last_reset_week != current_week_str and now_dt.weekday() == 6 and now_dt.hour >= 17:
            eq = self.ledger.get_total_equity()
            weekly_return_pct = ((eq - self.week_start_equity) / self.week_start_equity * 100.0) if self.week_start_equity > 0 else 0.0
            
            if weekly_return_pct <= -50.0:
                self.is_paused = True
                self.pause_reason = f"PAUSED: Weekly drawdown {weekly_return_pct:.1f}% exceeded 50% threshold"
                logger.warning(f"[RotationRunner] 🛑 P5 PAUSED: {self.pause_reason}")
            else:
                self.is_paused = False
                self.pause_reason = ""

            self.week_start_equity = eq
            self.last_reset_week = current_week_str
            self._save_state()
        elif not self.last_reset_week:
            self.last_reset_week = current_week_str

    def _save_state(self) -> None:
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "last_reset_week": self.last_reset_week,
                "timestamp": time.time(),
                "cash_idr": self.ledger.cash_idr,
                "week_start_equity": self.week_start_equity,
                "is_paused": self.is_paused,
                "pause_reason": self.pause_reason,
                "open_positions": {sym: pos.to_dict() for sym, pos in self.ledger.open_positions.items()},
                "closed_trades": self.ledger.trade_history[-200:],
                "total_equity_idr": self.ledger.get_total_equity(),
                "latest_regime": self.latest_regime_info,
            }
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"[RotationRunner] Error saving state: {e}")

    def _restore_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.last_reset_week = data.get("last_reset_week", "")
            self.week_start_equity = float(data.get("week_start_equity", self.initial_capital_idr))
            self.is_paused = bool(data.get("is_paused", False))
            self.pause_reason = str(data.get("pause_reason", ""))
            self.latest_regime_info = data.get("latest_regime", self.latest_regime_info)
            self.ledger.restore_state(
                cash_idr=data.get("cash_idr"),
                open_positions_data=data.get("open_positions"),
                trade_history_data=data.get("closed_trades"),
            )
            logger.info(f"[RotationRunner] 🔄 Restored P5 state from {self.state_file}")
        except Exception as e:
            logger.warning(f"[RotationRunner] Error restoring state: {e}")

    def on_ticker(
        self,
        symbol: str,
        price: float,
        binance_mom_5m: float = 0.0,
        current_ci: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        self.check_weekly_reset()
        sym = symbol.upper().strip()
        if sym in self.ledger.open_positions:
            res = self.ledger.update_market_price(
                symbol=sym,
                current_price=price,
                binance_mom_5m=binance_mom_5m,
                current_ci=current_ci,
            )
            if res:
                res["variant"] = "P5"
                self._save_state()
                return res
        return None

    def evaluate_candidate(
        self,
        candidate: Dict[str, Any],
        orderbook: Optional[Dict[str, Any]] = None,
        regime_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates candidate symbol for P5 Rotation Strategy.
        Regime routing:
        - BULL + BTC.D up (> +0.5%) -> BTC/ETH only
        - RANGE + BTC.D down (< -0.5%) -> altcoins (vol_ratio >= 2.0 & corr <= 0.70)
        - BEAR + BTC.D up (> +0.5%) -> HOLD CASH
        - BEAR + BTC.D down (< -0.5%) -> altcoins independent (corr < 0.50)
        """
        self.check_weekly_reset()
        if self.is_paused:
            return {"evaluated": False, "reason": self.pause_reason or "paused"}

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

        if len(self.ledger.open_positions) >= self.max_positions:
            return {"evaluated": False, "reason": "max_positions_reached"}
        if sym in self.ledger.open_positions:
            return {"evaluated": False, "reason": "already_open"}
        if self.ledger.cash_idr < self.order_sizing_idr:
            return {"evaluated": False, "reason": "insufficient_cash"}

        regime_info = regime_override or self.latest_regime_info
        regime = regime_info.get("regime", MarketRegime.RANGE)
        btcd_trend = float(regime_info.get("btc_dominance_trend_7h", 0.0))
        vol_ratio = float(candidate.get("volume_ratio", 1.0))
        corr = self.get_btc_correlation(sym)

        # 2. Quadrant Routing Logic
        if regime == MarketRegime.BULL and btcd_trend > 0.5:
            # Major focus: BTC / ETH only
            if sym not in ("BTCIDR", "ETHIDR"):
                return {"evaluated": False, "reason": "bull_btc_dominant"}
        elif regime == MarketRegime.BEAR and btcd_trend > 0.5:
            # Bear risk-off: hold cash
            return {"evaluated": False, "reason": "bear_risk_off"}
        elif regime == MarketRegime.RANGE and btcd_trend < -0.5:
            # Altcoin rotation: must have volume anomaly + acceptable correlation
            if corr > 0.70:
                return {"evaluated": False, "reason": "high_btc_correlation"}
            if vol_ratio < 2.0:
                return {"evaluated": False, "reason": "no_volume_anomaly"}
        elif regime == MarketRegime.BEAR and btcd_trend < -0.5:
            # Independent altcoin escape only (low correlation < 0.50)
            if corr >= 0.50:
                return {"evaluated": False, "reason": "bear_correlated_rejection"}
            if vol_ratio < 2.0:
                return {"evaluated": False, "reason": "no_volume_anomaly"}

        # 3. Order Placement (TP +5%, Hard Exit 7d, Limit Order 0.10% Maker Fee)
        res = self.ledger.place_paper_buy(
            symbol=sym,
            price=price,
            notional_idr=self.order_sizing_idr,
            stop_loss_pct=self.target_sl_pct,
            take_profit_pct=self.target_tp_pct,
            orderbook=orderbook,
            max_hold_time_s=self.max_hold_time_s,
            strategy="P5",
        )
        if res.get("success"):
            logger.info(
                f"[RotationRunner] 🚀 Placed P5 Rotation BUY for {sym} @ Rp {price:,.1f} "
                f"(Regime: {regime}, BTC.D 7H: {btcd_trend:+.2f}%)"
            )
            self._save_state()
            return {"evaluated": True, "order": res, "regime": regime}

        return {"evaluated": False, "reason": res.get("reason", "order_failed")}

    def get_summary(self) -> Dict[str, Any]:
        eq = self.ledger.get_total_equity()
        cum_pnl = eq - self.initial_capital_idr
        cum_pnl_pct = (cum_pnl / self.initial_capital_idr * 100.0) if self.initial_capital_idr > 0 else 0.0
        week_pnl = eq - self.week_start_equity
        week_pnl_pct = (week_pnl / self.week_start_equity * 100.0) if self.week_start_equity > 0 else 0.0

        return {
            "name": "PAPER_P5_ROTATION",
            "code": "P5",
            "equity_idr": round(eq, 2),
            "cash_idr": round(self.ledger.cash_idr, 2),
            "week_start_equity_idr": round(self.week_start_equity, 2),
            "week_pnl_idr": round(week_pnl, 2),
            "week_pnl_pct": round(week_pnl_pct, 2),
            "cum_pnl_idr": round(cum_pnl, 2),
            "cum_pnl_pct": round(cum_pnl_pct, 2),
            "open_positions": len(self.ledger.open_positions),
            "closed_trades": len(self.ledger.trade_history),
            "is_paused": self.is_paused,
            "pause_reason": self.pause_reason,
            "regime": self.latest_regime_info.get("regime", MarketRegime.RANGE),
            "btc_dominance_trend_7h": self.latest_regime_info.get("btc_dominance_trend_7h", 0.0),
        }
