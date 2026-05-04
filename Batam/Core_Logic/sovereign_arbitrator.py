#!/usr/bin/env python3
from __future__ import annotations

import json
import requests
import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys
from kibot_sentinel import get_sentinel

# Intelligence Imports
_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_root / "Intelligence"))
try:
    from kibot_learning_engine import get_engine as get_learning_engine
except ImportError:
    get_learning_engine = lambda: None

logger = logging.getLogger("SovereignArbitrator")

@dataclass
class AllocationRequest:
    source: str  # "INDODAX" or "POLYMARKET"
    asset: str
    signal_score: float  # 0.0 to 1.0
    ev_estimate: float   # Expected Value estimate
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class GlobalBalance:
    indodax_idr: float = 0.0
    polymarket_usdc: float = 0.0
    last_updated: float = 0.0

class SovereignArbitrator:
    """
    Sovereign Arbitrator (v8.2)
    The ultimate decision maker for capital allocation across platforms.
    Integrated with Bayesian learning for loss-streak protection.
    """
    def __init__(self, state_root: Path):
        self.state_root = state_root
        self.state_file = state_root / "sovereign_state.json"
        self._lock = threading.RLock()
        
        # Internal State
        self.balance = GlobalBalance()
        self.usd_idr_rate = 16200.0  # Default base rate
        self.risk_multiplier = 0.25   # Fractional Kelly (1/4)
        self.min_allocation_idr = 50000
        self.max_allocation_idr = 2000000
        
        # PnL Control
        self.daily_pnl_idr = 0.0
        self.last_pnl_reset = ""  # YYYY-MM-DD
        self.max_daily_loss_pct = 0.05 # 5% Hard Stop
        self.last_rate_update = 0.0
        
        # Stochastic Settings
        self.stochastic_noise = 0.10  # +/- 10% randomness
        
        self.load_state()
        self.refresh_usd_rate() # Get fresh rate on startup

    def load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
                self.usd_idr_rate = data.get("usd_idr_rate", 16200.0)
                self.daily_pnl_idr = data.get("daily_pnl_idr", 0.0)
                self.last_pnl_reset = data.get("last_pnl_reset", "")
                self.max_daily_loss_pct = data.get("max_daily_loss_pct", 0.05)
                # We don't load balances from disk as they should be fresh from live engines
        except Exception as e:
            logger.error(f"Failed to load arbitrator state: {e}")

    def save_state(self):
        try:
            data = {
                "usd_idr_rate": self.usd_idr_rate,
                "daily_pnl_idr": self.daily_pnl_idr,
                "last_pnl_reset": self.last_pnl_reset,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "ts": time.time()
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save arbitrator state: {e}")

    def update_balances(self, indodax_idr: float, polymarket_usdc: float):
        with self._lock:
            self._check_pnl_reset()
            self.balance.indodax_idr = indodax_idr
            self.balance.polymarket_usdc = polymarket_usdc
            self.balance.last_updated = time.time()

    def _check_pnl_reset(self):
        today = time.strftime("%Y-%m-%d")
        if self.last_pnl_reset != today:
            logger.info(f"ARBITRATOR: Resetting daily PnL (Prev: Rp{self.daily_pnl_idr:,.0f})")
            self.daily_pnl_idr = 0.0
            self.last_pnl_reset = today
            self.refresh_usd_rate() # Get fresh rate for the new day
            self.save_state()

    def refresh_usd_rate(self):
        """
        Consensus Sovereign Rate (v8.2)
        Fetches from multiple sources (Forex API + Indodax) to establish a baseline.
        """
        rates = []
        
        # Source 1: ExchangeRate-API (Free Tier)
        try:
            url = "https://api.exchangerate-api.com/v4/latest/USD"
            resp = requests.get(url, timeout=5)
            if resp.ok:
                data = resp.json()
                rate = data.get("rates", {}).get("IDR")
                if rate and rate > 10000:
                    rates.append(rate)
                    logger.info(f"Forex API USD/IDR: {rate:,.0f}")
        except Exception as e:
            logger.warning(f"Forex API failed: {e}")

        # Source 2: Indodax USDT/IDR
        try:
            url = "https://indodax.com/api/ticker/usdt_idr"
            resp = requests.get(url, timeout=5)
            if resp.ok:
                rate = float(resp.json().get("ticker", {}).get("last", 0))
                if rate > 10000:
                    rates.append(rate)
                    logger.info(f"Indodax USDT/IDR: {rate:,.0f}")
        except Exception: pass
        
        if rates:
            new_rate = sum(rates) / len(rates)
            
            # --- ORACLE CIRCUIT BREAKER ---
            if self.usd_idr_rate > 0:
                jump_pct = abs(new_rate - self.usd_idr_rate) / self.usd_idr_rate
                if jump_pct > 0.02: # 2% Jump in one update is suspicious
                    logger.warning(f"ORACLE VETO: Suspicious rate jump ({jump_pct:.2%}). "
                                   f"Old: {self.usd_idr_rate}, New: {new_rate}. Ignoring.")
                    return

            self.usd_idr_rate = new_rate
            self.last_rate_update = time.time()
            logger.info(f"Consensus Sovereign Rate: Rp {self.usd_idr_rate:,.0f}")
            self.save_state()
        else:
            logger.error(f"All rate sources failed. Using fallback: {self.usd_idr_rate}")

    def _apply_humility_factor(self, conviction: float) -> float:
        """
        Reduces extreme conviction to prevent 'God-Mode' overbetting.
        Caps effective conviction at 0.95.
        """
        if conviction > 0.98:
            logger.warning("HUMILITY: God-mode conviction detected. Scaling down to 0.95.")
            return 0.95
        return conviction

    def report_pnl(self, delta_idr: float):
        """Report trade result to arbitrator for global daily limit tracking"""
        with self._lock:
            self._check_pnl_reset()
            self.daily_pnl_idr += delta_idr
            
            # Update Sentinel with loss velocity if applicable
            sentinel = get_sentinel()
            # If delta is negative, calculate its percentage of total equity for sentinel
            equity = self.get_total_equity_idr()
            loss_pct = (abs(delta_idr) / equity * 100) if (delta_idr < 0 and equity > 0) else 0.0
            sentinel.register_trade(success=True, loss_pct=loss_pct)
            
            self.save_state()
            
            # Record outcome to Learning Engine
            learn = get_learning_engine()
            if learn:
                # Usually the manager calls record_exit, but we log here for visibility
                pass

            logger.info(f"ARBITRATOR: PnL Reported: Rp{delta_idr:,.0f} | Today: Rp{self.daily_pnl_idr:,.0f}")

    def get_total_equity_idr(self) -> float:
        return self.balance.indodax_idr + (self.balance.polymarket_usdc * self.usd_idr_rate)

    def calculate_stochastic_kelly(self, ev: float, conviction: float, **kwargs) -> float:
        """
        Calculates optimal size using Fractional Kelly + Stochastic Noise.
        Formula: Size = Equity * Fractional_Kelly * (EV/Conviction)
        """
        if ev <= 0:
            return 0.0
            
        total_equity = self.get_total_equity_idr()
        if total_equity <= 0:
            return 0.0

        # Apply Humility Factor to conviction
        conviction = self._apply_humility_factor(conviction)
        
        # Bayesian Adjustment: Consult Learning Engine
        learn = get_learning_engine()
        if learn:
            asset = kwargs.get("asset", "UNKNOWN")
            stats = learn.get_stats(asset)
            health = learn.get_pair_health(asset)
            
            # Use the engine's calculated Kelly Fraction as the baseline risk multiplier
            kelly_f = stats.kelly_fraction(kwargs.get("regime", "NORMAL"))
            base_size = total_equity * min(self.risk_multiplier, kelly_f)
            
            # Health-based scaling
            health_mult = 1.0
            if health < 0.4: health_mult = 0.2
            elif health < 0.6: health_mult = 0.7
            elif health > 0.85: health_mult = 1.2
            base_size *= health_mult
        else:
            # Fallback to simple conviction-based sizing
            base_size = total_equity * self.risk_multiplier * conviction * (ev / (ev + 0.05))
            
        # Apply stochastic noise
        noise = random.gauss(1.0, self.stochastic_noise / 2.0)
        final_size = base_size * noise
        
        # Constraints
        final_size = max(0.0, min(final_size, self.max_allocation_idr))
        if final_size < self.min_allocation_idr:
            return 0.0
            
        return round(final_size, 2)

    def request_allocation(self, req: AllocationRequest) -> Tuple[bool, float, str]:
        """
        The master entry gate (v8.2).
        Returns: (Approved, Size_IDR, Reason)
        """
        with self._lock:
            # 1. Basic Health Check
            if time.time() - self.balance.last_updated > 600: # 10 mins stale
                return False, 0.0, "ARBITRATOR: Balance state is stale (>10m)"

            # 1.5 Sentinel Anomaly Detection
            sentinel = get_sentinel()
            price = req.metadata.get("price", 0.0)
            mid_price = req.metadata.get("market_mid_price", 0.0)
            
            is_safe, s_reason = sentinel.check_order(
                pair=req.asset,
                side=req.metadata.get("side", "BUY"),
                price=price,
                market_mid_price=mid_price,
                estimated_loss_pct=0.0
            )
            
            if not is_safe:
                return False, 0.0, f"SENTINEL VETO: {s_reason}"

            # 2. Daily Loss Limit (Hard Stop)
            self._check_pnl_reset()
            
            # Auto-update rate if stale (> 1 hour)
            if time.time() - self.last_rate_update > 3600:
                self.refresh_usd_rate()

            total_equity = self.get_total_equity_idr()
            loss_threshold = total_equity * self.max_daily_loss_pct
            
            if self.daily_pnl_idr < -loss_threshold:
                return False, 0.0, f"ARBITRATOR: DAILY LOSS LIMIT REACHED (Rp{self.daily_pnl_idr:,.0f} < -Rp{loss_threshold:,.0f})"

            # 2.5 BAYESIAN ENTRY GATE (v8.2 Upgrade)
            learn = get_learning_engine()
            if learn:
                should_entry, learn_reason = learn.should_entry(req.asset)
                if not should_entry:
                    return False, 0.0, f"BAYESIAN VETO: {learn_reason}"

            # 3. Opportunity Cost Check
            available_funds = self.balance.indodax_idr if req.source == "INDODAX" else self.balance.polymarket_usdc * self.usd_idr_rate
            
            budget_utilization = (self.get_total_equity_idr() - available_funds) / max(self.get_total_equity_idr(), 1)
            threshold = 0.75 + (budget_utilization * 0.15) # Dynamic threshold
            
            if req.signal_score < threshold:
                return False, 0.0, f"ARBITRATOR: Conviction {req.signal_score:.2f} < Threshold {threshold:.2f} (Budget: {budget_utilization:.2%})"

            # 3.5 What-If Engine Cross-Validation
            whatif_file = self.state_root / "whatif_results.json"
            if whatif_file.exists():
                try:
                    with open(whatif_file, "r") as f:
                        wf = json.load(f)
                        res = wf.get("results", {}).get(req.asset)
                        if res:
                            verdict = res.get("verdict", "OK")
                            ev_sim = res.get("expectedValue", 0.0)
                            if verdict == "SKIP" or ev_sim < -0.005:
                                return False, 0.0, f"ARBITRATOR: What-If VETO (Verdict: {verdict}, EV: {ev_sim})"
                            if ev_sim < req.ev_estimate:
                                req.ev_estimate = ev_sim
                except Exception as e:
                    logger.warning(f"Failed to read What-If results: {e}")

            # 4. Calculate Size
            size_idr = self.calculate_stochastic_kelly(req.ev_estimate, req.signal_score, asset=req.asset)
            
            if size_idr <= 0:
                return False, 0.0, f"ARBITRATOR: Kelly size below minimum ({self.min_allocation_idr})"

            # 4. Final Verdict
            final_size = size_idr if req.source == "INDODAX" else size_idr / self.usd_idr_rate
            
            return True, final_size, "ARBITRATOR: Optimal allocation approved"

# Global Instance
_arbitrator: Optional[SovereignArbitrator] = None

def get_arbitrator(state_root: Optional[Path] = None) -> SovereignArbitrator:
    global _arbitrator
    if _arbitrator is None:
        if state_root is None:
            # Fallback to default state dir
            state_root = Path(__file__).resolve().parent.parent / "state"
        _arbitrator = SovereignArbitrator(state_root)
    return _arbitrator
