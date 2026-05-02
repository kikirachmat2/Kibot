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
    def reward_risk_ratio(self) -> float:
        avg_win = self.sum_wins / max(1, self.win_count)
        avg_loss = self.sum_losses / max(1, self.loss_count)
        return avg_win / max(1e-9, avg_loss)

    def kelly_fraction(self, regime: str = "NORMAL") -> float:
        if self.trade_count < 3: return 0.02
        if self.win_count <= 0: return 0.0
        
        wr = self.win_probability
        rr = self.reward_risk_ratio
        full = wr - ((1 - wr) / rr)
        
        # Regime Multiplier
        regime_pnl = self.regime_stats.get(regime, {}).get("sum_pnl", 0.0)
        mult = 0.5 # Half-Kelly
        if regime_pnl < -0.05: mult *= 0.5
        
        return max(0.02, min(0.12, full * mult))

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
        return self._cache.get(pair, PairStats(pair=pair))

    def save_stats(self, stats: PairStats):
        self._cache[stats.pair] = stats
        if self.use_redis:
            self.redis.set(f"kibot:learning:{stats.pair}", json.dumps(stats.to_dict()))
        # Periodic snapshot
        if time.time() % 3600 < 60:
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
            # Fallback search in file
            with open(TRADE_LOG_FILE, "r") as f:
                for line in f:
                    t = json.loads(line)
                    if t.get("trade_id") == trade_id and t.get("status") == "OPEN":
                        trade = t
                        break
        
        if not trade: return None

        # Calculate PnL
        entry_p = trade["entry_price"]
        gross = (exit_price - entry_p) / entry_p
        net_pct = gross - (MAKER_FEE + PPH_SELL + MAKER_FEE) # Approx round trip
        pnl_idr = trade["budget_idr"] * net_pct

        trade.update({
            "exit_price": exit_price, "exit_reason": reason, "status": "CLOSED",
            "pnl_idr": round(pnl_idr, 2), "pnl_pct": round(net_pct, 5),
            "exit_at": datetime.utcnow().isoformat(),
            **kwargs
        })

        # Update Learning Memory
        stats = self.get_stats(trade["pair_id"])
        stats.record_trade(net_pct, regime)
        self.save_stats(stats)

        # Persistence
        with open(TRADE_LOG_FILE, "a") as f:
            f.write(json.dumps(trade) + "\n")
        if self.use_redis:
            self.redis.delete(active_key)
            self.redis.lpush("kibot:history", json.dumps(trade))
            self.redis.ltrim("kibot:history", 0, 999)

        # Sync Supabase
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
            "total": stats.trade_count
        }

    def save_daily_summary(self):
        # Already handled by _save_to_json and periodic snapshots in this version
        pass

def get_engine() -> LearningEngine:
    global _engine
    if "_engine" not in globals() or globals()["_engine"] is None:
        globals()["_engine"] = LearningEngine()
    return globals()["_engine"]

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

    engine = get_engine()
    while True:
        engine.patrol_and_audit()
        time.sleep(300)
