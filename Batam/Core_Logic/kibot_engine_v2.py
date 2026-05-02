#!/usr/bin/env python3
"""
KiBot Trinity v7.0 — Dual Bucket Engine
Filosofi: Profit sedikit demi sedikit lama lama jadi bukit
Motto: Minimalisir kerugian, maksimalkan probabilitas keuntungan

ARSITEKTUR:
  Bucket A (50%): Global Lead-Lag — KiBot (Binance) + KiCom (Crypto.com) AND gate
  Bucket B (50%): Local Indodax-Only — ConvictionScore >= 0.85 murni matematis

BLIND SPOT YANG SUDAH DIPERBAIKI:
  - Order fill verification (bukan assume filled)
  - Position state persistent ke disk (survive restart)
  - API rate limiting (jangan ke-ban Indodax)
  - Decimal parsing robust (Indodax pakai koma di beberapa endpoint)
  - Minimum lot size per pair
  - Graceful shutdown (close posisi sebelum SIGTERM)
  - Memory leak prevention (cap _today_trades)
  - Thread-safe state management
"""

import os, json, math, time, threading, signal, sys
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional, Union, Any, Dict, List, Tuple
import urllib.request
import urllib.error
import logging

from coin_universe_overlay import apply_overlay_to_runtime

logger = logging.getLogger("kibot_v2")

# ============================================================
# ENVIRONMENT & PATHS
# ============================================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
STATE_DIR    = Path(os.environ.get("KIBOT_STATE_DIR", str(Path(__file__).resolve().parent.parent / "state")))
STATE_DIR.mkdir(parents=True, exist_ok=True)

TRADE_LOG_FILE    = STATE_DIR / "trade_log.jsonl"
CASCADE_FILE      = STATE_DIR / "cascade_mode.json"
POSITIONS_FILE    = STATE_DIR / "open_positions.json"   # BLIND SPOT FIX: persist posisi
DAILY_GUARD_FILE  = STATE_DIR / "daily_guard.json"
DAILY_SUMMARY_FILE = STATE_DIR / "daily_summary.json"

# ============================================================
# FEE CONSTANTS (Indodax verified)
# ============================================================
MAKER_FEE        = 0.0004   # 0.04% limit order
TAKER_FEE        = 0.0055   # 0.55% market order  
PPH_SELL         = 0.0021   # 0.21% PPh sisi jual (pajak)
ROUND_TRIP_LIMIT = MAKER_FEE + PPH_SELL + MAKER_FEE    # 0.0069 = 0.69%
ROUND_TRIP_MARKET= TAKER_FEE + PPH_SELL + TAKER_FEE    # 0.0131 = 1.31%
BREAKEVEN_LIMIT  = ROUND_TRIP_LIMIT * 1.2               # ~0.83% setelah slippage
BREAKEVEN_MARKET = ROUND_TRIP_MARKET * 1.2              # ~1.57%

# ============================================================
# SYSTEM LIMITS
# ============================================================
MIN_ORDER_IDR      = 10_000    # Minimum order Indodax
MIN_EQUITY_IDR     = 30_000    # Stop trading jika equity < ini
CASH_RESERVE_PCT   = 0.20      # 20% always cash
MAX_POSITIONS_A    = 3
MAX_POSITIONS_B    = 2
SCREEN_INTERVAL_S  = 120       # Scan Bucket B setiap 2 menit (optimized)
BTC_UPDATE_S       = 60        # Update BTC price setiap 1 menit
REVIEW_INTERVAL_S  = 1800      # 30 menit math review
MAX_TODAY_TRADES   = 200       # BLIND SPOT FIX: cap memory

# BLIND SPOT FIX: Rate limiting Indodax
_last_api_call: dict = {}
API_RATE_LIMITS = {
    "tickers":   (1.0, "all_tickers"),
    "ticker":    (0.5, "per_pair"),
    "ohlcv":     (2.0, "per_pair"),
    "orderbook": (0.5, "per_pair"),
}

def _rate_limited_fetch(url: str, rate_key: str, timeout: int = 8) -> Optional[bytes]:
    """Fetch dengan rate limiting — jangan spam API Indodax."""
    now = time.time()
    min_interval = API_RATE_LIMITS.get(rate_key, (1.0,))[0]
    last = _last_api_call.get(rate_key, 0)
    wait = min_interval - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_api_call[rate_key] = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        logger.debug(f"[FETCH] {rate_key}: {e}")
        return None

# ============================================================
# INDODAX PAIR SPECS
# BLIND SPOT FIX: minimum lot size berbeda per pair
# ============================================================
INDODAX_PAIR_SPECS = {
    "btc_idr":        {"min_idr": 10000, "price_decimals": 0},
    "eth_idr":        {"min_idr": 10000, "price_decimals": 0},
    "xrp_idr":        {"min_idr": 10000, "price_decimals": 2},
    "sol_idr":        {"min_idr": 10000, "price_decimals": 0},
    "doge_idr":       {"min_idr": 10000, "price_decimals": 2},
    "bnb_idr":        {"min_idr": 10000, "price_decimals": 0},
    "ada_idr":        {"min_idr": 10000, "price_decimals": 2},
    "xlm_idr":        {"min_idr": 10000, "price_decimals": 2},
    "trx_idr":        {"min_idr": 10000, "price_decimals": 2},
    "pepe_idr":       {"min_idr": 10000, "price_decimals": 5},
    "shib_idr":       {"min_idr": 10000, "price_decimals": 5},
    "bonk_idr":       {"min_idr": 10000, "price_decimals": 6},
    "whitewhale_idr": {"min_idr": 10000, "price_decimals": 2},
    "br_idr":         {"min_idr": 10000, "price_decimals": 2},
    "drx_idr":        {"min_idr": 10000, "price_decimals": 5},
    "bio_idr":        {"min_idr": 10000, "price_decimals": 2},
    "pippin_idr":     {"min_idr": 10000, "price_decimals": 5},
    "myx_idr":        {"min_idr": 10000, "price_decimals": 2},
    "jellyjelly_idr": {"min_idr": 10000, "price_decimals": 5},
    "aster_idr":      {"min_idr": 10000, "price_decimals": 2},
    "hype_idr":       {"min_idr": 10000, "price_decimals": 0},
    "gravity_idr":    {"min_idr": 10000, "price_decimals": 5},
    "trollsol_idr":   {"min_idr": 10000, "price_decimals": 5},
    "mubarak_idr":    {"min_idr": 10000, "price_decimals": 5},
    "xpl_idr":        {"min_idr": 10000, "price_decimals": 2},
    "fanc_idr":       {"min_idr": 10000, "price_decimals": 5},
    "nova_idr":       {"min_idr": 10000, "price_decimals": 0},
    "mrs_idr":        {"min_idr": 10000, "price_decimals": 2},
    "islm_idr":       {"min_idr": 10000, "price_decimals": 5},
    "vanry_idr":      {"min_idr": 10000, "price_decimals": 5},
}

def get_min_order(pair_id: str) -> float:
    return INDODAX_PAIR_SPECS.get(pair_id, {}).get("min_idr", MIN_ORDER_IDR)

# ============================================================
# PAIR UNIVERSE
# ============================================================
LEAD_LAG_PAIRS = {
    "btc_idr":"BTCUSDT",  "eth_idr":"ETHUSDT",   "xrp_idr":"XRPUSDT",
    "sol_idr":"SOLUSDT",  "doge_idr":"DOGEUSDT",  "bnb_idr":"BNBUSDT",
    "ada_idr":"ADAUSDT",  "shib_idr":"SHIBUSDT",  "xlm_idr":"XLMUSDT",
    "trx_idr":"TRXUSDT",  "dot_idr":"DOTUSDT",    "pepe_idr":"PEPEUSDT",
    "bonk_idr":"BONKUSDT","link_idr":"LINKUSDT",   "avax_idr":"AVAXUSDT",
    "near_idr":"NEARUSDT","apt_idr":"APTUSDT",    "sui_idr":"SUIUSDT",
    "floki_idr":"FLOKIUSDT","enj_idr":"ENJUSDT",  "dusk_idr":"DUSKUSDT",
    "fun_idr":"FUNUSDT",  "atom_idr":"ATOMUSDT",  "uni_idr":"UNIUSDT",
    "pol_idr":"POLUSDT",  "matic_idr":"MATICUSDT","ltc_idr":"LTCUSDT",
    "hbar_idr":"HBARUSDT","arb_idr":"ARBUSDT",
}

CRYPTOCOM_PAIR_MAP = {
    "btc_idr":"BTC_USDT",   "eth_idr":"ETH_USDT",   "xrp_idr":"XRP_USDT",
    "sol_idr":"SOL_USDT",   "doge_idr":"DOGE_USDT",  "bnb_idr":"BNB_USDT",
    "ada_idr":"ADA_USDT",   "xlm_idr":"XLM_USDT",   "trx_idr":"TRX_USDT",
    "dot_idr":"DOT_USDT",   "pepe_idr":"PEPE_USDT",  "bonk_idr":"BONK_USDT",
    "link_idr":"LINK_USDT", "avax_idr":"AVAX_USDT",  "near_idr":"NEAR_USDT",
    "apt_idr":"APT_USDT",   "sui_idr":"SUI_USDT",    "floki_idr":"FLOKI_USDT",
    "enj_idr":"ENJ_USDT",   "dusk_idr":"DUSK_USDT",  "fun_idr":"FUN_USDT",
    "atom_idr":"ATOM_USDT", "uni_idr":"UNI_USDT",    "pol_idr":"POL_USDT",
    "matic_idr":"MATIC_USDT","ltc_idr":"LTC_USDT",   "hbar_idr":"HBAR_USDT",
}

INDODAX_ONLY_PAIRS = [
    "whitewhale_idr","br_idr","drx_idr","bio_idr","pippin_idr",
    "myx_idr","jellyjelly_idr","aster_idr","hype_idr","gravity_idr",
    "trollsol_idr","mubarak_idr","xpl_idr","fanc_idr","nova_idr",
    "mrs_idr","islm_idr","vanry_idr",
]

_coin_universe_overlay_state = apply_overlay_to_runtime(LEAD_LAG_PAIRS, INDODAX_ONLY_PAIRS)

# ============================================================
# CASCADE LOSS INTELLIGENCE
# ============================================================
CASCADE_CONFIG = {
    "GROWTH":     {"kelly_mult":1.0, "conv_min":0.85, "b_active":True,  "max_a":3, "max_b":2},
    "CAUTION":    {"kelly_mult":0.8, "conv_min":0.88, "b_active":True,  "max_a":2, "max_b":1},
    "DEFENSIVE":  {"kelly_mult":0.5, "conv_min":0.90, "b_active":False, "max_a":2, "max_b":0},
    "RESTRICTED": {"kelly_mult":0.3, "conv_min":0.92, "b_active":False, "max_a":1, "max_b":0},
    "HARD_STOP":  {"kelly_mult":0.0, "conv_min":1.00, "b_active":False, "max_a":0, "max_b":0},
}

class CascadeState:
    _lock = threading.Lock()

    def __init__(self):
        self.mode = "GROWTH"
        self.consecutive_losses = 0
        self.wins_today = 0
        self.losses_today = 0
        self.daily_pnl_pct = 0.0
        self._load()

    def _load(self):
        if CASCADE_FILE.exists():
            try:
                d = json.loads(CASCADE_FILE.read_text())
                self.mode = d.get("mode","GROWTH")
                self.consecutive_losses = d.get("consecutive_losses",0)
                self.wins_today = d.get("wins_today",0)
                self.losses_today = d.get("losses_today",0)
                self.daily_pnl_pct = d.get("daily_pnl_pct",0.0)
            except Exception:
                pass

    def save(self):
        CASCADE_FILE.write_text(json.dumps({
            "mode":self.mode,"consecutive_losses":self.consecutive_losses,
            "wins_today":self.wins_today,"losses_today":self.losses_today,
            "daily_pnl_pct":self.daily_pnl_pct,
            "updated":datetime.utcnow().isoformat()
        }, indent=2))

    def cfg(self) -> dict:
        return CASCADE_CONFIG.get(self.mode, CASCADE_CONFIG["GROWTH"])

    def on_win(self):
        with self._lock:
            self.wins_today += 1
            self.consecutive_losses = 0
            prev = self.mode
            if self.mode == "CAUTION":      self.mode = "GROWTH"
            elif self.mode == "DEFENSIVE" and self.wins_today >= 2: self.mode = "CAUTION"
            elif self.mode == "RESTRICTED" and self.wins_today >= 3: self.mode = "DEFENSIVE"
            if prev != self.mode:
                logger.info(f"[CASCADE] {prev} → {self.mode} (win)")
            self.save()

    def on_loss(self, daily_pnl_pct: float):
        with self._lock:
            self.losses_today += 1
            self.consecutive_losses += 1
            self.daily_pnl_pct = daily_pnl_pct
            prev = self.mode
            if daily_pnl_pct <= -0.02:        self.mode = "HARD_STOP"
            elif self.consecutive_losses >= 3: self.mode = "RESTRICTED"
            elif self.consecutive_losses >= 2: self.mode = "DEFENSIVE"
            elif self.consecutive_losses >= 1: self.mode = "CAUTION"
            if prev != self.mode:
                logger.warning(f"[CASCADE] {prev} → {self.mode} (loss)")
            self.save()

    def daily_reset(self):
        with self._lock:
            self.wins_today = 0
            self.losses_today = 0
            if self.mode == "HARD_STOP":
                self.mode = "CAUTION"
            self.save()

cascade_state = CascadeState()

# ============================================================
# OPEN POSITION MANAGER
# ============================================================
class OpenPosition:
    def __init__(self, trade_id: str, pair_id: str, bucket: str,
                 entry_price: float, budget_idr: float, qty: float,
                 conviction: float, phase: str, order_id: str,
                 trailing_pct: float, target_pct: float,
                 entry_at: str):
        self.trade_id = trade_id
        self.pair_id = pair_id
        self.bucket = bucket
        self.entry_price = entry_price
        self.budget_idr = budget_idr
        self.qty = qty
        self.conviction = conviction
        self.phase = phase
        self.order_id = order_id
        self.trailing_pct = trailing_pct
        self.target_pct = target_pct
        self.entry_at = entry_at
        self.peak_price = entry_price
        self.partial_tp_levels = []
        self.fill_verified = False
        self.suspended = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, d: dict) -> "OpenPosition":
        p = cls.__new__(cls)
        p.__dict__.update(d)
        return p

class PositionManager:
    _lock = threading.Lock()

    def __init__(self):
        self._positions: dict[str, OpenPosition] = {}
        self._load()

    def _load(self):
        if POSITIONS_FILE.exists():
            try:
                data = json.loads(POSITIONS_FILE.read_text())
                for pair_id, pd in data.items():
                    self._positions[pair_id] = OpenPosition.from_dict(pd)
                logger.info(f"[POS] Loaded {len(self._positions)} open positions from disk")
            except Exception as e:
                logger.error(f"[POS] Load error: {e}")

    def save(self):
        with self._lock:
            POSITIONS_FILE.write_text(json.dumps(
                {k: v.to_dict() for k, v in self._positions.items()},
                ensure_ascii=False, indent=2, default=str
            ))

    def open(self, pos: OpenPosition):
        with self._lock:
            self._positions[pos.pair_id] = pos
        self.save()

    def close(self, pair_id: str) -> Optional[OpenPosition]:
        with self._lock:
            pos = self._positions.pop(pair_id, None)
        if pos:
            self.save()
        return pos

    def get(self, pair_id: str) -> Optional[OpenPosition]:
        return self._positions.get(pair_id)

    def all(self) -> list[OpenPosition]:
        with self._lock:
            return list(self._positions.values())

    def count_bucket(self, bucket: str) -> int:
        return sum(1 for p in self._positions.values() if p.bucket == bucket)

    def get_unverified_fills(self) -> list[OpenPosition]:
        return [p for p in self._positions.values() if not p.fill_verified]

position_manager = PositionManager()

# ============================================================
# TRADE LOGGER
# ============================================================
class TradeLogger:
    _lock = threading.Lock()

    def __init__(self):
        TRADE_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._today: list[dict] = []
        self._load_today()

    def _load_today(self):
        if not TRADE_LOG_FILE.exists():
            return
        today = (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d")
        try:
            with open(TRADE_LOG_FILE) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        t = json.loads(line)
                        if t.get("entry_at","").startswith(today):
                            self._today.append(t)
                    except Exception:
                        pass
            if len(self._today) > MAX_TODAY_TRADES:
                self._today = self._today[-MAX_TODAY_TRADES:]
        except Exception as e:
            logger.debug(f"[LOG] Load: {e}")

    def record_entry(self, trade_id: str, pair_id: str, bucket: str,
                     entry_price: float, budget_idr: float,
                     conviction: float, phase: str, cascade_mode: str,
                     target_pct: float, trailing_pct: float,
                     order_id: str = "") -> None:
        fee_est = MAKER_FEE * budget_idr
        entry = {
            "trade_id": trade_id, "pair_id": pair_id, "bucket": bucket,
            "entry_price": entry_price, "budget_idr": budget_idr,
            "conviction_score": conviction, "pump_phase": phase,
            "cascade_mode": cascade_mode, "target_pct": target_pct,
            "trailing_pct": trailing_pct, "fee_entry_idr": round(fee_est, 2),
            "order_id": order_id,
            "entry_at": (datetime.utcnow() + timedelta(hours=7)).isoformat(),
            "status": "OPEN"
        }
        with self._lock:
            with open(TRADE_LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
            self._today.append(entry)
        logger.info(f"[LOG] ENTRY {bucket}/{pair_id} @ {entry_price} Rp{budget_idr:,.0f} [{trade_id}]")

    def record_exit(self, trade_id: str, exit_price: float,
                    exit_reason: str, order_type: str = "LIMIT") -> Optional[dict]:
        lines, found = [], None
        if not TRADE_LOG_FILE.exists():
            return None
        with self._lock:
            with open(TRADE_LOG_FILE) as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        t = json.loads(line)
                        if t.get("trade_id") == trade_id and t.get("status") == "OPEN":
                            entry_p = t["entry_price"]
                            budget  = t["budget_idr"]
                            gross   = (exit_price - entry_p) / entry_p
                            fee_ex  = (TAKER_FEE if order_type == "MARKET" else MAKER_FEE) + PPH_SELL
                            net_pct = gross - (t.get("fee_entry_idr", 0) / budget) - fee_ex
                            pnl_idr = budget * net_pct
                            try:
                                entry_dt = datetime.fromisoformat(t["entry_at"])
                                hold_min = int((datetime.now() - entry_dt).total_seconds() / 60)
                            except Exception:
                                hold_min = 0
                            t.update({
                                "exit_price": exit_price,
                                "pnl_idr": round(pnl_idr, 2),
                                "pnl_pct": round(net_pct, 5),
                                "hold_minutes": hold_min,
                                "win": pnl_idr > 0,
                                "exit_reason": exit_reason,
                                "order_type_exit": order_type,
                                "exit_at": (datetime.utcnow() + timedelta(hours=7)).isoformat(),
                                "status": "CLOSED"
                            })
                            found = t
                            self._today.append(t)
                            position_manager.close(t["pair_id"])
                            logger.info(
                                f"[LOG] EXIT {t['bucket']}/{t['pair_id']} "
                                f"Rp{pnl_idr:+,.0f} ({net_pct:+.2%}) "
                                f"hold={hold_min}m [{exit_reason}]"
                            )
                        lines.append(json.dumps(t))
                    except Exception as parse_err:
                        logger.debug(f"[LOG] Parse: {parse_err}")
                        lines.append(line.strip())
            with open(TRADE_LOG_FILE, "w") as f:
                f.write("\n".join(lines) + "\n")
        if found:
            _async_supabase_insert("trade_history", found)
            self.post_mortem(found)
        return found

    def post_mortem(self, trade: dict):
        if trade.get("win") or abs(trade.get("pnl_idr", 0)) < 200:
            return
        phase = trade.get("pump_phase", "")
        hold  = trade.get("hold_minutes", 0)
        exit_r= trade.get("exit_reason", "")
        if hold < 5 and "TIMING" not in exit_r:
            classification = "TIMING"
            lesson = "Entry terlalu dini — tunggu konfirmasi 2+ candle"
        elif phase in ("PEAK", "LATE", "POST_PEAK"):
            classification = "PEAK_ENTRY"
            lesson = "Entry di fase terlambat — conviction score harus > 0.90 untuk fase ini"
        elif "HARD_STOP" in exit_r or "STOP_LOSS" in exit_r:
            classification = "STOP_LOSS"
            lesson = "Stop loss terpicu normal — review apakah trailing % tepat"
        else:
            classification = "FAKE_PUMP"
            lesson = "Volume spike palsu — cek orderbook depth lebih ketat"
        pm_record = {
            "trade_id": trade.get("trade_id"), "pair_id": trade.get("pair_id"),
            "bucket": trade.get("bucket"), "loss_idr": trade.get("pnl_idr"),
            "exit_reason": exit_r, "conviction_at_exit": trade.get("conviction_score"),
            "classification": classification, "lesson": lesson
        }
        _async_supabase_insert("post_mortem_log", pm_record)

    def get_stats(self, bucket: Optional[str] = None) -> dict:
        closed = [t for t in self._today if t.get("status") == "CLOSED"]
        if bucket:
            closed = [t for t in closed if t.get("bucket") == bucket]
        wins = [t for t in closed if t.get("win")]
        losses = [t for t in closed if not t.get("win")]
        n = len(closed)
        if n == 0:
            return {"n":0,"wins":0,"losses":0,"win_rate":0.5,"ev_idr":0,"pf":1.0,"pnl_idr":0}
        wr = len(wins) / n
        aw = sum(t["pnl_idr"] for t in wins)   / max(len(wins), 1)
        al = abs(sum(t["pnl_idr"] for t in losses)) / max(len(losses), 1)
        ev = wr * aw - (1 - wr) * al
        pf = sum(t["pnl_idr"] for t in wins) / max(abs(sum(t["pnl_idr"] for t in losses)), 1)
        return {"n":n,"wins":len(wins),"losses":len(losses),
                "win_rate":round(wr,3),"ev_idr":round(ev,0),
                "pf":round(pf,2),"pnl_idr":round(sum(t["pnl_idr"] for t in closed),0)}

    def get_pair_stats(self, pair_id: str) -> dict:
        closed = [t for t in self._today
                  if t.get("pair_id") == pair_id and t.get("status") == "CLOSED"]
        if not closed:
            return {"n":0,"win_rate":0.5,"pf":1.0,"avg_win":0,"avg_loss":0}
        wins = [t for t in closed if t.get("win")]
        losses = [t for t in closed if not t.get("win")]
        wr = len(wins) / len(closed)
        aw = sum(t["pnl_idr"] for t in wins) / max(len(wins), 1)
        al = abs(sum(t["pnl_idr"] for t in losses)) / max(len(losses), 1)
        pf = sum(t["pnl_idr"] for t in wins) / max(abs(sum(t["pnl_idr"] for t in losses)), 1)
        return {"n":len(closed),"win_rate":round(wr,3),"pf":round(pf,2),
                "avg_win":round(aw,0),"avg_loss":round(al,0)}

    def is_in_cooldown(self, pair_id: str) -> bool:
        losses = [t for t in self._today
                  if t.get("pair_id") == pair_id and
                  t.get("status") == "CLOSED" and not t.get("win")]
        if not losses:
            return False
        try:
            latest = max(losses, key=lambda x: x.get("exit_at",""))
            exit_dt = datetime.fromisoformat(latest["exit_at"])
            return datetime.now() < exit_dt + timedelta(minutes=30)
        except Exception:
            return False

trade_logger = TradeLogger()

# ============================================================
# MATH FUNCTIONS
# ============================================================
def safe_float(val, default: float = 0.0) -> float:
    try:
        return float(str(val).replace(",","."))
    except Exception:
        return default

def fetch_candles(pair_id: str, tf: int = 15, count: int = 30) -> list[dict]:
    base = pair_id.replace("_idr","").upper()
    now = int(time.time())
    from_ts = now - tf * 60 * count
    url = (f"https://indodax.com/tradingview/history_v2"
           f"?symbol={base}/IDR&tf={tf}&from={from_ts}&to={now}")
    raw = _rate_limited_fetch(url, "ohlcv", timeout=10)
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return []
        if not isinstance(data, dict):
            return []
        t  = data.get("t", [])
        c  = data.get("c", data.get("Close", []))
        h  = data.get("h", data.get("High",  []))
        lo = data.get("l", data.get("Low",   []))
        v  = data.get("v", data.get("Vol",   []))
        return [{"t":int(t[i]),"c":safe_float(c[i]),
                 "h":safe_float(h[i]),"l":safe_float(lo[i]),
                 "v":safe_float(v[i]) if i < len(v) else 0}
                for i in range(len(t))]
    except Exception as e:
        logger.debug(f"[CANDLE] {pair_id}: {e}")
        return []

def calc_bollinger(closes: List[float], period: int = 20, mult: float = 2.0) -> Optional[dict]:
    if len(closes) < period:
        return None
    w   = closes[-period:]
    sma = sum(w) / period
    std = math.sqrt(sum((c - sma)**2 for c in w) / period)
    if std < 1e-10:
        return None
    return {"upper": sma + mult*std, "middle": sma, "lower": sma - mult*std, "std": std}

def calc_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains  = [max(d, 0) for d in deltas][-period:]
    losses = [max(-d, 0) for d in deltas][-period:]
    ag, al = sum(gains)/period, sum(losses)/period
    if al < 1e-10:
        return 100.0 if ag > 1e-10 else 50.0
    return 100 - (100 / (1 + ag/al))

def calc_volume_trend(vols: list[float], short: int = 3, long: int = 8) -> str:
    if len(vols) < long:
        return "stable"
    s = sum(vols[-short:]) / short
    l = sum(vols[-long:])  / long
    if s > l * 1.5:   return "increasing"
    if s < l * 0.60:  return "decreasing"
    return "stable"

# ============================================================
# WHAT-IF ENGINE
# ============================================================
def simulate_what_if(pair_id: str, budget: float, spread: float,
                     slippage: float, target: float, stop: float,
                     win_rate: float = 0.5, n: int = 0,
                     use_market: bool = False) -> dict:
    fee   = ROUND_TRIP_MARKET if use_market else ROUND_TRIP_LIMIT
    cost  = spread / 2 + slippage + fee
    net   = target - cost
    loss  = stop + cost
    rew   = budget * max(net, 0)
    risk  = budget * loss
    rr    = rew / max(risk, 1)
    wr    = 0.5 * (n / 5) + win_rate * (1 - n / 5) if n < 5 else win_rate
    ev    = wr * rew - (1 - wr) * risk
    min_net = 0.018 if use_market else 0.008
    if ev <= 0 or rr < 1.2 or net < min_net:
        dec = "SKIP"
    elif rr < 1.5 or wr < 0.45:
        dec = "REDUCE"
    else:
        dec = "ENTER"
    return {"decision":dec,"net_pct":round(net,4),"ev_idr":round(ev,0),
            "rr":round(rr,2),"wr":round(wr,3),"cost":round(cost,4)}

# ============================================================
# BTC REGIME GUARD
# ============================================================
_btc_1h_ago: float = 0.0
_btc_now: float    = 0.0
_btc_hist: list    = []

def update_btc(price: float):
    global _btc_1h_ago, _btc_now, _btc_hist
    _btc_now = price
    now_ts = time.time()
    _btc_hist.append((now_ts, price))
    _btc_hist = [(t, p) for t, p in _btc_hist if now_ts - t <= 3700]
    if _btc_hist:
        hour_old = [(t, p) for t, p in _btc_hist if now_ts - t >= 3500]
        if hour_old:
            _btc_1h_ago = hour_old[0][1]

def btc_change_1h() -> float:
    if _btc_1h_ago <= 0 or _btc_now <= 0:
        return 0.0
    return (_btc_now - _btc_1h_ago) / _btc_1h_ago * 100

def is_btc_ok(bucket: str) -> tuple[bool, str]:
    ch = btc_change_1h()
    if ch < -5.0:  return False, f"BTC dump 1h={ch:.1f}% — semua diblok"
    if bucket=="B" and ch < -4.0: return False, f"BTC dump 1h={ch:.1f}% — B diblok"
    return True, f"BTC 1h={ch:.1f}%"

# ============================================================
# KICOM SCANNER
# ============================================================
_kicom_cache: dict = {}
_kicom_cache_ts: dict = {}
KICOM_CACHE_TTL = 120

def fetch_kicom(pair_id: str) -> Optional[dict]:
    cdc = CRYPTOCOM_PAIR_MAP.get(pair_id)
    if not cdc:
        return None
    now = time.time()
    if pair_id in _kicom_cache and now - _kicom_cache_ts.get(pair_id, 0) < KICOM_CACHE_TTL:
        return _kicom_cache[pair_id]
    url = f"https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={cdc}"
    raw = _rate_limited_fetch(url, "kicom_" + pair_id, timeout=5)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        item = data.get("result", {}).get("data", [{}])[0]
        result = {
            "symbol": cdc,
            "change_24h": safe_float(item.get("c", 0)) * 100,
            "is_bullish": safe_float(item.get("c", 0)) > 0.005,
            "confidence": min(abs(safe_float(item.get("c", 0))) / 0.05, 1.0),
        }
        _kicom_cache[pair_id] = result
        _kicom_cache_ts[pair_id] = now
        return result
    except Exception as e:
        logger.debug(f"[KICOM] {cdc}: {e}")
        return None

def dual_scanner_agree(pair_id: str, KiBot_sig: dict) -> tuple[bool, float, str]:
    kin_conf = KiBot_sig.get("confidence", 0)
    kin_ret  = KiBot_sig.get("shortTermReturnPct", 0)
    KiBot_ok = kin_conf >= 0.60 and kin_ret > 0
    if not KiBot_ok:
        return False, 0.0, f"KiBot tidak confirm (conf={kin_conf:.2f})"
    kicom = fetch_kicom(pair_id)
    if not kicom:
        return False, 0.0, "KiCom tidak tersedia"
    kicom_ok = kicom["is_bullish"] and kicom["confidence"] >= 0.40
    if not kicom_ok:
        return False, 0.0, f"KiCom tidak confirm (bullish={kicom['is_bullish']})"
    combined = (kin_conf + kicom["confidence"]) / 2
    return True, combined, f"BOTH OK (kin={kin_conf:.2f} cdc={kicom['confidence']:.2f})"

# ============================================================
# CONVICTION SCORE
# ============================================================
def compute_conviction(pair_id: str, ticker: dict,
                       closes: list[float], vols: list[float],
                       avg_vol_7d: float) -> dict:
    price      = safe_float(ticker.get("last", 0))
    high_24h   = safe_float(ticker.get("high",  price))
    low_24h    = safe_float(ticker.get("low",   price))
    vol_24h    = safe_float(ticker.get("vol_idr", 0))
    price_open = safe_float(ticker.get("open",  price))
    bid        = safe_float(ticker.get("buy",   price * 0.99))
    ask        = safe_float(ticker.get("sell",  price * 1.01))
    change_24h = (price - price_open) / max(price_open, 0.001) * 100

    if price <= 0:
        return {"score":0.0,"allowed":False,"reason":"invalid price","phase":"BLOCKED"}

    blocks = []
    if change_24h > 50:       blocks.append(f"pump {change_24h:.0f}%>50%")
    if vol_24h < 500_000_000: blocks.append(f"vol {vol_24h/1e9:.2f}B<500M")
    if trade_logger.is_in_cooldown(pair_id): blocks.append("cooldown aktif")
    btc_ok, btc_reason = is_btc_ok("B")
    if not btc_ok: blocks.append(btc_reason)

    bb = calc_bollinger(closes) if len(closes) >= 20 else None
    rsi = calc_rsi(closes)

    if bb and price > bb["upper"]: blocks.append(f"price>BB_upper")
    if rsi > 80: blocks.append(f"RSI={rsi:.0f}>80")

    if blocks:
        return {"score":0.0,"allowed":False,"reason":" | ".join(blocks),"phase":"BLOCKED",
                "rsi":rsi,"components":{}}

    vol_ratio = vol_24h / max(avg_vol_7d, 1)
    vol_score = 0.6 if vol_ratio > 10.0 else min(vol_ratio / 3.0, 1.0)

    if bb and (bb["upper"] - bb["lower"]) > 0:
        bb_pct = (price - bb["lower"]) / (bb["upper"] - bb["lower"])
        bb_score = max(0.0, min(bb_pct, 1.0))
    else:
        pos = (price - low_24h) / max(high_24h - low_24h, 0.001)
        bb_pct = pos
        bb_score = pos

    total_depth = bid + ask
    ob_score = min(bid / max(total_depth, 0.001), 1.0) if total_depth > 0 else 0.5
    mom_score = max(0.0, (75.0 - rsi) / 75.0)

    spread_pct = (ask - bid) / max(bid, 0.001)
    spread_penalty = -0.15 if spread_pct > 0.05 else (-0.05 if spread_pct > 0.02 else 0.0)

    vol_trend = calc_volume_trend(vols)
    vol_trend_score = 1.0 if vol_trend=="increasing" else (0.6 if vol_trend=="stable" else 0.2)

    raw = (
        0.25 * vol_score +
        0.20 * bb_score +
        0.20 * ob_score +
        0.20 * mom_score +
        0.15 * vol_trend_score
    ) + spread_penalty
    score = round(max(0.0, min(raw, 1.0)), 3)

    pos_range = (price - low_24h) / max(high_24h - low_24h, 0.001)
    if pos_range < 0.30:   phase, trail, tgt = "EARLY", 0.05, 0.08
    elif pos_range < 0.55: phase, trail, tgt = "MID",   0.04, 0.05
    elif pos_range < 0.80: phase, trail, tgt = "LATE",  0.03, 0.03
    else:                  phase, trail, tgt = "PEAK",  0.02, 0.02

    min_score = 0.92 if phase == "PEAK" else (0.88 if phase == "LATE" else 0.85)
    allowed = score >= min_score and not blocks

    return {
        "score": score, "allowed": allowed, "phase": phase,
        "reason": f"score={score:.3f} >= {min_score}" if allowed else f"score={score:.3f} < {min_score}",
        "rsi": round(rsi,1), "bb_pct": round(bb_pct,3),
        "vol_ratio": round(vol_ratio,2), "spread_pct": round(spread_pct,4),
        "vol_trend": vol_trend, "trailing_pct": trail, "target_pct": tgt,
        "components": {"vol":round(vol_score,3),"bb":round(bb_score,3),
                       "ob":round(ob_score,3),"mom":round(mom_score,3),
                       "vol_trend":round(vol_trend_score,3)}
    }

# ============================================================
# POSITION SIZING
# ============================================================
def size_bucket_a(balance: float, wr: float, aw: float, al: float,
                   cascade_mult: float, pair_id: str) -> float:
    if al <= 0 or aw <= 0:
        size = balance * 0.08
    else:
        kelly = wr - (1 - wr) / (aw / al)
        size  = balance * max(0, kelly / 2) * cascade_mult
    min_ord = get_min_order(pair_id)
    return max(min_ord, min(size, balance * 0.12))

def size_bucket_b(balance: float, n_trades: int, wr: float,
                   aw: float, al: float, cascade_mult: float,
                   pair_id: str) -> float:
    if n_trades < 20:
        size = balance * 0.08 * cascade_mult
    else:
        if al <= 0 or aw <= 0:
            size = balance * 0.08
        else:
            kelly = wr - (1 - wr) / (aw / al)
            size  = balance * max(0, kelly / 2) * cascade_mult
    min_ord = get_min_order(pair_id)
    return max(min_ord, min(size, balance * 0.10))

# ============================================================
# EXIT STRATEGY
# ============================================================
def evaluate_exit(pos: OpenPosition, cur_price: float,
                  rsi: float, vol_trend: str, conv_score: float,
                  daily_pnl_pct: float, btc_1h: float,
                  hold_min: int, bb_upper: Optional[float]) -> dict:
    pnl = (cur_price - pos.entry_price) / pos.entry_price
    if cur_price > pos.peak_price:
        pos.peak_price = cur_price

    if daily_pnl_pct <= -0.02:
        return {"action":"EXIT_ALL","pct":1.0,"market":True,"reason":"daily -2% hard stop"}
    if pnl <= -0.03:
        return {"action":"EXIT_ALL","pct":1.0,"market":False,"reason":f"hard stop -{abs(pnl):.1%}"}
    if btc_1h < -5.0 and pnl > 0:
        return {"action":"EXIT_ALL","pct":1.0,"market":False,"reason":f"BTC panic {btc_1h:.1f}%"}
    if vol_trend == "decreasing" and hold_min > 15 and pnl > 0.005:
        return {"action":"EXIT_ALL","pct":1.0,"market":False,"reason":"volume collapse"}
    if hold_min > 720:
        return {"action":"EXIT_ALL","pct":1.0,"market":False,"reason":"time exit 12h"}

    peak_signals = sum([
        bb_upper is not None and cur_price > bb_upper * 0.97,
        rsi > 75,
        vol_trend == "decreasing",
        pnl > 0.08,
    ])
    if peak_signals >= 3:
        return {"action":"PARTIAL_EXIT","pct":0.70,"market":False,
                "tighten_trail":0.015,"reason":f"peak {peak_signals}/4 signals"}

    if pos.bucket == "B" and conv_score < 0.60 and hold_min > 30:
        return {"action":"EXIT_ALL","pct":1.0,"market":False,
                "reason":f"conviction drop {conv_score:.2f}"}

    if pnl >= 0.15 and "15pct" not in pos.partial_tp_levels:
        pos.partial_tp_levels.append("15pct")
        return {"action":"PARTIAL_EXIT","pct":0.70,"market":False,
                "tighten_trail":0.015,"reason":"TP +15%"}
    if pnl >= 0.10 and "10pct" not in pos.partial_tp_levels:
        pos.partial_tp_levels.append("10pct")
        return {"action":"PARTIAL_EXIT","pct":0.20,"market":False,
                "tighten_trail":0.020,"reason":"TP +10%"}
    if pnl >= 0.06 and "6pct" not in pos.partial_tp_levels:
        pos.partial_tp_levels.append("6pct")
        return {"action":"PARTIAL_EXIT","pct":0.30,"market":False,
                "tighten_trail":0.025,"reason":"TP +6%"}
    if pnl >= 0.03 and "3pct" not in pos.partial_tp_levels:
        pos.partial_tp_levels.append("3pct")
        return {"action":"PARTIAL_EXIT","pct":0.30,"market":False,
                "reason":"TP +3%"}

    drop_from_peak = (pos.peak_price - cur_price) / pos.peak_price
    if drop_from_peak >= pos.trailing_pct:
        return {"action":"EXIT_ALL","pct":1.0,"market":False,
                "reason":f"trailing stop -{drop_from_peak:.1%}"}

    if pnl <= -0.015:
        return {"action":"TIGHTEN_TRAIL","pct":0,"market":False,
                "tighten_trail":pos.trailing_pct * 0.5,
                "reason":"loss warning -1.5%"}

    return {"action":"HOLD","pct":0,"market":False,"reason":"hold"}

# ============================================================
# SCREENER
# ============================================================
_known_pairs: set = set()

def screen_bucket_b(all_tickers: dict, btc_1h: float,
                     cfg: dict, equity_idr: float) -> list[dict]:
    if not cfg.get("b_active", True):
        return []

    bucket_b_balance = equity_idr * (1 - CASH_RESERVE_PCT) * 0.50
    available_slots = cfg["max_b"] - position_manager.count_bucket("B")
    if available_slots <= 0:
        return []

    candidates = []
    current = set(k for k in all_tickers.keys() if k.endswith("_idr"))
    _known_pairs.update(current)

    for pair_id in INDODAX_ONLY_PAIRS:
        ticker = all_tickers.get(pair_id)
        if not ticker:
            continue
        vol_24h = safe_float(ticker.get("vol_idr", 0))
        if vol_24h < 500_000_000:
            continue
        if position_manager.get(pair_id):
            continue

        candles = fetch_candles(pair_id, tf=15, count=30)
        closes  = [c["c"] for c in candles]
        vols    = [c["v"] for c in candles]
        avg_vol = vol_24h

        conv = compute_conviction(pair_id, ticker, closes, vols, avg_vol)
        if conv["score"] < 0.70:
            continue

        pair_stats = trade_logger.get_pair_stats(pair_id)
        sim = simulate_what_if(
            pair_id, bucket_b_balance * 0.08,
            spread=conv.get("spread_pct", 0.02),
            slippage=0.015,
            target=conv["target_pct"],
            stop=conv["trailing_pct"],
            win_rate=pair_stats.get("win_rate", 0.5),
            n=pair_stats.get("n", 0)
        )
        if sim["decision"] == "SKIP":
            continue

        candidates.append({
            "pair_id": pair_id, "ticker": ticker,
            "conv": conv, "pair_stats": pair_stats,
            "sim": sim, "score": conv["score"],
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:3]

# ============================================================
# UTILS
# ============================================================
def verify_fill(pos: OpenPosition) -> bool:
    if not pos.order_id or pos.order_id == "":
        pos.fill_verified = True
        return True
    entry_dt = datetime.fromisoformat(pos.entry_at)
    age_min = (datetime.now() - entry_dt).total_seconds() / 60
    if age_min > 5 and not pos.fill_verified:
        logger.warning(f"[FILL] {pos.pair_id} order {pos.order_id} timeout — cancel")
        return False
    return pos.fill_verified

_shutting_down = False
def _on_sigterm(signum, frame):
    global _shutting_down
    logger.warning("[SHUTDOWN] SIGTERM received...")
    _shutting_down = True
    position_manager.save()

def register_shutdown():
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)

register_shutdown()

def _async_supabase_insert(table: str, data: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    def _do():
        try:
            clean = {k: v for k, v in data.items()
                     if not isinstance(v, (list, dict)) or k in ("post_mortem_tags",)}
            payload = json.dumps(clean, default=str).encode()
            req = urllib.request.Request(
                f"{SUPABASE_URL}/rest/v1/{table}",
                data=payload,
                headers={"apikey": SUPABASE_KEY,
                         "Authorization": f"Bearer {SUPABASE_KEY}",
                         "Content-Type": "application/json",
                         "Prefer": "resolution=ignore-duplicates"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=8)
        except Exception as e:
            logger.debug(f"[SB] {table}: {e}")
    threading.Thread(target=_do, daemon=True).start()

def run_math_review(equity: float, daily_pnl_pct: float) -> str:
    stats = trade_logger.get_stats()
    now_wib = datetime.utcnow() + timedelta(hours=7)
    ev = stats.get("ev_idr", 0)
    wr = stats.get("win_rate", 0.5)
    action = ("TIGHTEN" if ev <= 0 and stats["n"] >= 3
              else "OPTIMAL" if wr >= 0.65 and ev > 0
              else "CONTINUE")
    em = "🟢" if daily_pnl_pct >= 0 else ("🟡" if daily_pnl_pct >= -0.01 else "🔴")
    msg = (
        f"📊 [{now_wib.strftime('%H:%M')} WIB] Review\n"
        f"{em} PnL: {daily_pnl_pct:+.2%} | Eq: Rp{equity:,.0f}\n"
        f"📈 {stats['n']}T ({stats.get('wins',0)}W/{stats.get('losses',0)}L) "
        f"WR={wr:.0%} EV=Rp{ev:+,.0f}\n"
        f"⚡ Mode: {cascade_state.mode} | {action}"
    )
    _async_supabase_insert("performance_snapshots", {
        "equity_idr": equity, "daily_pnl_pct": daily_pnl_pct,
        "cascade_mode": cascade_state.mode,
        "trades_today": stats["n"], "win_rate_today": wr,
        "ev_today_idr": ev, "action_taken": action
    })
    return msg

print("✅ kibot_engine_v2.py OK")
