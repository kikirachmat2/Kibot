"""
Swing Trading Evaluator for KiBot V2.
Implements the 730-Day Indodax Backtest Model:
1. Trend-Following (TF) on BTC/IDR & ETH/IDR (1D candles):
   - EMA(20) > EMA(50)
   - Close > EMA(100)
   - Volume >= 0.95 * SMA20(Volume)
   - RSI(14) >= 48.0
   - TP: +2.5 * ATR(14), SL: -1.5 * ATR(14)
   - Max hold: 21 days (1,814,400s)

2. Mean-Reversion (MR) on ETH/IDR & AVAX/IDR (1D candles):
   - Close <= Lower Bollinger Band (20, 2.0 std)
   - ADX(14) <= 25.0
   - RSI(14) <= 45.0
   - Absolute SMA20 Slope (5 bars) <= 2.0%
   - TP: Middle Band (SMA20), SL: -1.5 * ATR(14)
   - Max hold: 10 days (864,000s)

3. Mutual Exclusivity:
   - On ETH, RSI deadband (45.0 < RSI < 48.0) ensures TF and MR never conflict.
   - If both qualify, explicit precedence guards against dual-triggering.
"""
from __future__ import annotations

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from council.evaluator import CouncilDecision
from council.indicators import (
    calc_ema,
    calc_sma,
    calc_rsi,
    calc_atr,
    calc_bollinger_bands,
    calc_adx,
    calc_slope,
    calc_choppiness_index,
    calc_volume_zscore,
    calc_bollinger_pct_b,
)
from config import settings


def normalize_symbol(symbol: str) -> str:
    """Normalizes symbol to uppercase without slashes or underscores (e.g. 'BTC/IDR' -> 'BTCIDR')."""
    return symbol.upper().replace("/", "").replace("_", "").strip()


class SwingEvaluator:
    """
    Evaluates 1D Swing Trading opportunities for BTC, ETH, and AVAX.
    Matches empirical distributions from the 730-day Indodax historical backtest.
    """

    TF_ELIGIBLE = {"BTCIDR", "ETHIDR", "SOLIDR"}
    MR_ELIGIBLE = {"ETHIDR", "AVAXIDR"}

    # Calibrated empirical backtest performance metrics
    TF_STATS = {
        "p": 0.4545,       # Win rate 45.45%
        "q": 0.5455,
        "avg_win_net": 0.0780,   # +7.80% net of fees
        "avg_loss_net": 0.0580,  # -5.80% net of fees
        "ev_pct": 0.38,          # +0.38% per trade
        "kelly_fraction": 0.0244, # Half-Kelly
        "rr_ratio": 1.34,
        "max_hold_days": 21,
    }

    MR_STATS = {
        "p": 0.5172,       # Win rate 51.72%
        "q": 0.4828,
        "avg_win_net": 0.0730,   # +7.30% net of fees
        "avg_loss_net": 0.0645,  # -6.45% net of fees
        "ev_pct": 0.66,          # +0.66% per trade
        "kelly_fraction": 0.0453, # Half-Kelly
        "rr_ratio": 1.13,
        "max_hold_days": 10,
    }

    def __init__(
        self,
        allocation_pct: Optional[float] = None,
        use_volatility_parity: bool = True,
        target_risk_pct: float = 0.015,
        max_cap_pct: Optional[float] = None,
    ):
        # Default allocation: 25.0% of bankroll per position (enabling 2-3 positions within 70% cap)
        self.allocation_pct = allocation_pct if allocation_pct is not None else getattr(settings, "POSITION_ALLOCATION_PCT", 0.25)
        self.use_volatility_parity = use_volatility_parity
        self.target_risk_pct = target_risk_pct
        self.max_cap_pct = max_cap_pct if max_cap_pct is not None else 0.25

    def calculate_position_size(self, bankroll_idr: float, sl_pct: float) -> float:
        """
        Calculates position size using Volatility Risk Parity (Equal-Dollar Risk):
        Position Size = min((Bankroll * Risk_Target) / (SL_pct / 100), Bankroll * Max_Cap_pct)
        Ensures each trade risks exactly `target_risk_pct` (default 2.0%) of bankroll.
        """
        if not self.use_volatility_parity or sl_pct <= 0:
            return round(bankroll_idr * self.allocation_pct, 2)

        risk_budget_idr = bankroll_idr * self.target_risk_pct
        volatility_sized_idr = risk_budget_idr / (sl_pct / 100.0)
        max_size_idr = bankroll_idr * self.max_cap_pct
        final_size = min(volatility_sized_idr, max_size_idr)
        return max(10_000.0, round(final_size, 2))

    def extract_indicator_values(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extracts precomputed indicators from candidate or computes them
        dynamically from daily candle series if provided.
        """
        # 1. If daily candles or price lists are provided
        closes: List[float] = candidate.get("closes") or []
        highs: List[float] = candidate.get("highs") or []
        lows: List[float] = candidate.get("lows") or []
        volumes: List[float] = candidate.get("volumes") or []

        # If candles is list of dicts [{'close': ..., 'high': ...}]
        candles: List[Dict[str, Any]] = candidate.get("candles_1d") or candidate.get("candles") or []
        if candles and not closes:
            closes = [float(c.get("close") or c.get("c") or 0.0) for c in candles]
            highs = [float(c.get("high") or c.get("h") or 0.0) for c in candles]
            lows = [float(c.get("low") or c.get("l") or 0.0) for c in candles]
            volumes = [float(c.get("volume") or c.get("v") or 0.0) for c in candles]

        vals: Dict[str, Any] = {}

        # Last price
        vals["price"] = float(candidate.get("price") or candidate.get("last_price") or (closes[-1] if closes else 0.0))
        vals["spread_pct"] = float(candidate.get("spread_pct") or 0.0)

        # Precomputed fields take priority if present
        if "ema20" in candidate:
            vals["ema20"] = float(candidate["ema20"])
            vals["ema50"] = float(candidate.get("ema50", 0.0))
            vals["ema100"] = float(candidate.get("ema100", 0.0))
            vals["rsi14"] = float(candidate.get("rsi14", 50.0))
            vals["atr14"] = float(candidate.get("atr14", 0.0))
            vals["volume"] = float(candidate.get("volume", 1.0))
            vals["volume_sma20"] = float(candidate.get("volume_sma20", 1.0))
            vals["lower_bb"] = float(candidate.get("lower_bb", 0.0))
            vals["middle_bb"] = float(candidate.get("middle_bb", 0.0))
            vals["upper_bb"] = float(candidate.get("upper_bb", 0.0))
            vals["adx14"] = float(candidate.get("adx14", 20.0))
            vals["sma20_slope"] = float(candidate.get("sma20_slope", 0.0))
            vals["choppiness_index"] = float(candidate.get("choppiness_index", 50.0))
            vals["volume_zscore"] = float(candidate.get("volume_zscore", 0.0))
            vals["bollinger_pct_b"] = float(candidate.get("bollinger_pct_b", 0.5))
            vals["volume_projected_ratio"] = float(candidate.get("volume_projected_ratio", 1.0))
            vals["prior_bar_volume_ratio"] = float(candidate.get("prior_bar_volume_ratio", 1.0))
            vals["prior_bar_zscore"] = float(candidate.get("prior_bar_zscore", 0.0))
            vals["volume_ratio"] = float(candidate.get("volume_ratio", 1.0))
            vals["binance_momentum_1h"] = float(candidate.get("binance_momentum_1h") or 0.0)
            vals["binance_momentum_5m"] = float(candidate.get("binance_momentum_5m") or 0.0)
            vals["binance_is_dumping"] = bool(candidate.get("binance_is_dumping", False))
            vals["binance_dump_reason"] = str(candidate.get("binance_dump_reason", "STABLE"))
            # D-08 Fix B: Binance data availability status (UNKNOWN = fail-closed)
            vals["binance_data_status"] = str(candidate.get("binance_data_status", "UNKNOWN"))
            return vals

        # Dynamic computation if series length >= 100
        if len(closes) >= 100:
            ema20_s = calc_ema(closes, 20)
            ema50_s = calc_ema(closes, 50)
            ema100_s = calc_ema(closes, 100)
            rsi_s = calc_rsi(closes, 14)
            atr_s = calc_atr(highs, lows, closes, 14) if highs and lows else [0.0] * len(closes)
            vol_sma20 = calc_sma(volumes, 20) if volumes else [1.0] * len(closes)
            mid_bb, up_bb, low_bb = calc_bollinger_bands(closes, 20, 2.0)
            adx_s = calc_adx(highs, lows, closes, 14) if highs and lows else [20.0] * len(closes)
            sma20_series = calc_sma(closes, 20)
            slope = calc_slope(sma20_series, 5)
            ci_s = calc_choppiness_index(highs, lows, closes, 14) if highs and lows else [50.0] * len(closes)
            vol_z_s = calc_volume_zscore(volumes, 20) if volumes else [0.0] * len(closes)
            pct_b_s = calc_bollinger_pct_b(closes, up_bb, low_bb)

            vals["ema20"] = ema20_s[-1]
            vals["ema50"] = ema50_s[-1]
            vals["ema100"] = ema100_s[-1]
            vals["rsi14"] = rsi_s[-1]
            vals["atr14"] = atr_s[-1]
            vals["volume"] = volumes[-1] if volumes else 1.0
            vals["volume_sma20"] = vol_sma20[-1] if vol_sma20 else 1.0
            vals["lower_bb"] = low_bb[-1]
            vals["middle_bb"] = mid_bb[-1]
            vals["upper_bb"] = up_bb[-1]
            vals["adx14"] = adx_s[-1]
            vals["sma20_slope"] = slope
            vals["choppiness_index"] = ci_s[-1]
            vals["volume_zscore"] = vol_z_s[-1]
            vals["bollinger_pct_b"] = pct_b_s[-1]
        else:
            # Defaults if not enough bars
            vals["ema20"] = float(candidate.get("ema20", 0.0))
            vals["ema50"] = float(candidate.get("ema50", 0.0))
            vals["ema100"] = float(candidate.get("ema100", 0.0))
            vals["rsi14"] = float(candidate.get("rsi14", 50.0))
            vals["atr14"] = float(candidate.get("atr14", 0.0))
            vals["volume"] = float(candidate.get("volume", 1.0))
            vals["volume_sma20"] = float(candidate.get("volume_sma20", 1.0))
            vals["lower_bb"] = float(candidate.get("lower_bb", 0.0))
            vals["middle_bb"] = float(candidate.get("middle_bb", 0.0))
            vals["upper_bb"] = float(candidate.get("upper_bb", 0.0))
            vals["adx14"] = float(candidate.get("adx14", 20.0))
            vals["sma20_slope"] = float(candidate.get("sma20_slope", 0.0))
            vals["choppiness_index"] = float(candidate.get("choppiness_index", 50.0))
            vals["volume_zscore"] = float(candidate.get("volume_zscore", 0.0))
            vals["bollinger_pct_b"] = float(candidate.get("bollinger_pct_b", 0.5))
            vals["volume_projected_ratio"] = float(candidate.get("volume_projected_ratio", 1.0))
            vals["prior_bar_volume_ratio"] = float(candidate.get("prior_bar_volume_ratio", 1.0))
            vals["prior_bar_zscore"] = float(candidate.get("prior_bar_zscore", 0.0))
            vals["volume_ratio"] = float(candidate.get("volume_ratio", 1.0))

        vals["binance_momentum_1h"] = float(candidate.get("binance_momentum_1h") or 0.0)
        vals["binance_momentum_5m"] = float(candidate.get("binance_momentum_5m") or 0.0)
        vals["binance_is_dumping"] = bool(candidate.get("binance_is_dumping", False))
        vals["binance_dump_reason"] = str(candidate.get("binance_dump_reason", "STABLE"))
        # D-08 Fix B: Binance data availability status (UNKNOWN = fail-closed)
        vals["binance_data_status"] = str(candidate.get("binance_data_status", "UNKNOWN"))

        return vals

    def evaluate_trend_following(self, norm_sym: str, raw_sym: str, vals: Dict[str, Any], bankroll_idr: float, t0: float) -> Optional[CouncilDecision]:
        """
        Sub-strategy 1: Trend-Following (TF) for BTC, ETH, and SOL
        Rules:
        - EMA20 > EMA50
        - Close > EMA100
        - Dual-Verification Volume Gate (Run-rate projection, prior bar confirmation, or volume z-score)
        - RSI14: 48.0 <= RSI <= 72.0 (healthy pullback, avoid blow-off tops)
        - Choppiness Index: CI < 61.8 (avoid choppy sideways whipsaws)
        - Binance Lead-Lag: No liquidation dump (Return_1h >= -1.5% and not dumping)
        - Sizing: Volatility Risk Parity (Equal-Dollar Risk Budget 2.0%)
        """
        if norm_sym not in self.TF_ELIGIBLE:
            return None

        price = vals["price"]
        ema20 = vals["ema20"]
        ema50 = vals["ema50"]
        ema100 = vals["ema100"]
        rsi14 = vals["rsi14"]
        atr14 = vals["atr14"]
        vol = vals["volume"]
        vol_sma20 = vals["volume_sma20"]
        ci = vals.get("choppiness_index", 50.0)
        vol_z = vals.get("volume_zscore", 0.0)
        binance_is_dumping = vals.get("binance_is_dumping", False)
        binance_mom_1h = vals.get("binance_momentum_1h", 0.0)

        if ema20 <= 0 or ema50 <= 0 or ema100 <= 0:
            return None

        # Check conditions
        cond_ema_cross = ema20 > ema50
        cond_above_ema100 = price > ema100
        
        # Dual-Verification Volume Gate:
        # 1. Run-Rate Projection: projected daily volume >= 0.85 * SMA20, OR
        # 2. Volume Z-Score >= 0.30, OR
        # 3. Prior Bar Confirmation: yesterday's closed volume >= 0.90 * SMA20 or Z >= 0.20, OR
        # 4. Standard volume >= 0.90 * SMA20, OR
        # 5. 24h rolling ticker volume ratio >= 1.0
        vol_projected_ratio = vals.get("volume_projected_ratio", 0.0)
        prior_vol_ratio = vals.get("prior_bar_volume_ratio", 0.0)
        prior_vol_z = vals.get("prior_bar_zscore", 0.0)
        vol_ratio = vals.get("volume_ratio", 1.0)

        cond_volume = (
            (vol_projected_ratio >= 0.85) or
            (vol_z >= 0.30) or
            (prior_vol_ratio >= 0.90) or
            (prior_vol_z >= 0.20) or
            (vol >= 0.90 * vol_sma20 if vol_sma20 > 0 else True) or
            (vol_ratio >= 1.0)
        )
        
        # Pullback healthy, not in overbought blow-off top
        cond_rsi = 48.0 <= rsi14 <= 72.0

        # Anti-Whipsaw Choppiness Index filter (CI < 61.8)
        cond_ci = ci < 61.8

        # Binance macro lead-lag confirmation
        cond_binance = not binance_is_dumping and binance_mom_1h >= -0.015

        if not (cond_ema_cross and cond_above_ema100 and cond_volume and cond_rsi and cond_ci and cond_binance):
            return None

        # Calculate TP / SL based on ATR(14)
        # Default ATR fallback to 3.5% of price if ATR not provided
        effective_atr = atr14 if (atr14 > 0 and atr14 < price) else (price * 0.035)
        tp_pct = round(((2.5 * effective_atr) / price) * 100.0, 2)
        sl_pct = round(((1.5 * effective_atr) / price) * 100.0, 2)

        # Enforce sensible bounds (e.g. TP min 3.0%, SL min 2.0%)
        tp_pct = max(3.0, min(tp_pct, 15.0))
        sl_pct = max(2.0, min(sl_pct, 10.0))

        suggested_size = self.calculate_position_size(bankroll_idr, sl_pct)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        vol_desc = (
            f"VolProj={vol_projected_ratio:.2f}>=0.85" if vol_projected_ratio >= 0.85
            else f"PriorVolRatio={prior_vol_ratio:.2f}>=0.90" if prior_vol_ratio >= 0.90
            else f"VolZ={vol_z:.2f}>=0.30" if vol_z >= 0.30
            else f"VolRatio={vol_ratio:.2f}>=1.0"
        )
        return CouncilDecision(
            verdict="APPROVED",
            symbol=raw_sym,
            action="BUY",
            confidence=0.88,
            score=86.5,
            reason=f"Swing TF Approved: EMA20({ema20:.0f})>EMA50({ema50:.0f}), Close>EMA100, RSI={rsi14:.1f} in [48,72], CI={ci:.1f}<61.8, {vol_desc}",
            suggested_size_idr=suggested_size,
            ev_pct=self.TF_STATS["ev_pct"],
            kelly_fraction=self.TF_STATS["kelly_fraction"],
            rr_ratio=self.TF_STATS["rr_ratio"],
            deliberation_duration_ms=duration_ms,
            enrichment_status="1D_SWING_TF",
            target_tp_pct=tp_pct,
            target_sl_pct=sl_pct,
            strategy="TREND_FOLLOWING",
            max_hold_time_s=self.TF_STATS["max_hold_days"] * 86400,
            atr14=round(effective_atr, 2),
        )

    def evaluate_mean_reversion(self, norm_sym: str, raw_sym: str, vals: Dict[str, Any], bankroll_idr: float, t0: float) -> Optional[CouncilDecision]:
        """
        Sub-strategy 2: Mean-Reversion (MR) for ETH & AVAX
        Rules:
        - Close <= Lower Bollinger Band (20, 2.0) OR Bollinger %B <= 0.05
        - ADX14 <= 25.0
        - RSI14 <= 45.0
        - Absolute SMA20 Slope (5 bars) <= 2.0%
        - Binance Safe: No catastrophic collapse (Binance_1h >= -4.0%)
        - Sizing: Volatility Risk Parity (Equal-Dollar Risk Budget 2.0%)
        """
        if norm_sym not in self.MR_ELIGIBLE:
            return None

        price = vals["price"]
        lower_bb = vals["lower_bb"]
        middle_bb = vals["middle_bb"]
        adx14 = vals["adx14"]
        rsi14 = vals["rsi14"]
        atr14 = vals["atr14"]
        slope = vals["sma20_slope"]
        pct_b = vals.get("bollinger_pct_b", 0.5)
        binance_mom_1h = vals.get("binance_momentum_1h", 0.0)

        if lower_bb <= 0 or middle_bb <= 0:
            return None

        # Check conditions: Lower BB touch OR Bollinger %B <= 0.05
        cond_bb = (price <= lower_bb) or (pct_b <= 0.05)
        cond_adx = adx14 <= 25.0
        cond_rsi = rsi14 <= 45.0
        cond_slope = abs(slope) <= 0.02
        cond_binance_safe = binance_mom_1h >= -0.040

        if not (cond_bb and cond_adx and cond_rsi and cond_slope and cond_binance_safe):
            return None

        # Calculate TP / SL
        # TP: Middle Bollinger Band (SMA20)
        effective_atr = atr14 if (atr14 > 0 and atr14 < price) else (price * 0.035)
        tp_pct = round(((middle_bb - price) / price) * 100.0, 2)
        sl_pct = round(((1.5 * effective_atr) / price) * 100.0, 2)

        # Enforce bounds
        tp_pct = max(2.5, min(tp_pct, 12.0))
        sl_pct = max(2.0, min(sl_pct, 10.0))

        suggested_size = self.calculate_position_size(bankroll_idr, sl_pct)
        duration_ms = (time.perf_counter() - t0) * 1000.0

        return CouncilDecision(
            verdict="APPROVED",
            symbol=raw_sym,
            action="BUY",
            confidence=0.85,
            score=84.0,
            reason=f"Swing MR Approved: Price({price:.0f})<=LowerBB({lower_bb:.0f}) or %B={pct_b:.2f}<=0.05, ADX={adx14:.1f}<=25, RSI={rsi14:.1f}<=45, Slope={slope*100:.2f}%<=2%",
            suggested_size_idr=suggested_size,
            ev_pct=self.MR_STATS["ev_pct"],
            kelly_fraction=self.MR_STATS["kelly_fraction"],
            rr_ratio=self.MR_STATS["rr_ratio"],
            deliberation_duration_ms=duration_ms,
            enrichment_status="1D_SWING_MR",
            target_tp_pct=tp_pct,
            target_sl_pct=sl_pct,
            strategy="MEAN_REVERSION",
            max_hold_time_s=self.MR_STATS["max_hold_days"] * 86400,
            atr14=round(effective_atr, 2),
        )

    def evaluate(self, candidate: Dict[str, Any], bankroll_idr: float = 10_000_000.0) -> CouncilDecision:
        """
        Unified evaluation entry point for Swing Strategy.
        Executes TF and MR evaluations with mutual exclusivity enforcement.
        """
        t0 = time.perf_counter()
        raw_sym = str(candidate.get("symbol") or candidate.get("pair") or "UNKNOWN").upper().strip()
        norm_sym = normalize_symbol(raw_sym)

        # Reject if symbol is not in swing universe
        if norm_sym not in (self.TF_ELIGIBLE | self.MR_ELIGIBLE):
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED",
                symbol=raw_sym,
                action="NONE",
                confidence=0.0,
                score=0.0,
                reason=f"Symbol {raw_sym} is not in swing universe (BTC, ETH, AVAX, SOL)",
                suggested_size_idr=0.0,
                ev_pct=0.0,
                kelly_fraction=0.0,
                rr_ratio=0.0,
                deliberation_duration_ms=duration_ms,
                enrichment_status="INELIGIBLE_SYMBOL",
                strategy="NONE",
                max_hold_time_s=0,
            )

        vals = self.extract_indicator_values(candidate)

        # D-08 Fix B: Block entry when Binance data is stale or missing (fail-closed)
        binance_status = vals.get("binance_data_status", "UNKNOWN")
        if binance_status == "UNKNOWN":
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED",
                symbol=raw_sym,
                action="NONE",
                confidence=0.0,
                score=0.0,
                reason="Binance cross-market data unavailable or stale (fail-closed: no entry without lead-lag confirmation)",
                suggested_size_idr=0.0,
                ev_pct=0.0,
                kelly_fraction=0.0,
                rr_ratio=0.0,
                deliberation_duration_ms=duration_ms,
                enrichment_status="BINANCE_DATA_UNKNOWN",
                strategy="NONE",
                max_hold_time_s=0,
            )

        # Microstructure Guard
        if vals["price"] <= 0:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED",
                symbol=raw_sym,
                action="NONE",
                confidence=0.0,
                score=0.0,
                reason="Invalid zero or negative price",
                suggested_size_idr=0.0,
                ev_pct=0.0,
                kelly_fraction=0.0,
                rr_ratio=0.0,
                deliberation_duration_ms=duration_ms,
                enrichment_status="INVALID_PRICE",
                strategy="NONE",
                max_hold_time_s=0,
            )

        # Spread filter: max 0.80% spread for swing (relaxed from 0.50% scalping limit due to wider targets)
        if vals["spread_pct"] > 0.0080:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            return CouncilDecision(
                verdict="REJECTED",
                symbol=raw_sym,
                action="NONE",
                confidence=0.1,
                score=10.0,
                reason=f"Spread {vals['spread_pct']*100:.2f}% exceeds swing limit 0.80%",
                suggested_size_idr=0.0,
                ev_pct=0.0,
                kelly_fraction=0.0,
                rr_ratio=0.0,
                deliberation_duration_ms=duration_ms,
                enrichment_status="HIGH_SPREAD",
                strategy="NONE",
                max_hold_time_s=0,
            )

        # 1. Evaluate Trend-Following (Eligible: BTC, ETH)
        tf_decision = self.evaluate_trend_following(norm_sym, raw_sym, vals, bankroll_idr, t0)

        # 2. Evaluate Mean-Reversion (Eligible: ETH, AVAX)
        mr_decision = self.evaluate_mean_reversion(norm_sym, raw_sym, vals, bankroll_idr, t0)

        # 3. Mutual Exclusivity & Selection
        # On ETH, RSI >= 48 (TF) and RSI <= 45 (MR) are mutually exclusive.
        # But if somehow both pass, TF takes precedence for ETH.
        if tf_decision and mr_decision:
            return tf_decision
        if tf_decision:
            return tf_decision
        if mr_decision:
            return mr_decision

        duration_ms = (time.perf_counter() - t0) * 1000.0
        return CouncilDecision(
            verdict="REJECTED",
            symbol=raw_sym,
            action="NONE",
            confidence=0.3,
            score=35.0,
            reason="Did not meet Swing 1D TF or MR gating criteria",
            suggested_size_idr=0.0,
            ev_pct=0.0,
            kelly_fraction=0.0,
            rr_ratio=0.0,
            deliberation_duration_ms=duration_ms,
            enrichment_status="CRITERIA_NOT_MET",
            strategy="NONE",
            max_hold_time_s=0,
        )
