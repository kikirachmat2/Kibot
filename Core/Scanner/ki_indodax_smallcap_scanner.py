import json, time, requests
from datetime import datetime
import logging

logger = logging.getLogger("IndodaxScanner")

# Thresholds untuk small cap pump detection (Aggressive V3.1)
VOLUME_SPIKE_MULTIPLIER = 1.5   # volume > 1.5x rata-rata 30m (Was 3.0)
PRICE_CHANGE_MIN_PCT    = 0.5   # harga naik minimal 0.5% dalam 5 menit (Was 1.5)
OBI_MIN                 = 0.1   # order book imbalance minimum (beli > jual) (Was 0.3)
MIN_VOLUME_IDR          = 1_000_000   # filter dust: min 1jt IDR volume/jam (Was 5jt)
MAX_VOLUME_IDR          = 1_000_000_000_000  # 1 Trillion IDR (Essentially no upper limit for BTC/ETH) (Was 50B)

class IndodaxSmallCapScanner:
    def __init__(self):
        self.exchange = "INDODAX"
        self.price_history = {}   # pair → list of (ts, price)
        self.volume_history = {}  # pair → list of (ts, volume_idr)

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
        """Hitung OBI dari top 10 bid/ask."""
        try:
            r = requests.get(f"https://indodax.com/api/{pair}/depth", timeout=4)
            if r.status_code != 200:
                return 0.0
            data = r.json()
            bids = sum(float(b[1]) for b in data.get("buy", [])[:10])
            asks = sum(float(a[1]) for a in data.get("sell", [])[:10])
            total = bids + asks
            return (bids - asks) / total if total > 0 else 0.0
        except Exception as e:
            logger.error(f"Fetch orderbook failed for {pair}: {e}")
            return 0.0

    def detect_pump(self, pair: str, ticker: dict) -> dict | None:
        now = time.time()
        price = float(ticker.get("last", 0))
        vol_idr = float(ticker.get("vol_idr", 0))

        if price <= 0 or vol_idr < MIN_VOLUME_IDR or vol_idr > MAX_VOLUME_IDR:
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

        # Price change 5 menit terakhir
        cutoff_5m = now - 300
        recent_prices = [p for t, p in self.price_history[pair] if t > cutoff_5m]
        if len(recent_prices) < 2:
            return None
        price_change_pct = (recent_prices[-1] - recent_prices[0]) / recent_prices[0] * 100

        # Volume spike vs rata-rata
        avg_vol = sum(v for _, v in self.volume_history[pair]) / len(self.volume_history[pair])
        vol_ratio = vol_idr / avg_vol if avg_vol > 0 else 1.0

        if price_change_pct < PRICE_CHANGE_MIN_PCT or vol_ratio < VOLUME_SPIKE_MULTIPLIER:
            return None

        # Konfirmasi OBI (fetch orderbook hanya jika threshold price+volume terpenuhi)
        obi = self.fetch_orderbook(pair)
        if obi < OBI_MIN:
            return None  # Pump palsu, order book condong ke jual

        return {
            "type": "SMALLCAP_PUMP",
            "symbol": pair.upper().replace("_", "/"),
            "base_symbol": pair.split("_")[0].upper(),
            "price": price,
            "price_idr": price,
            "change_5m_pct": round(price_change_pct, 2),
            "vol_ratio": round(vol_ratio, 1),
            "obi": round(obi, 3),
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
