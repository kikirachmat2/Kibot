"""
Candle Enrichment Manager for KiBot V2.
Maintains rolling daily (1D) candle history and precomputes full technical indicators:
- EMA(20), EMA(50), EMA(100)
- RSI(14)
- ATR(14)
- Bollinger Bands (20, 2.0) & Bollinger %B
- ADX(14) & SMA20 Slope (5)
- Choppiness Index (14)
- Volume Z-Score (20) & Volume SMA(20)

Fetches from Indodax TradingView API out-of-band every 300 seconds and caches in memory.
Enables sub-microsecond zero-latency injection of indicators into candidate payloads.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
import aiohttp

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

logger = logging.getLogger("KiBotV2.CandleEnrichment")


class CandleEnrichmentManager:
    """
    Background worker that manages 1D historical candles and indicator snapshots
    for the swing trading universe (BTC, ETH, AVAX, SOL).
    """

    DEFAULT_SYMBOLS = ["BTCIDR", "ETHIDR", "AVAXIDR", "SOLIDR"]
    API_URL = "https://indodax.com/tradingview/history_v2"

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        refresh_interval_s: float = 300.0,
        history_days: int = 150,
        timeout_s: float = 10.0,
    ):
        self.symbols = symbols or self.DEFAULT_SYMBOLS
        self.refresh_interval_s = refresh_interval_s
        self.history_days = history_days
        self.timeout_s = timeout_s

        # In-memory indicator cache: normalized_symbol -> Dict[str, Any]
        self._indicators: Dict[str, Dict[str, Any]] = {}
        # In-memory raw candle cache: normalized_symbol -> Dict of lists
        self._raw_candles: Dict[str, Dict[str, List[float]]] = {}

        self._session: Optional[aiohttp.ClientSession] = None
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Converts 'BTC/IDR', 'btc_idr', 'BTCIDR' to 'BTCIDR'."""
        return symbol.upper().replace("/", "").replace("_", "").strip()

    async def start(self) -> None:
        """Initializes HTTP session, performs immediate warm-up fetch, and starts background loop."""
        self._running = True
        self._session = aiohttp.ClientSession()
        logger.info(f"[CandleManager] Initializing 1D candle enrichment for {self.symbols}...")
        
        # Warm-up fetch before letting trading loop process candidates
        await self.refresh_all_symbols()
        
        self._task = asyncio.create_task(self._run_loop())
        logger.info("[CandleManager] Started background candle refresh loop (interval=300s)")

    async def stop(self) -> None:
        """Stops background loop and closes HTTP session."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("[CandleManager] Stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.refresh_interval_s)
                await self.refresh_all_symbols()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"[CandleManager] Background refresh loop error (gracefully swallowed): {exc}")

    async def refresh_all_symbols(self) -> None:
        """Fetches and computes indicators for all configured symbols."""
        for sym in self.symbols:
            try:
                await self.fetch_and_compute_symbol(sym)
            except Exception as e:
                logger.warning(f"[CandleManager] Failed to refresh candles for {sym}: {e}")

    async def fetch_and_compute_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetches 150 daily bars from Indodax TradingView API and computes technical indicators.
        """
        norm_sym = self.normalize_symbol(symbol)
        now = int(time.time())
        from_ts = now - (self.history_days * 86400)
        url = f"{self.API_URL}?symbol={norm_sym}&tf=1D&from={from_ts}&to={now}"

        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        try:
            async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout_s)) as resp:
                if resp.status != 200:
                    logger.warning(f"[CandleManager] HTTP {resp.status} fetching {norm_sym} candles")
                    return self._indicators.get(norm_sym)

                data = await resp.json()
                if not isinstance(data, list) or len(data) < 20:
                    logger.warning(f"[CandleManager] Incomplete data for {norm_sym}: {len(data) if isinstance(data, list) else type(data)}")
                    return self._indicators.get(norm_sym)

                computed = self.process_candles(norm_sym, data)
                self._indicators[norm_sym] = computed
                logger.info(
                    f"[CandleManager] 📊 Refreshed {norm_sym} ({len(data)} bars): "
                    f"Close={computed['price']:,.0f} | EMA20={computed['ema20']:,.0f} | "
                    f"EMA50={computed['ema50']:,.0f} | EMA100={computed['ema100']:,.0f} | "
                    f"RSI={computed['rsi14']:.1f} | CI={computed['choppiness_index']:.1f}"
                )
                return computed
        except Exception as exc:
            logger.warning(f"[CandleManager] Network/parse error fetching {norm_sym}: {exc}")
            return self._indicators.get(norm_sym)

    def process_candles(self, norm_sym: str, data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Processes list of candle dicts and computes full indicators dictionary.
        """
        closes = [float(d.get("Close") or d.get("close") or d.get("c") or 0.0) for d in data]
        highs = [float(d.get("High") or d.get("high") or d.get("h") or 0.0) for d in data]
        lows = [float(d.get("Low") or d.get("low") or d.get("l") or 0.0) for d in data]
        volumes = [float(d.get("Volume") or d.get("volume") or d.get("v") or 0.0) for d in data]

        times = [float(d.get("Time") or d.get("time") or d.get("t") or 0.0) for d in data]

        # Cache raw series for live price adjustment
        self._raw_candles[norm_sym] = {
            "closes": list(closes),
            "highs": list(highs),
            "lows": list(lows),
            "volumes": list(volumes),
            "times": list(times),
        }

        computed = self._compute_from_series(closes, highs, lows, volumes, times)
        self._indicators[norm_sym] = computed
        return computed

    def _compute_from_series(
        self,
        closes: List[float],
        highs: List[float],
        lows: List[float],
        volumes: List[float],
        times: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Computes technical indicator values from OHLCV arrays including intraday volume run-rate."""
        n = len(closes)
        if n < 20:
            return {}

        ema20_s = calc_ema(closes, 20)
        ema50_s = calc_ema(closes, 50)
        ema100_s = calc_ema(closes, 100)
        rsi_s = calc_rsi(closes, 14)
        atr_s = calc_atr(highs, lows, closes, 14)
        vol_sma20 = calc_sma(volumes, 20)
        mid_bb, up_bb, low_bb = calc_bollinger_bands(closes, 20, 2.0)
        adx_s = calc_adx(highs, lows, closes, 14)
        sma20_series = calc_sma(closes, 20)
        slope = calc_slope(sma20_series, 5)
        ci_s = calc_choppiness_index(highs, lows, closes, 14)
        vol_z_s = calc_volume_zscore(volumes, 20)
        pct_b_s = calc_bollinger_pct_b(closes, up_bb, low_bb)

        # Intraday Volume Run-Rate Normalization
        now = time.time()
        tau = 1.0
        if times and len(times) > 0 and times[-1] > 0:
            elapsed = max(0.0, now - times[-1])
            # Bound tau between 0.15 (~3.6h of trading day) and 1.0
            tau = max(0.15, min(1.0, elapsed / 86400.0))

        vol_last = volumes[-1] if volumes else 0.0
        volume_projected = vol_last / tau
        current_vol_sma20 = vol_sma20[-1] if (vol_sma20 and vol_sma20[-1] > 0) else 1.0
        volume_projected_ratio = round(volume_projected / current_vol_sma20, 2)

        prior_vol = volumes[-2] if len(volumes) >= 2 else vol_last
        prior_bar_volume_ratio = round(prior_vol / current_vol_sma20, 2)
        prior_bar_zscore = round(vol_z_s[-2], 2) if len(vol_z_s) >= 2 else 0.0

        return {
            "price": closes[-1],
            "ema20": round(ema20_s[-1], 2),
            "ema50": round(ema50_s[-1], 2),
            "ema100": round(ema100_s[-1], 2),
            "rsi14": round(rsi_s[-1], 2),
            "atr14": round(atr_s[-1], 2),
            "volume": round(volumes[-1], 4),
            "volume_sma20": round(vol_sma20[-1], 4),
            "volume_projected": round(volume_projected, 4),
            "volume_projected_ratio": volume_projected_ratio,
            "prior_bar_volume_ratio": prior_bar_volume_ratio,
            "prior_bar_zscore": prior_bar_zscore,
            "intraday_tau": round(tau, 3),
            "lower_bb": round(low_bb[-1], 2),
            "middle_bb": round(mid_bb[-1], 2),
            "upper_bb": round(up_bb[-1], 2),
            "adx14": round(adx_s[-1], 2),
            "sma20_slope": round(slope, 5),
            "choppiness_index": round(ci_s[-1], 2),
            "volume_zscore": round(vol_z_s[-1], 2),
            "bollinger_pct_b": round(pct_b_s[-1], 4),
            "bars_count": n,
            "last_updated": time.time(),
        }

    def update_live_price(self, symbol: str, current_price: float) -> Optional[Dict[str, Any]]:
        """
        Adjusts the latest bar's close price with real-time WebSocket tick
        and returns updated indicator snapshot.
        """
        norm_sym = self.normalize_symbol(symbol)
        raw = self._raw_candles.get(norm_sym)
        if not raw or not raw["closes"] or current_price <= 0:
            return self._indicators.get(norm_sym)

        # Clone and update latest bar
        closes = list(raw["closes"])
        highs = list(raw["highs"])
        lows = list(raw["lows"])
        volumes = raw["volumes"]
        times = raw.get("times")

        closes[-1] = current_price
        if current_price > highs[-1]:
            highs[-1] = current_price
        if current_price < lows[-1]:
            lows[-1] = current_price

        updated = self._compute_from_series(closes, highs, lows, volumes, times)
        self._indicators[norm_sym] = updated
        return updated

    def get_indicators(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns the latest indicator snapshot for symbol in sub-microsecond time."""
        norm_sym = self.normalize_symbol(symbol)
        return self._indicators.get(norm_sym)
