import json
import os
import time
import redis
import re
import uuid
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple, List
import urllib.request

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

# INDODAX FEE (Maker 0.04%, PPh 0.21%, Taker 0.55%)
MAKER_FEE = 0.0004
TAKER_FEE = 0.0055
PPH_SELL  = 0.0021

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
    regime_stats: Dict[str, Dict[str, float]] = field(default_factory=dict)
    lessons: List[str] = field(default_factory=list)

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

        return max(0.01, min(0.15, full_kelly * mult))

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
        
        self.ema_pnl = (0.8 * self.ema_pnl) + (0.2 * pnl)
        self.last_trade_ts = time.time()
        
        if regime not in self.regime_stats:
            self.regime_stats[regime] = {"count": 0, "sum_pnl": 0.0}
        self.regime_stats[regime]["count"] += 1
        self.regime_stats[regime]["sum_pnl"] += pnl

class LearningEngine:
    def __init__(self):
        try:
            self.redis = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
            self.redis.ping()
            self.use_redis = True
        except Exception:
            self.use_redis = False
        
        self._cache: Dict[str, PairStats] = {}
        self._load_from_json()

    def _load_from_json(self):
        if STATE_PATH.exists():
            try:
                raw = json.loads(STATE_PATH.read_text())
                for pair, data in raw.items():
                    self._cache[pair] = PairStats.from_dict(data)
            except Exception: pass

    def get_stats(self, pair: str) -> PairStats:
        if self.use_redis:
            data = self.redis.get(f"kibot:learning:{pair}")
            if data: return PairStats.from_dict(json.loads(data))
        if pair not in self._cache:
            self._cache[pair] = PairStats(pair=pair)
        return self._cache[pair]

    def get(self, pair: str) -> PairStats:
        """Alias for get_stats for compatibility."""
        return self.get_stats(pair)

    def save_stats(self, stats: PairStats):
        self._cache[stats.pair] = stats
        if self.use_redis:
            self.redis.set(f"kibot:learning:{stats.pair}", json.dumps(stats.to_dict()))
        # Periodic snapshot
        if time.time() % 3600 < 60 or not STATE_PATH.exists():
            STATE_PATH.write_text(json.dumps({k: v.to_dict() for k, v in self._cache.items()}, indent=2))

    def record_entry(self, pair: str, entry_price: float, budget: float, **kwargs) -> str:
        trade_id = str(uuid.uuid4())[:8]
        trade = {
            "trade_id": trade_id, "pair_id": pair, "entry_price": entry_price,
            "budget_idr": budget, "status": "OPEN", "entry_at": datetime.utcnow().isoformat(),
            **kwargs
        }
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(trade) + "\n")
        
        if self.use_redis:
            self.redis.set(f"kibot:active:{trade_id}", json.dumps(trade))
        return trade_id

    def record_exit(self, trade_id: str, exit_price: float, reason: str, regime: str = "NORMAL", **kwargs):
        active_key = f"kibot:active:{trade_id}"
        trade = None
        
        if self.use_redis:
            raw = self.redis.get(active_key)
            if raw: trade = json.loads(raw)
        
        if not trade and TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r") as f:
                for line in f:
                    try:
                        t = json.loads(line)
                        if t.get("trade_id") == trade_id and t.get("status") == "OPEN":
                            trade = t
                            break
                    except: pass
        
        if not trade: return None

        entry_p = trade["entry_price"]
        gross = (exit_price - entry_p) / entry_p
        net_pct = gross - (MAKER_FEE + PPH_SELL + MAKER_FEE)
        pnl_idr = trade["budget_idr"] * net_pct

        trade.update({
            "exit_price": exit_price, "exit_reason": reason, "status": "CLOSED",
            "pnl_idr": round(pnl_idr, 2), "pnl_pct": round(net_pct, 5),
            "exit_at": datetime.utcnow().isoformat(),
            "win": net_pct > 0,
            **kwargs
        })

        stats = self.get_stats(trade["pair_id"])
        stats.record_trade(net_pct, regime)
        self.save_stats(stats)

        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(trade) + "\n")
        if self.use_redis:
            self.redis.delete(active_key)
            self.redis.lpush("kibot:history", json.dumps(trade))
            self.redis.ltrim("kibot:history", 0, 999)

        self._sync_to_supabase(trade)
        return trade

    def _sync_to_supabase(self, trade: dict):
        def do_sync():
            try:
                url = os.environ.get("SUPABASE_URL")
                key = os.environ.get("SUPABASE_ANON_KEY")
                if not url or not key: return
                req = urllib.request.Request(
                    f"{url}/rest/v1/trade_history",
                    data=json.dumps(trade).encode(),
                    headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                )
                urllib.request.urlopen(req, timeout=5)
            except Exception: pass
        threading.Thread(target=do_sync, daemon=True).start()

    def get_today_stats(self) -> dict:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        closed = []
        if TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r") as f:
                for line in f:
                    try:
                        t = json.loads(line)
                        if t.get("status") == "CLOSED" and t.get("exit_at", "").startswith(today):
                            closed.append(t)
                    except: pass
        
        wins = [t for t in closed if t.get("win")]
        losses = [t for t in closed if not t.get("win")]
        total = len(closed)
        if total == 0: return {"total":0, "win_rate":0.5, "pnl_idr":0}
        
        return {
            "total": total, "wins": len(wins), "losses": len(losses),
            "win_rate": len(wins)/total, "pnl_idr": sum(t.get("pnl_idr", 0) for t in closed)
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
        
        # 3. Recency Score (EMA PnL)
        ema_score = 0.5 + (stats.ema_pnl * 10)
        ema_score = max(0.0, min(1.0, ema_score))
        
        final_health = (wr_score * 0.4) + (pf_score * 0.4) + (ema_score * 0.2)
        
        # Cool-down penalty
        if time.time() < stats.cooldown_until_ts:
            final_health *= 0.5
            
        return round(final_health, 2)

    def save_daily_summary(self):
        # Save current state to JSON
        try:
            STATE_PATH.write_text(json.dumps({k: v.to_dict() for k, v in self._cache.items()}, indent=2))
        except: pass

    def patrol_and_audit(self):
        """Autonomous patrol for learning opportunities and trade audits."""
        try:
            # Sync any unsaved state
            self.save_daily_summary()
            # In the future, this will scan trade_log.jsonl for inconsistencies
            print(f"[LEARNING] Patrol completed at {datetime.now()}")
        except Exception as e:
            print(f"[LEARNING] Patrol Error: {e}")

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
    engine = get_engine()
    while True:
        engine.patrol_and_audit()
        time.sleep(300)
