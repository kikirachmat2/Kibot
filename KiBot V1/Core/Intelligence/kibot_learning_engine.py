"""KiBot Learning Engine — Bayesian PairStats & Historian Profiler.

ARCHITECTURE NOTE:
- `strategy_stats.py` is the official Single Source of Truth (SSOT) for live trading execution gates,
  EV calculations, and strategy graduation.
- `kibot_learning_engine.py` serves as an auxiliary contextual/display layer providing
  Bayesian prior updating (alpha/beta), historian profiling, and pair behavior metrics.
"""

from __future__ import annotations
import sys
import os
import json
import time
import re
import logging
import asyncio
import hashlib
import hmac
import signal
import uuid
import threading
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Setup paths (Sovereign Unified Support)
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import redis
except ImportError:
    redis = None

import httpx
from dataclasses import asdict, dataclass, field

# --- CONFIGURATION ---
STATE_ROOT = Path(os.getenv("KIBOT_RUNTIME_ROOT", ".")) / "state"
STATE_ROOT.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_ROOT / "learning_state.json"
TRADE_LOG_FILE = STATE_ROOT / "trade_log.jsonl"

REDIS_HOST = os.getenv("KIBOT_REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("KIBOT_REDIS_PORT", "6379"))
ROUND_TRIP_MAKER = float(os.getenv("KIBOT_ROUND_TRIP_MAKER_COST", "0.003"))
ROUND_TRIP_TAKER = float(os.getenv("KIBOT_ROUND_TRIP_TAKER_COST", "0.005"))
WIB_UTC_OFFSET_HOURS = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))
WIB_TZ = timezone(timedelta(hours=WIB_UTC_OFFSET_HOURS))

# --- INTELLIGENCE HARDENING ---
PNL_UPPER_BOUND = 0.50 # +50% max per trade for learning (prevents outlier manipulation)
PNL_LOWER_BOUND = -0.20 # -20% max per trade for learning
STALE_SIGNAL_TTL_SEC = 15 # Signals older than 15s are rejected for entry

from Core.Support.ki_config import KiConfig

# INDODAX OFFICIAL FEE STRUCTURE (Maker 0.21% buy / 0.20% sell, Taker 0.31% buy / 0.30% sell)
MAKER_FEE = KiConfig.INDODAX_MAKER_BUY_FEE_PCT   # 0.0021 (0.21%)
TAKER_FEE = KiConfig.INDODAX_TAKER_BUY_FEE_PCT   # 0.0031 (0.31%)
PPH_SELL  = 0.0000  # Included in official 0.30% sell fee

@dataclass
class PairStats:
    pair: str
    alpha: float = 1.0
    beta: float = 1.0
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    sum_wins: float = 0.0
    sum_losses: float = 0.0
    ema_pnl: float = 0.0
    last_trade_ts: float = 0.0
    cooldown_until_ts: float = 0.0
    max_drawdown: float = 0.0
    peak_pnl: float = 0.0
    current_drawdown: float = 0.0
    cumulative_pnl: float = 0.0
    pnl_variance: float = 0.0
    consecutive_losses: int = 0
    regime_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    lessons: List[str] = field(default_factory=list)
    # ─────────────────────────────────────────────
    # Long-horizon historian fields (§12, §12.1)
    # ─────────────────────────────────────────────
    historian_verdict:          str   = "UNKNOWN"  # GOOD|MIXED|DEAD|TRAP_PRONE|UNKNOWN
    flatness_score:             float = 0.5  # 0.0=very active, 1.0=flat/dead
    pump_frequency_score:       float = 0.5  # how often this pair genuinely pumps
    pump_continuation_score:    float = 0.5  # how often pumps continue after entry
    retracement_risk_score:     float = 0.5  # how often it retraces sharply
    liquidity_decay_score:      float = 0.5  # how often liquidity collapses post-entry
    trap_count:                 int   = 0    # number of confirmed trap events
    historian_updated_at:       float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "PairStats":
        fields = PairStats.__dataclass_fields__
        return PairStats(**{key: value for key, value in data.items() if key in fields})

    @property
    def win_probability(self) -> float:
        return self.alpha / max(1e-9, self.alpha + self.beta)

    @property
    def avg_win(self) -> float:
        return self.sum_wins / max(1, self.win_count)

    @property
    def avg_loss(self) -> float:
        return self.sum_losses / max(1, self.loss_count)

    @property
    def reward_risk_ratio(self) -> float:
        avg_win = self.avg_win
        avg_loss = self.avg_loss
        return avg_win / max(1e-9, avg_loss)

    @property
    def profit_factor(self) -> float:
        if self.sum_losses == 0: return 2.0 if self.sum_wins > 0 else 1.0
        return self.sum_wins / self.sum_losses

    def kelly_fraction(self, regime: str = "NORMAL") -> float:
        if self.trade_count < 3: return 0.02
        if self.win_count <= 0: return 0.0
        
        wr = self.win_probability
        rr = self.reward_risk_ratio
        
        # Kelly Formula: f = (p*r - q) / r
        # We use a conservative half-kelly or less
        edge = wr * rr - (1 - wr)
        full_kelly = edge / max(1e-9, rr)
        
        # Regime Multiplier
        regime_data = self.regime_stats.get(regime, {})
        regime_pnl = regime_data.get("sum_pnl", 0.0)
        regime_count = regime_data.get("count", 0)
        
        mult = 0.5 # Default Half-Kelly
        
        # If we have data for this regime and it sucks, scale down
        if regime_count >= 2:
            avg_regime_pnl = regime_pnl / regime_count
            if avg_regime_pnl < -0.01: mult *= 0.5
            if avg_regime_pnl < -0.03: mult *= 0.2
            
        # Global Profit Factor adjustment
        pf = self.profit_factor
        if pf > 2.0: mult *= 1.2
        elif pf < 1.0: mult *= 0.5

        return max(0.01, min(0.12, full_kelly * mult))

    def record_trade(self, pnl: float, regime: str):
        self.trade_count += 1
        if pnl > 0:
            self.win_count += 1
            self.sum_wins += pnl
            self.alpha += 1
        else:
            self.loss_count += 1
            self.sum_losses += abs(pnl)
            self.beta += 1
        
        # --- PNL CLIPPING (Anti-Poisoning) ---
        clipped_pnl = max(PNL_LOWER_BOUND, min(PNL_UPPER_BOUND, pnl))
        if clipped_pnl != pnl:
            print(f"[INTEL][CLIPPING] PnL {pnl:.2%} clipped to {clipped_pnl:.2%} for pair {self.pair}")
        
        pnl = clipped_pnl

        # Variance calculation (Running variance)
        prev_ema = self.ema_pnl
        self.ema_pnl = (0.8 * self.ema_pnl) + (0.2 * pnl)
        self.pnl_variance = (0.8 * self.pnl_variance) + 0.2 * (pnl - prev_ema)**2
        
        # Proper Max Drawdown Tracking
        self.cumulative_pnl += pnl
        if self.cumulative_pnl > self.peak_pnl:
            self.peak_pnl = self.cumulative_pnl
            self.current_drawdown = 0.0
        else:
            self.current_drawdown = self.peak_pnl - self.cumulative_pnl
            self.max_drawdown = max(self.max_drawdown, self.current_drawdown)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self.last_trade_ts = time.time()
        
        if regime not in self.regime_stats:
            self.regime_stats[regime] = {"count": 0, "sum_pnl": 0.0}
        self.regime_stats[regime]["count"] += 1
        self.regime_stats[regime]["sum_pnl"] += pnl

    # ─────────────────────────────────────────────
    # §12 — Historian Verdict (Long-Horizon Profile)
    # ─────────────────────────────────────────────

    def compute_historian_verdict(self, ohlc_quality: Optional[dict] = None) -> str:
        """
        Derive long-horizon historian verdict from KiBot's own trade history.
        §12.1: Historian profile must be updated from real trade data, not vibes.

        Verdict: GOOD | MIXED | DEAD | TRAP_PRONE | UNKNOWN
        """
        if self.trade_count < 3:
            self.historian_verdict = "UNKNOWN"
            self.historian_updated_at = time.time()
            return self.historian_verdict

        win_rate = self.win_probability
        pf       = self.profit_factor
        trap_rate = self.trap_count / max(1, self.trade_count)

        # Flatness from OHLC quality (if provided from scanner's _fetch_ohlc_quality)
        if ohlc_quality:
            distinct = ohlc_quality.get("distinct_close_levels", 999)
            zero_vol = ohlc_quality.get("zero_volume_ratio", 0.0)
            self.flatness_score = round(
                min(1.0, max(0.0, (zero_vol * 0.6) + (1.0 - min(1.0, distinct / 20.0)) * 0.4)),
                3
            )

        # Compute sub-scores from trade history
        self.pump_continuation_score = round(win_rate, 3)
        self.retracement_risk_score  = round(min(1.0, self.max_drawdown * 5), 3)
        self.liquidity_decay_score   = round(trap_rate, 3)

        # Derive verdict
        if self.flatness_score > 0.7:
            verdict = "DEAD"
        elif trap_rate >= 0.30 or self.consecutive_losses >= 4:
            verdict = "TRAP_PRONE"
        elif win_rate >= 0.60 and pf >= 1.5 and trap_rate < 0.15:
            verdict = "GOOD"
        elif win_rate >= 0.45 and pf >= 1.0:
            verdict = "MIXED"
        else:
            verdict = "MIXED"

        self.historian_verdict   = verdict
        self.historian_updated_at = time.time()

        return verdict

    def get_historian_profile(self, ohlc_quality: Optional[dict] = None) -> dict:
        """Return historian profile dict for scanner output (§17.2 historian_profile field)."""
        # Refresh verdict
        self.compute_historian_verdict(ohlc_quality)
        return {
            "verdict":               self.historian_verdict,
            "trade_count":           self.trade_count,
            "win_probability":       round(self.win_probability, 3),
            "profit_factor":         round(self.profit_factor, 3),
            "pump_continuation":     self.pump_continuation_score,
            "retracement_risk":      self.retracement_risk_score,
            "liquidity_decay":       self.liquidity_decay_score,
            "flatness_score":        self.flatness_score,
            "trap_count":            self.trap_count,
            "consecutive_losses":    self.consecutive_losses,
            "cumulative_pnl":        round(self.cumulative_pnl, 6),
            "historian_updated_at":  self.historian_updated_at,
        }

def _get_signing_key() -> bytes:
    # Use the same root of trust as kibot_security
    secret = os.getenv("KIBOT_SECRET")
    if not secret:
        raise RuntimeError("KIBOT_SECRET missing: learning engine refuses to sign or verify state")
    try:
        from Core.Support.ki_vault import get_vault
        vault = get_vault()
        if vault and hasattr(vault, "_key") and vault._key:
            return vault._key
    except Exception:
        pass
    return secret.encode()


def _now_wib() -> datetime:
    return datetime.now(WIB_TZ)

class LearningEngine:
    def __init__(self):
        self.use_redis = False
        if redis:
            try:
                self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
                self.redis.ping()
                self.use_redis = True
            except Exception:
                self.use_redis = False
        
        self._cache: Dict[str, PairStats] = {}
        self._today_trades: List[dict] = [] # In-memory track for manager compatibility
        self._load_from_json()

    def _atomic_write(self, path: Path, content: str):
        tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
        try:
            tmp.write_text(content)
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def _load_from_json(self):
        if STATE_PATH.exists():
            try:
                content = STATE_PATH.read_text()
                if "|" not in content:
                    raise ValueError("State file missing HMAC signature")
                
                payload, signature = content.rsplit("|", 1)
                key = _get_signing_key()
                expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
                
                if not hmac.compare_digest(signature, expected):
                    print("[SECURITY] LEARNING STATE CORRUPTED: HMAC mismatch. Deleting for safety.")
                    STATE_PATH.unlink()
                    return

                raw = json.loads(payload)
                for pair, data in raw.items():
                    self._cache[pair] = PairStats.from_dict(data)
            except Exception as e:
                print(f"[SECURITY] Learning state load failed: {e}")

    def get_stats(self, pair: str) -> PairStats:
        if self.use_redis:
            data = self.redis.get(f"kibot:learning:{pair}")
            if data: return PairStats.from_dict(json.loads(str(data)))
        if pair not in self._cache:
            # New Pair: Use Bayesian Seeds
            is_large_cap = pair.lower() in ["btc_idr", "eth_idr", "sol_idr", "xrp_idr", "bnb_idr"]
            if is_large_cap:
                # Optimistic 50% default
                self._cache[pair] = PairStats(pair=pair, alpha=5.0, beta=5.0)
            else:
                # Conservative 20% default for unknown Small Caps
                self._cache[pair] = PairStats(pair=pair, alpha=2.0, beta=8.0)
        return self._cache[pair]

    def get(self, pair: str) -> PairStats:
        """Alias for get_stats for compatibility."""
        return self.get_stats(pair)

    def save_stats(self, stats: PairStats, force: bool = False):
        self._cache[stats.pair] = stats
        if self.use_redis:
            self.redis.set(f"kibot:learning:{stats.pair}", json.dumps(stats.to_dict()))
        
        # Periodic or forced signed snapshot
        if force or time.time() % 3600 < 60 or not STATE_PATH.exists():
            payload = json.dumps({k: v.to_dict() for k, v in self._cache.items()}, indent=2)
            key = _get_signing_key()
            signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
            self._atomic_write(STATE_PATH, f"{payload}|{signature}")

    def record_entry(self, pair: str, entry_price: float, budget: float, **kwargs) -> str:
        # --- REPLAY PROTECTION (TTL Check) ---
        sent_at = kwargs.get("sentAtEpochMs") or (kwargs.get("timestamp", 0) * 1000)
        if sent_at > 0:
            age_sec = (time.time() * 1000 - sent_at) / 1000
            if age_sec > STALE_SIGNAL_TTL_SEC:
                print(f"[INTEL][REJECT] Stale signal for {pair}: age={age_sec:.1f}s > {STALE_SIGNAL_TTL_SEC}s")
                return "REJECTED_STALE"

        trade_id = str(uuid.uuid4())[:8]
        trade = {
            "trade_id": trade_id, "pair_id": pair, "entry_price": entry_price,
            "budget_idr": budget, "status": "OPEN", "entry_at": _now_wib().isoformat(),
            "timestamp": time.time(),
            **kwargs
        }
        self._today_trades.append(trade) # Track in memory
        
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(trade) + "\n")
        
        if self.use_redis:
            self.redis.set(f"kibot:active:{trade_id}", json.dumps(trade))
        return trade_id

    def record_trade(self, pair: str, pnl_pct: float, regime: str = "NORMAL", **kwargs):
        """Directly record a trade result to pair stats with metadata."""
        stats = self.get_stats(pair)
        stats.record_trade(pnl_pct, regime)
        self.save_stats(stats, force=True)
        
        # Log it to the file too for audit trail
        audit_log = {
            "type": "TRADE_RECORD",
            "pair": pair,
            "pnl_pct": pnl_pct,
            "regime": regime,
            "timestamp": time.time(),
            **kwargs
        }
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(audit_log) + "\n")

    def should_entry(self, pair: str) -> Tuple[bool, str]:
        """
        Bayesian Gatekeeper: Decide if we should allow entry based on history.
        """
        stats = self.get_stats(pair)
        health = self.get_pair_health(pair)
        
        if health < 0.2:
            return False, f"HEALTH_CRITICAL: {health:.2f}"
        
        if stats.consecutive_losses >= 3:
            return False, f"LOSS_STREAK: {stats.consecutive_losses} losses"
            
        if time.time() < stats.cooldown_until_ts:
            return False, "COOLDOWN_ACTIVE"
            
        return True, "OK"

    def get_open_trade_for_pair(self, pair: str) -> Optional[dict]:
        """Manager compatibility: Find an open trade for a specific pair."""
        for t in self._today_trades:
            if t.get("pair_id") == pair and t.get("status") == "OPEN":
                return t
        return None

    # [REMOVED DUPLICATE get_today_stats]

    def score_penalty(self, pair: str) -> float:
        """Manager compatibility: Calculate a penalty score (0.0 to 1.0) based on health."""
        health = self.get_pair_health(pair)
        # Low health = High penalty
        return max(0.0, 1.0 - health)

    def record_exit(self, trade_id: str, exit_price: float, reason: str, regime: str = "NORMAL", **kwargs):
        """
        Records trade exit with PARANOID price validation.
        """
        # --- PARANOID PRICE VERIFICATION ---
        mid_price = kwargs.get("market_mid_price", 0.0)
        if mid_price > 0:
            deviation = abs(exit_price - mid_price) / mid_price
            if deviation > 0.05: # 5% deviation on exit is suspicious for an audit
                print(f"[SECURITY] EXIT PRICE ANOMALY: Trade {trade_id} exit {exit_price} deviates {deviation:.2%} from mid {mid_price}")
                # We still record but flag it
                kwargs["anomaly_flag"] = True
                kwargs["anomaly_reason"] = "Price Deviation > 5%"

        active_key = f"kibot:active:{trade_id}"
        trade = None
        
        if self.use_redis:
            raw = self.redis.get(active_key)
            if raw: trade = json.loads(str(raw))
        
        if not trade and TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r") as f:
                for line in f:
                    try:
                        t = json.loads(line)
                        if t.get("trade_id") == trade_id and t.get("status") == "OPEN":
                            trade = t
                            break
                    except Exception: pass
        
        if not trade: return None

        entry_p = trade["entry_price"]
        gross = (exit_price - entry_p) / entry_p
        net_pct = gross - (MAKER_FEE + PPH_SELL + MAKER_FEE)
        pnl_idr = trade["budget_idr"] * net_pct

        trade.update({
            "exit_price": exit_price, "exit_reason": reason, "status": "CLOSED",
            "pnl_idr": round(pnl_idr, 2), "pnl_pct": round(net_pct, 5),
            "exit_at": _now_wib().isoformat(),
            "win": net_pct > 0,
            **kwargs
        })

        # Update in-memory track
        for i, t in enumerate(self._today_trades):
            if t["trade_id"] == trade_id:
                self._today_trades[i] = trade
                break

        stats = self.get_stats(trade["pair_id"])
        stats.record_trade(net_pct, regime)
        self.save_stats(stats)

        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(trade) + "\n")
        if self.use_redis:
            self.redis.delete(active_key)
            self.redis.lpush("kibot:history", json.dumps(trade))
            self.redis.ltrim("kibot:history", 0, 999)

        return trade


    def get_today_stats(self) -> dict:
        today = _now_wib().strftime("%Y-%m-%d")
        closed = []
        if TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r") as f:
                for line in f:
                    try:
                        t = json.loads(line)
                        if t.get("status") == "CLOSED" and t.get("exit_at", "").startswith(today):
                            closed.append(t)
                    except Exception: pass
        
        wins = [t for t in closed if t.get("win")]
        losses = [t for t in closed if not t.get("win")]
        total = len(closed)
        if total == 0: return {"total":0, "win_rate":0.5, "pnl_idr":0}
        
        return {
            "total": total, "wins": len(wins), "losses": len(losses),
            "win_rate": len(wins)/total, "pnl_idr": sum(t.get("pnl_idr", 0) for t in closed)
        }

    def get_today_activity(self) -> dict:
        """Return today's trade activity counts including open entries."""
        today = _now_wib().strftime("%Y-%m-%d")
        entries = 0
        open_trades = 0
        closed_trades = 0
        if TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r") as f:
                for line in f:
                    try:
                        trade = json.loads(line)
                    except Exception:
                        continue
                    stamp = str(trade.get("entry_at") or trade.get("exit_at") or "")
                    if not stamp.startswith(today):
                        continue
                    if trade.get("status") == "OPEN":
                        entries += 1
                        open_trades += 1
                    elif trade.get("status") == "CLOSED":
                        closed_trades += 1
        return {
            "entries": entries,
            "open": open_trades,
            "closed": closed_trades,
            "today": today,
        }

    def get_pair_stats(self, pair: str) -> dict:
        stats = self.get_stats(pair)
        return {
            "win_rate": stats.win_probability,
            "profit_factor": stats.profit_factor,
            "total": stats.trade_count,
            "health": self.get_pair_health(pair)
        }

    def get_pair_health(self, pair: str) -> float:
        """
        Returns a score from 0.0 (Dead/High Risk) to 1.0 (Very Healthy).
        Based on Win Rate, Profit Factor, and EMA PnL.
        """
        stats = self.get_stats(pair)
        if stats.trade_count < 3:
            return 0.7  # Default for new pairs
        
        # 1. Win Rate Score (0-1)
        wr_score = stats.win_probability
        
        # 2. Profit Factor Score (0-1, normalized)
        pf = stats.profit_factor
        pf_score = min(1.0, pf / 2.0)
        
        # 3. Recency Score (EMA PnL + Variance)
        # We penalize high variance (unpredictability)
        vol_penalty = min(0.3, stats.pnl_variance * 5)
        ema_score = 0.5 + (stats.ema_pnl * 10) - vol_penalty
        ema_score = max(0.0, min(1.0, ema_score))
        
        # 4. Drawdown Penalty
        dd_penalty = min(0.4, stats.max_drawdown * 2)
        
        # 5. Consecutive Loss Panic
        panic_penalty = 0.0
        if stats.consecutive_losses >= 3:
            panic_penalty = 0.3 # Sharp drop in health for losing streaks
            
        final_health = (wr_score * 0.35) + (pf_score * 0.35) + (ema_score * 0.3)
        final_health = max(0.0, final_health - dd_penalty - panic_penalty)
        
        # Cool-down penalty
        if time.time() < stats.cooldown_until_ts:
            final_health *= 0.5
            
        return round(final_health, 2)

    def save_daily_summary(self):
        # Save current state to JSON
        try:
            payload = json.dumps({k: v.to_dict() for k, v in self._cache.items()}, indent=2)
            key = _get_signing_key()
            signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
            self._atomic_write(STATE_PATH, f"{payload}|{signature}")
        except Exception: pass

    def patrol_and_audit(self):
        """Autonomous patrol for learning opportunities and trade audits."""
        try:
            # Sync any unsaved state
            self.save_daily_summary()
            # In the future, this will scan trade_log.jsonl for inconsistencies
            print(f"[LEARNING] Patrol completed at {_now_wib()}")
        except Exception as e:
            print(f"[LEARNING] Patrol Error: {e}")
    def handle_sigterm(self, signum, frame):
        """Graceful shutdown for Learning Engine."""
        print("👋 Learning Engine shutting down gracefully...")
        # Final save
        self.save_daily_summary()
        sys.exit(0)

class VWAPRegimeDetector:
    def detect(self, candles: list) -> str:
        if len(candles) < 5:
            return "SIDEWAYS"
        try:
            tp_vol = sum(((c["high"] + c["low"] + c["close"]) / 3.0) * c["volume"] for c in candles)
            total_vol = sum(c["volume"] for c in candles)
            if total_vol <= 0:
                return "SIDEWAYS"
            vwap = tp_vol / total_vol
            last_price = candles[-1]["close"]
            avg_vol = total_vol / len(candles)
            vol_ratio = candles[-1]["volume"] / avg_vol if avg_vol > 0 else 1.0
            closes = [c["close"] for c in candles[-5:]]
            ema5 = closes[0]
            for price in closes[1:]:
                ema5 = 0.7 * ema5 + 0.3 * price
            above_vwap = last_price > vwap
            high_volume = vol_ratio > 1.5
            trend_ratio = last_price / max(1e-9, closes[0])
            if trend_ratio > 1.01 and above_vwap and high_volume:
                return "BULLISH"
            if trend_ratio < 0.95 and high_volume:
                return "BREAKDOWN_PANIC"
            if trend_ratio < 0.99 and not above_vwap and high_volume:
                return "BEARISH"
            if trend_ratio < 1.0 and high_volume and ema5 <= vwap:
                return "BEARISH"
            return "SIDEWAYS"
        except Exception:
            return "SIDEWAYS"

_engine: Optional[LearningEngine] = None
_regime_detector: Optional[VWAPRegimeDetector] = None

def get_engine() -> LearningEngine:
    global _engine
    if _engine is None:
        _engine = LearningEngine()
    return _engine

def get_regime_detector() -> VWAPRegimeDetector:
    global _regime_detector
    if _regime_detector is None:
        _regime_detector = VWAPRegimeDetector()
    return _regime_detector

if __name__ == "__main__":
    print("🚀 KiBot Learning Engine Starting...")
    
    # [VAULT] Load Sovereign Secrets
    try:
        from Core.Support.ki_vault import load_sovereign_env
        load_sovereign_env()
    except Exception as ve:
        print(f"[BOOT][VAULT][WARN] Could not load vaulted env: {ve}")

    engine = get_engine()
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, engine.handle_sigterm)
    signal.signal(signal.SIGINT, engine.handle_sigterm)
    
    while True:
        engine.patrol_and_audit()
        time.sleep(300)
