import os, time, json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

DIRECTIVES_FILE = Path(os.environ.get("KIBOT_GOVERNOR_FILE", "state/governor_directives.json"))

# ═══ CAPITAL ALLOCATION (50/50) ════════════════════════════

class CapitalAllocator:
    """
    Enforce split 50/50:
    - LEAD_LAG bucket (50%): sinyal dari 5 global scanner
    - LOCAL_PUMP bucket (50%): sinyal deteksi pump lokal Indodax
    Max 25% dari bucket per single trade.
    """
    def __init__(self, total_capital_idr: float):
        self.total = total_capital_idr
        self.ratio = {
            "LEAD_LAG":   float(os.environ.get("KIBOT_LEAD_LAG_BUCKET_PCT", "0.50")),
            "LOCAL_PUMP": float(os.environ.get("KIBOT_LOCAL_PUMP_BUCKET_PCT", "0.50")),
        }
        self.deployed = {"LEAD_LAG": 0.0, "LOCAL_PUMP": 0.0}
        self.MAX_PER_TRADE = 0.25  # max 25% dari bucket per trade
        self._last_directive_check = 0.0

    def _refresh_directives(self):
        now = time.time()
        if now - self._last_directive_check < 60: return
        self._last_directive_check = now
        
        if DIRECTIVES_FILE.exists():
            try:
                data = json.loads(DIRECTIVES_FILE.read_text())
                cap_cfg = data.get("capital", {})
                if "ratio" in cap_cfg:
                    self.ratio.update(cap_cfg["ratio"])
                if "max_per_trade" in cap_cfg:
                    self.MAX_PER_TRADE = float(cap_cfg["max_per_trade"])
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"[CAPITAL][WARN] directive refresh error: {e}", flush=True)

    def update_total(self, new_total: float):
        self.total = new_total

    def allocate(self, bucket: str, requested_idr: float, msc_multiplier: float = 1.0) -> Optional[float]:
        """
        Return alokasi dalam IDR, atau None jika bucket habis.
        msc_multiplier: dari MSC engine (0.6x - 1.2x)
        """
        self._refresh_directives()
        max_bucket   = self.total * self.ratio.get(bucket, 0.50)
        available    = max_bucket - self.deployed.get(bucket, 0.0)
        max_per      = max_bucket * self.MAX_PER_TRADE * msc_multiplier
        if available < 10_000:  # min 10rb IDR
            return None
        allocated = min(requested_idr, available, max_per)
        self.deployed[bucket] = self.deployed.get(bucket, 0.0) + allocated
        return allocated

    def release(self, bucket: str, amount_idr: float):
        self.deployed[bucket] = max(0.0, self.deployed.get(bucket, 0.0) - amount_idr)

    def status(self) -> dict:
        return {
            bkt: {
                "deployed": self.deployed.get(bkt, 0.0),
                "max":      self.total * ratio,
                "free":     max(0.0, self.total * ratio - self.deployed.get(bkt, 0.0)),
                "pct_used": (self.deployed.get(bkt, 0.0) / (self.total * ratio) * 100
                             if self.total * ratio > 0 else 0)
            }
            for bkt, ratio in self.ratio.items()
        }


# ═══ PARTIAL TAKE PROFIT ═══════════════════════════════════

class PartialTPManager:
    """
    Exit ladder berbeda per bucket.
    LEAD_LAG: konservatif (sinyal predictive)
    LOCAL_PUMP: agresif (pump lokal bisa reversal cepat)
    """
    LADDERS = {
        "LEAD_LAG": [
            (0.5,  0.30, "ll_tp1"),  # +0.5% profit → jual 30%
            (1.2,  0.50, "ll_tp2"),  # +1.2% → jual 50% sisa (~65% total keluar)
            # Sisa 35%: trailing stop
        ],
        "LOCAL_PUMP": [
            (1.0,  0.25, "lp_tp1"),  # +1.0% → jual 25%
            (2.5,  0.40, "lp_tp2"),  # +2.5% → jual 40% sisa
            (4.5,  0.35, "lp_tp3"),  # +4.5% → jual 35% sisa (habis)
        ],
    }

    def check(self, position: dict, current_profit_pct: float) -> Optional[dict]:
        """
        Return sell action dict jika ada TP level yang terpenuhi, else None.
        position harus punya: pairId, remainingQty, bucketType, executedTpLevels (set)
        """
        bucket = position.get("bucketType", "LOCAL_PUMP")
        ladder = self.LADDERS.get(bucket, self.LADDERS["LOCAL_PUMP"])
        done   = position.get("executedTpLevels", set())
        if not isinstance(done, set): done = set(done)
        qty    = position.get("remainingQty", 0.0)

        for trigger, pct, key in ladder:
            level_key = f"{position.get('pairId','?')}_{key}"
            if level_key not in done and current_profit_pct >= trigger:
                sell_qty = qty * pct
                return {
                    "action":    "PARTIAL_SELL",
                    "pairId":    position.get("pairId"),
                    "sellQty":   sell_qty,
                    "reason":    f"TP {trigger}% → sell {int(pct*100)}%",
                    "levelKey":  level_key,
                    "bucket":    bucket,
                }
        return None


# ═══ PROFIT LOCK ════════════════════════════════════════════

class ProfitLockManager:
    """
    30% dari setiap realized profit dikunci, tidak di-redeploy.
    70% kembali ke bucket untuk trade berikutnya.
    """
    LOCK_RATIO = 0.30

    def __init__(self):
        self.daily_locked = 0.0
        self.daily_profit = 0.0
        self.session_locked = 0.0
        self.lock_ratio = float(os.environ.get("KIBOT_PROFIT_LOCK_RATIO", "0.30"))

    def _refresh_directives(self):
        if DIRECTIVES_FILE.exists():
            try:
                data = json.loads(DIRECTIVES_FILE.read_text())
                self.lock_ratio = float(data.get("risk", {}).get("lock_ratio", self.lock_ratio))
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"[PROFIT_LOCK][WARN] directive refresh error: {e}", flush=True)

    def lock(self, net_profit_idr: float, bucket: str) -> dict:
        if net_profit_idr <= 0:
            return {"locked": 0.0, "redeployable": net_profit_idr}
        self._refresh_directives()
        locked = net_profit_idr * self.lock_ratio
        redeploy = net_profit_idr - locked
        self.daily_locked += locked
        self.daily_profit += net_profit_idr
        self.session_locked += locked
        return {"locked": locked, "redeployable": redeploy, "bucket": bucket}

    def daily_reset(self):
        self.daily_locked = 0.0
        self.daily_profit = 0.0

    def status(self) -> dict:
        return {
            "daily_locked":  self.daily_locked,
            "daily_profit":  self.daily_profit,
            "session_locked": self.session_locked,
            "lock_ratio":    self.lock_ratio,
        }


# ═══ TRAILING STOP (adaptive per bucket per price tier) ═════

class AdaptiveTrailingStop:
    """
    Trailing stop berbeda berdasarkan:
    - Bucket (LEAD_LAG lebih ketat, LOCAL_PUMP lebih longgar)
    - Harga koin (micro-cap lebih lebar untuk avoid noise)
    """
    def get_trail_pct(self, bucket: str, price_idr: float,
                      current_profit_pct: float) -> float:
        # Base per bucket
        base = 1.5 if bucket == "LEAD_LAG" else 3.0

        # Price tier override (guardrail yang tidak bisa diubah)
        if price_idr < 50:
            return max(base, 7.0)   # Ultra micro-cap: min 7%
        elif price_idr < 500:
            return max(base, 3.5)   # Micro-cap: min 3.5%

        # Dynamic: semakin besar profit, trailing lebih ketat
        if current_profit_pct > 5.0:
            base = base * 0.7  # Tighten saat sudah profit besar
        return base

    def should_stop(self, position: dict, current_price: float) -> bool:
        high_water = position.get("highWaterPrice", position.get("entryPrice", current_price))
        trail_pct  = self.get_trail_pct(
            bucket=position.get("bucketType", "LOCAL_PUMP"),
            price_idr=current_price,
            current_profit_pct=position.get("currentProfitPct", 0)
        )
        stop_price = high_water * (1 - trail_pct / 100)
        return current_price <= stop_price


# ═══ HARD STOP GUARD ════════════════════════════════════════

class HardStopGuard:
    """
    Hard stop -3% daily loss dan 12h position timeout.
    Tidak bisa di-bypass oleh apapun.
    """
    DAILY_LOSS_LIMIT_PCT = float(os.environ.get("KIBOT_HARD_DAILY_LOSS_PCT", "3.0"))
    POS_TIMEOUT_HOURS    = float(os.environ.get("KIBOT_POS_TIMEOUT_HOURS",   "12.0"))

    def __init__(self):
        self.daily_pnl = 0.0
        self.initial_capital = 0.0
        self.hard_stopped = False
        self.loss_limit_pct = self.DAILY_LOSS_LIMIT_PCT

    def _refresh_directives(self):
        if DIRECTIVES_FILE.exists():
            try:
                data = json.loads(DIRECTIVES_FILE.read_text())
                self.loss_limit_pct = float(data.get("risk", {}).get("daily_loss_limit_pct", self.loss_limit_pct))
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"[HARD_STOP][WARN] directive refresh error: {e}", flush=True)

    def update_pnl(self, realized_pnl_idr: float):
        self.daily_pnl += realized_pnl_idr
        self._refresh_directives()
        if self.initial_capital > 0:
            loss_pct = -self.daily_pnl / self.initial_capital * 100
            if loss_pct >= self.loss_limit_pct and not self.hard_stopped:
                self.hard_stopped = True
                return True  # Trigger hard stop
        return False

    def check_position_timeout(self, position: dict) -> bool:
        entry_ms = position.get("entryTimestampMs", time.time() * 1000)
        held_h   = (time.time() * 1000 - entry_ms) / 3600000
        return held_h >= self.POS_TIMEOUT_HOURS

    def can_enter(self) -> bool:
        return not self.hard_stopped

    def daily_reset(self):
        self.daily_pnl = 0.0
        self.hard_stopped = False
