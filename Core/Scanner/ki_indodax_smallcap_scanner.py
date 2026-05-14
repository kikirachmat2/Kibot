import json, os, time, requests
from datetime import datetime
import logging

logger = logging.getLogger("IndodaxScanner")

# Thresholds untuk small cap pump detection (Aggressive V4.0)
# Fokus: coins yang sedang naik kuat, dekat high harian, dan masih punya volume persistence.
VOLUME_SPIKE_MULTIPLIER = 1.35
PRICE_CHANGE_MIN_PCT    = 0.35  # 5m momentum minimum untuk ignition kecil
OBI_MIN                 = 0.1   # order book imbalance minimum (beli > jual)
MIN_VOLUME_IDR          = 1_000_000
MAX_VOLUME_IDR          = 1_000_000_000_000  # Praktis no upper limit untuk major pairs
CONTINUATION_MIN_RUNUP_PCT = 10.0
CONTINUATION_MIN_RANGE_POSITION = 0.65
CONTINUATION_MAX_DIST_TO_HIGH_PCT = 12.5
MATURE_MIN_RUNUP_PCT = 22.0
MATURE_MIN_RANGE_POSITION = 0.50
MATURE_MAX_DIST_TO_HIGH_PCT = 20.0
MATURE_MIN_VOLUME_RATIO = 1.05
CONTINUATION_MIN_VOLUME_RATIO = 1.15
PULLBACK_MIN_RUNUP_PCT = 18.0
PULLBACK_MIN_RANGE_POSITION = 0.38
PULLBACK_MAX_DIST_TO_HIGH_PCT = 32.0
PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT = 35.0
PULLBACK_MIN_VOLUME_RATIO = 1.05
PULLBACK_MIN_RECLAIM_SCORE = 0.55
LATE_RECLAIM_MIN_RUNUP_PCT = 25.0
LATE_RECLAIM_MIN_RANGE_POSITION = 0.28
LATE_RECLAIM_MAX_DIST_TO_HIGH_PCT = 45.0
LATE_RECLAIM_MAX_DRAWDOWN_FROM_HIGH_PCT = 45.0
LATE_RECLAIM_MIN_VOLUME_RATIO = 1.08
LATE_RECLAIM_MIN_RECLAIM_SCORE = 0.64
RANGE_BREAK_MIN_RUNUP_PCT = 15.0
RANGE_BREAK_MIN_RANGE_POSITION = 0.22
RANGE_BREAK_MIN_BREAKOUT_FROM_LOW_PCT = 2.0
RANGE_BREAK_MAX_DIST_TO_HIGH_PCT = 55.0
RANGE_BREAK_MIN_VOLUME_RATIO = 1.10
RANGE_BREAK_MIN_RECLAIM_SCORE = 0.70
SUPPORT_BOUNCE_MIN_RUNUP_PCT = 6.0
SUPPORT_BOUNCE_MIN_RANGE_POSITION = 0.08
SUPPORT_BOUNCE_MAX_DIST_TO_HIGH_PCT = 72.0
SUPPORT_BOUNCE_MIN_BOUNCE_FROM_LOW_PCT = 1.5
SUPPORT_BOUNCE_MIN_VOLUME_RATIO = 1.08
SUPPORT_BOUNCE_MIN_RECLAIM_SCORE = 0.66
PIVOT_RECLAIM_MIN_RUNUP_PCT = 4.0
PIVOT_RECLAIM_MIN_RANGE_POSITION = 0.05
PIVOT_RECLAIM_MAX_DIST_TO_HIGH_PCT = 82.0
PIVOT_RECLAIM_MIN_BOUNCE_FROM_LOW_PCT = 1.0
PIVOT_RECLAIM_MIN_VOLUME_RATIO = 1.06
PIVOT_RECLAIM_MIN_RECLAIM_SCORE = 0.60
MAX_TICK_SIZE_PCT = float(os.getenv("KIBOT_MAX_TICK_SIZE_PCT", "3.0"))
MIN_24H_PRICE_LEVELS = int(os.getenv("KIBOT_MIN_24H_PRICE_LEVELS", "8"))
MAX_SCANNER_SPREAD_PCT = float(os.getenv("KIBOT_SCANNER_MAX_SPREAD_PCT", "1.2"))
MIN_CANDLE_DISTINCT_LEVELS = int(os.getenv("KIBOT_MIN_CANDLE_DISTINCT_LEVELS", "6"))
MAX_ZERO_VOLUME_CANDLE_RATIO = float(os.getenv("KIBOT_MAX_ZERO_VOLUME_CANDLE_RATIO", "0.45"))
OHLC_QUALITY_TTL_SEC = int(os.getenv("KIBOT_OHLC_QUALITY_TTL_SEC", "300"))

class IndodaxSmallCapScanner:
    def __init__(self):
        self.exchange = "INDODAX"
        self.price_history = {}   # pair → list of (ts, price)
        self.volume_history = {}  # pair → list of (ts, volume_idr)
        self._price_increments = {}
        self._price_increments_ts = 0.0
        self._ohlc_quality_cache = {}

    def fetch_all_tickers(self):
        try:
            r = requests.get("https://indodax.com/api/summaries", timeout=8)
            if r.status_code != 200:
                logger.error(f"Indodax API returned status {r.status_code}")
                return {}
            if not r.content:
                logger.error("Indodax API returned empty content")
                return {}
            data = r.json()
            return data.get("tickers", {})
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode Indodax tickers JSON: {e}")
            return {}
        except Exception as e:
            logger.error(f"Fetch tickers failed: {e}")
            return {}

    def fetch_orderbook(self, pair: str):
        """Hitung OBI dan spread dari top 10 bid/ask."""
        try:
            r = requests.get(f"https://indodax.com/api/depth/{pair.replace('_', '')}", timeout=4)
            if r.status_code != 200:
                return None
            data = r.json()
            buy_rows = data.get("buy", []) or []
            sell_rows = data.get("sell", []) or []
            bids = sum(float(b[1]) for b in buy_rows[:10])
            asks = sum(float(a[1]) for a in sell_rows[:10])
            total = bids + asks
            obi = (bids - asks) / total if total > 0 else None
            spread_pct = None
            if buy_rows and sell_rows:
                best_bid = float(buy_rows[0][0])
                best_ask = float(sell_rows[0][0])
                if best_bid > 0:
                    spread_pct = ((best_ask - best_bid) / best_bid) * 100
            return {
                "obi": obi,
                "spread_pct": spread_pct,
                "best_bid": float(buy_rows[0][0]) if buy_rows else 0.0,
                "best_ask": float(sell_rows[0][0]) if sell_rows else 0.0,
            }
        except Exception as e:
            logger.error(f"Fetch orderbook failed for {pair}: {e}")
            return None

    def fetch_price_increments(self):
        now = time.time()
        if self._price_increments and now - self._price_increments_ts < 3600:
            return self._price_increments
        try:
            r = requests.get("https://indodax.com/api/price_increments", timeout=8)
            r.raise_for_status()
            data = r.json().get("increments", {})
            self._price_increments = {
                str(pair).lower(): float(value)
                for pair, value in data.items()
                if value not in (None, "")
            }
            self._price_increments_ts = now
        except Exception as e:
            logger.error(f"Fetch price increments failed: {e}")
        return self._price_increments

    def _fetch_ohlc_quality(self, pair: str) -> dict:
        """Lightweight anti-flat-history check using official Indodax OHLC endpoint."""
        now = time.time()
        cached = self._ohlc_quality_cache.get(pair)
        if cached and now - cached.get("ts", 0) < OHLC_QUALITY_TTL_SEC:
            return dict(cached.get("quality", {}))

        quality = {
            "ok": True,
            "distinct_close_levels": 0,
            "zero_volume_ratio": 0.0,
            "trend_efficiency": 0.0,
            "reason": "ok",
        }
        try:
            to_ts = int(now)
            from_ts = to_ts - (18 * 3600)
            symbol = pair.replace("_", "").upper()
            url = (
                "https://indodax.com/tradingview/history_v2"
                f"?from={from_ts}&to={to_ts}&tf=15&symbol={symbol}"
            )
            rows = requests.get(url, timeout=8).json()
            if not isinstance(rows, list) or len(rows) < 10:
                quality.update({"ok": False, "reason": "insufficient_ohlc"})
            else:
                closes = [float(row.get("Close", 0) or 0) for row in rows if float(row.get("Close", 0) or 0) > 0]
                volumes = [float(row.get("Volume", 0) or 0) for row in rows]
                if len(closes) < 10:
                    quality.update({"ok": False, "reason": "insufficient_close_history"})
                else:
                    distinct_levels = len(set(closes))
                    zero_volume_ratio = sum(1 for vol in volumes if vol <= 0) / max(1, len(volumes))
                    total_path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
                    trend_efficiency = abs(closes[-1] - closes[0]) / total_path if total_path > 0 else 0.0
                    quality.update({
                        "distinct_close_levels": distinct_levels,
                        "zero_volume_ratio": round(zero_volume_ratio, 3),
                        "trend_efficiency": round(trend_efficiency, 3),
                    })
                    if distinct_levels < MIN_CANDLE_DISTINCT_LEVELS:
                        quality.update({"ok": False, "reason": "flat_close_history"})
                    elif zero_volume_ratio > MAX_ZERO_VOLUME_CANDLE_RATIO:
                        quality.update({"ok": False, "reason": "too_many_zero_volume_candles"})
        except Exception as e:
            logger.debug(f"OHLC quality check failed for {pair}: {e}")
            quality.update({"ok": True, "reason": "ohlc_unavailable"})

        self._ohlc_quality_cache[pair] = {"ts": now, "quality": dict(quality)}
        return quality

    def detect_pump(self, pair: str, ticker: dict) -> dict | None:
        now = time.time()
        price = float(ticker.get("last", 0))
        day_low = float(ticker.get("low", price) or price)
        day_high = float(ticker.get("high", price) or price)
        vol_idr = float(ticker.get("vol_idr", 0))

        if price <= 0 or vol_idr < MIN_VOLUME_IDR or vol_idr > MAX_VOLUME_IDR:
            return None

        increments = self.fetch_price_increments()
        price_increment = float(increments.get(pair, 1.0) or 1.0)
        tick_size_pct = (price_increment / price * 100) if price > 0 else 100.0
        day_range = max(day_high - day_low, 0.0)
        price_levels_24h = int(day_range / price_increment) + 1 if price_increment > 0 else 0
        if tick_size_pct > MAX_TICK_SIZE_PCT or price_levels_24h < MIN_24H_PRICE_LEVELS:
            logger.debug(
                f"Reject {pair}: tick trap tick={tick_size_pct:.2f}% levels={price_levels_24h}"
            )
            return None

        # Simpan history (window 30 menit)
        if pair not in self.price_history:
            self.price_history[pair] = []
            self.volume_history[pair] = []

        self.price_history[pair].append((now, price))
        self.volume_history[pair].append((now, vol_idr))

        # Bersihkan data > 30 menit
        cutoff = now - 1800
        self.price_history[pair] = [(t, p) for t, p in self.price_history[pair] if t > cutoff]
        self.volume_history[pair] = [(t, v) for t, v in self.volume_history[pair] if t > cutoff]

        if len(self.price_history[pair]) < 3:
            return None

        # Track record sederhana: butuh persistence, bukan cuma lonjakan 1 titik
        price_window = [p for _, p in self.price_history[pair]]
        volume_window = [v for _, v in self.volume_history[pair]]
        if len(price_window) >= 4:
            direction_hits = sum(1 for i in range(1, len(price_window)) if price_window[i] >= price_window[i - 1])
            persistence = direction_hits / max(1, len(price_window) - 1)
        else:
            persistence = 0.0

        # Price change 5 menit terakhir
        cutoff_5m = now - 300
        recent_prices = [p for t, p in self.price_history[pair] if t > cutoff_5m]
        if len(recent_prices) < 2:
            return None
        price_change_pct = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100

        # Volume spike vs rata-rata
        avg_vol = sum(v for _, v in self.volume_history[pair]) / len(self.volume_history[pair])
        vol_ratio = vol_idr / avg_vol if avg_vol > 0 else 1.0
        vol_acceleration = 0.0
        if len(volume_window) >= 4:
            vol_acceleration = (volume_window[-1] - volume_window[-4]) / max(volume_window[-4], 1.0)

        # 24h proxy: how far the pair has already run from day low, and how close it sits to day high.
        runup_from_low_pct = ((price - day_low) / day_low * 100) if day_low > 0 else 0.0
        distance_to_high_pct = ((day_high - price) / day_high * 100) if day_high > 0 else 100.0
        range_position = ((price - day_low) / day_range) if day_range > 0 else 0.0
        range_position = max(0.0, min(1.0, range_position))

        trend_continuation = (
            runup_from_low_pct >= CONTINUATION_MIN_RUNUP_PCT
            and range_position >= CONTINUATION_MIN_RANGE_POSITION
            and distance_to_high_pct <= CONTINUATION_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= CONTINUATION_MIN_VOLUME_RATIO
            and persistence >= 0.55
        )
        pullback_reclaim = False
        pullback_reclaim_score = 0.0
        late_reclaim = False
        late_reclaim_score = 0.0
        range_break_reclaim = False
        range_break_reclaim_score = 0.0
        support_bounce_reclaim = False
        support_bounce_reclaim_score = 0.0
        pivot_reclaim = False
        pivot_reclaim_score = 0.0
        if not trend_continuation:
            recent_low_5m = min(recent_prices) if recent_prices else price
            reclaim_from_low_pct = ((price - recent_low_5m) / recent_low_5m * 100) if recent_low_5m > 0 else 0.0
            drawdown_from_high_pct = ((day_high - price) / day_high * 100) if day_high > 0 else 100.0
            reclaim_score = 0.0
            reclaim_score += min(1.0, max(0.0, runup_from_low_pct / 45.0)) * 0.30
            reclaim_score += min(1.0, max(0.0, reclaim_from_low_pct / 6.0)) * 0.25
            reclaim_score += min(1.0, max(0.0, persistence)) * 0.20
            reclaim_score += min(1.0, max(0.0, vol_ratio - 1.0)) * 0.15
            reclaim_score += max(0.0, 1.0 - min(1.0, drawdown_from_high_pct / PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT)) * 0.10
            pullback_reclaim = (
                runup_from_low_pct >= PULLBACK_MIN_RUNUP_PCT
                and range_position >= PULLBACK_MIN_RANGE_POSITION
                and distance_to_high_pct <= PULLBACK_MAX_DIST_TO_HIGH_PCT
                and vol_ratio >= PULLBACK_MIN_VOLUME_RATIO
                and persistence >= 0.50
                and reclaim_from_low_pct >= 1.5
                and drawdown_from_high_pct <= PULLBACK_MAX_DRAWDOWN_FROM_HIGH_PCT
                and reclaim_score >= PULLBACK_MIN_RECLAIM_SCORE
            )
            pullback_reclaim_score = round(reclaim_score, 3)
            late_reclaim = (
                runup_from_low_pct >= LATE_RECLAIM_MIN_RUNUP_PCT
                and range_position >= LATE_RECLAIM_MIN_RANGE_POSITION
                and distance_to_high_pct <= LATE_RECLAIM_MAX_DIST_TO_HIGH_PCT
                and vol_ratio >= LATE_RECLAIM_MIN_VOLUME_RATIO
                and persistence >= 0.55
                and reclaim_from_low_pct >= 1.0
                and drawdown_from_high_pct <= LATE_RECLAIM_MAX_DRAWDOWN_FROM_HIGH_PCT
                and reclaim_score >= LATE_RECLAIM_MIN_RECLAIM_SCORE
            )
            late_reclaim_score = round(reclaim_score, 3)
            breakout_from_low_pct = reclaim_from_low_pct
            range_break_reclaim = (
                runup_from_low_pct >= RANGE_BREAK_MIN_RUNUP_PCT
                and range_position >= RANGE_BREAK_MIN_RANGE_POSITION
                and distance_to_high_pct <= RANGE_BREAK_MAX_DIST_TO_HIGH_PCT
                and vol_ratio >= RANGE_BREAK_MIN_VOLUME_RATIO
                and persistence >= 0.58
                and breakout_from_low_pct >= RANGE_BREAK_MIN_BREAKOUT_FROM_LOW_PCT
                and reclaim_score >= RANGE_BREAK_MIN_RECLAIM_SCORE
            )
            range_break_reclaim_score = round(reclaim_score, 3)
            support_bounce_reclaim = (
                runup_from_low_pct >= SUPPORT_BOUNCE_MIN_RUNUP_PCT
                and range_position >= SUPPORT_BOUNCE_MIN_RANGE_POSITION
                and distance_to_high_pct <= SUPPORT_BOUNCE_MAX_DIST_TO_HIGH_PCT
                and vol_ratio >= SUPPORT_BOUNCE_MIN_VOLUME_RATIO
                and persistence >= 0.52
                and reclaim_from_low_pct >= SUPPORT_BOUNCE_MIN_BOUNCE_FROM_LOW_PCT
                and reclaim_score >= SUPPORT_BOUNCE_MIN_RECLAIM_SCORE
            )
            support_bounce_reclaim_score = round(reclaim_score, 3)
            pivot_reclaim = (
                runup_from_low_pct >= PIVOT_RECLAIM_MIN_RUNUP_PCT
                and range_position >= PIVOT_RECLAIM_MIN_RANGE_POSITION
                and distance_to_high_pct <= PIVOT_RECLAIM_MAX_DIST_TO_HIGH_PCT
                and vol_ratio >= PIVOT_RECLAIM_MIN_VOLUME_RATIO
                and persistence >= 0.48
                and reclaim_from_low_pct >= PIVOT_RECLAIM_MIN_BOUNCE_FROM_LOW_PCT
                and reclaim_score >= PIVOT_RECLAIM_MIN_RECLAIM_SCORE
            )
            pivot_reclaim_score = round(reclaim_score, 3)
        mature_pump = (
            runup_from_low_pct >= MATURE_MIN_RUNUP_PCT
            and range_position >= MATURE_MIN_RANGE_POSITION
            and distance_to_high_pct <= MATURE_MAX_DIST_TO_HIGH_PCT
            and vol_ratio >= MATURE_MIN_VOLUME_RATIO
        )

        price_floor = PRICE_CHANGE_MIN_PCT
        volume_floor = VOLUME_SPIKE_MULTIPLIER
        if trend_continuation:
            price_floor = 0.25
            volume_floor = min(volume_floor, CONTINUATION_MIN_VOLUME_RATIO)
        if pullback_reclaim:
            price_floor = min(price_floor, 0.22)
            volume_floor = min(volume_floor, PULLBACK_MIN_VOLUME_RATIO)
        if late_reclaim:
            price_floor = min(price_floor, 0.18)
            volume_floor = min(volume_floor, LATE_RECLAIM_MIN_VOLUME_RATIO)
        if range_break_reclaim:
            price_floor = min(price_floor, 0.16)
            volume_floor = min(volume_floor, RANGE_BREAK_MIN_VOLUME_RATIO)
        if support_bounce_reclaim:
            price_floor = min(price_floor, 0.16)
            volume_floor = min(volume_floor, SUPPORT_BOUNCE_MIN_VOLUME_RATIO)
        if pivot_reclaim:
            price_floor = min(price_floor, 0.15)
            volume_floor = min(volume_floor, PIVOT_RECLAIM_MIN_VOLUME_RATIO)
        if mature_pump:
            price_floor = min(price_floor, 0.15)
            volume_floor = min(volume_floor, MATURE_MIN_VOLUME_RATIO)

        if price_change_pct < price_floor or vol_ratio < volume_floor:
            return None

        # Confidence score yang lebih berani tapi tetap data-driven
        momentum_score = min(1.0, max(0.0, price_change_pct / 4.0))
        volume_score = min(1.0, max(0.0, (vol_ratio - 1.0) / 3.0))
        persistence_score = min(1.0, max(0.0, persistence))
        acceleration_score = min(1.0, max(0.0, vol_acceleration))
        trend_score = min(1.0, max(0.0, runup_from_low_pct / 35.0))
        range_score = min(1.0, max(0.0, range_position))
        near_high_score = max(0.0, min(1.0, 1.0 - (distance_to_high_pct / 12.0)))
        stage_bonus = 0.06 if trend_continuation else 0.03 if mature_pump else 0.0
        if pullback_reclaim:
            stage_bonus = max(stage_bonus, 0.04)
        if late_reclaim:
            stage_bonus = max(stage_bonus, 0.035)
        if range_break_reclaim:
            stage_bonus = max(stage_bonus, 0.045)
        if support_bounce_reclaim:
            stage_bonus = max(stage_bonus, 0.05)
        if pivot_reclaim:
            stage_bonus = max(stage_bonus, 0.055)
        orderbook = self.fetch_orderbook(pair)
        obi = orderbook.get("obi") if isinstance(orderbook, dict) else None
        spread_pct = orderbook.get("spread_pct") if isinstance(orderbook, dict) else None
        obi_available = obi is not None
        if spread_pct is not None and spread_pct > MAX_SCANNER_SPREAD_PCT:
            return None
        if obi_available and obi < OBI_MIN:
            return None  # Pump palsu, order book condong ke jual

        ohlc_quality = self._fetch_ohlc_quality(pair)
        if not ohlc_quality.get("ok", True):
            logger.debug(f"Reject {pair}: OHLC quality {ohlc_quality.get('reason')}")
            return None
        obi_proxy = max(
            0.0,
            min(
                1.0,
                0.22
                + (trend_score * 0.20)
                + (range_score * 0.18)
                + (persistence_score * 0.16)
                + (volume_score * 0.12)
                + (0.06 if trend_continuation else 0.0)
            ),
        )
        obi_score = min(1.0, max(0.0, ((obi + 1.0) / 2.0) if obi_available else obi_proxy))
        confidence = round(
            min(
                0.96,
                0.22
                + (momentum_score * 0.28)
                + (volume_score * 0.22)
                + (obi_score * 0.16)
                + (persistence_score * 0.10)
                + (acceleration_score * 0.04),
            ),
            4,
        )
        confidence = round(
            min(
                0.98,
                confidence
                + (trend_score * 0.06)
                + (range_score * 0.04)
                + (near_high_score * 0.05)
                + stage_bonus,
            ),
            4,
        )

        return {
            "type": "SMALLCAP_PUMP",
            "symbol": pair.upper().replace("_", "/"),
            "base_symbol": pair.split("_")[0].upper(),
            "price": price,
            "price_idr": price,
            "change_pct": round(price_change_pct, 2),
            "change_5m_pct": round(price_change_pct, 2),
            "runup_24h_proxy_pct": round(runup_from_low_pct, 2),
            "distance_to_high_pct": round(distance_to_high_pct, 2),
            "range_position": round(range_position, 3),
            "vol_ratio": round(vol_ratio, 1),
            "obi": round(obi if obi_available else obi_proxy * 2 - 1, 3),
            "obi_source": "ORDERBOOK" if obi_available else "PROXY",
            "spread_pct": round(float(spread_pct), 3) if spread_pct is not None else None,
            "tick_size_pct": round(tick_size_pct, 3),
            "price_increment": price_increment,
            "price_levels_24h": price_levels_24h,
            "market_quality": ohlc_quality,
            "confidence": confidence,
            "momentum_score": round(momentum_score, 3),
            "volume_score": round(volume_score, 3),
            "persistence_score": round(persistence_score, 3),
            "acceleration_score": round(acceleration_score, 3),
            "trend_score": round(trend_score, 3),
            "range_score": round(range_score, 3),
            "near_high_score": round(near_high_score, 3),
            "trend_continuation": trend_continuation,
            "pullback_reclaim": pullback_reclaim,
            "late_reclaim": late_reclaim,
            "range_break_reclaim": range_break_reclaim,
            "support_bounce_reclaim": support_bounce_reclaim,
            "pivot_reclaim": pivot_reclaim,
            "mature_pump": mature_pump,
            "track_record": {
                "persistence": round(persistence, 3),
                "vol_acceleration": round(vol_acceleration, 3),
                "window_points": len(price_window),
                "day_low": round(day_low, 8),
                "day_high": round(day_high, 8),
                "pullback_reclaim_score": pullback_reclaim_score,
                "late_reclaim_score": late_reclaim_score,
                "range_break_reclaim_score": range_break_reclaim_score,
                "support_bounce_reclaim_score": support_bounce_reclaim_score,
                "pivot_reclaim_score": pivot_reclaim_score,
            },
            "pump_stage": "CONTINUATION" if trend_continuation else "RECLAIM" if pullback_reclaim else "LATE_RECLAIM" if late_reclaim else "RANGE_BREAK_RECLAIM" if range_break_reclaim else "SUPPORT_BOUNCE" if support_bounce_reclaim else "PIVOT_RECLAIM" if pivot_reclaim else "MATURE" if mature_pump else "IGNITION",
            "regime": "PUMP_DETECTED",
            "exchange": "INDODAX",
            "ts": int(now * 1000)
        }

    def collect_signals(self):
        """Standard interface for ScannerEngine."""
        tickers = self.fetch_all_tickers()
        signals = []
        for pair, ticker in tickers.items():
            if not pair.endswith("_idr"):
                continue
            sig = self.detect_pump(pair, ticker)
            if sig:
                signals.append(sig)
        return {"signals": signals}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanner = IndodaxSmallCapScanner()
    while True:
        res = scanner.collect_signals()
        if res["signals"]:
            print(f"Signals detected: {len(res['signals'])}")
        time.sleep(10)
