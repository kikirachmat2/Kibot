import json, time, socket, requests
from datetime import datetime

BATAM_HOST = "168.110.201.228"
BATAM_PORT = 9998

# Thresholds untuk small cap pump detection
VOLUME_SPIKE_MULTIPLIER = 3.0   # volume > 3x rata-rata 30m
PRICE_CHANGE_MIN_PCT    = 1.5   # harga naik minimal 1.5% dalam 5 menit
OBI_MIN                 = 0.3   # order book imbalance minimum (beli > jual)
MIN_VOLUME_IDR          = 5_000_000   # filter dust: min 5jt IDR volume/jam
MAX_VOLUME_IDR          = 50_000_000_000  # filter whale pair yg udah mainstream

class IndodaxSmallCapScanner:
    def __init__(self):
        self.price_history = {}   # pair → list of (ts, price)
        self.volume_history = {}  # pair → list of (ts, volume_idr)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def fetch_all_tickers(self):
        try:
            r = requests.get("https://indodax.com/api/summaries", timeout=8)
            return r.json().get("tickers", {})
        except:
            return {}

    def fetch_orderbook(self, pair: str):
        """Hitung OBI dari top 10 bid/ask."""
        try:
            r = requests.get(f"https://indodax.com/api/{pair}/depth", timeout=4)
            data = r.json()
            bids = sum(float(b[1]) for b in data.get("buy", [])[:10])
            asks = sum(float(a[1]) for a in data.get("sell", [])[:10])
            total = bids + asks
            return (bids - asks) / total if total > 0 else 0.0
        except:
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
            "s": pair.upper().replace("_", "/"),
            "base_symbol": pair.split("_")[0].upper(),
            "p": price,
            "price_idr": price,
            "change_5m_pct": round(price_change_pct, 2),
            "vol_ratio": round(vol_ratio, 1),
            "obi": round(obi, 3),
            "regime": "PUMP_DETECTED",
            "exchange": "INDODAX",
            "ts": int(now * 1000),
            "sentAtEpochMs": int(now * 1000),
        }

    def run(self):
        print("[INDODAX-SMALLCAP] Scanner started — all IDR pairs")
        while True:
            tickers = self.fetch_all_tickers()
            signals = []
            for pair, ticker in tickers.items():
                if not pair.endswith("_idr"):
                    continue
                sig = self.detect_pump(pair, ticker)
                if sig:
                    print(f"🚀 PUMP DETECTED: {sig['s']} +{sig['change_5m_pct']}% vol×{sig['vol_ratio']} OBI={sig['obi']}")
                    signals.append(sig)

            if signals:
                payload = json.dumps({
                    "seq_id": int(time.time()),
                    "ts": int(time.time() * 1000),
                    "signals": signals
                }).encode()
                for _ in range(2):  # UDP redundancy
                    self.sock.sendto(payload, (BATAM_HOST, BATAM_PORT))

            time.sleep(30)  # Scan tiap 30 detik (Indodax rate limit friendly)

if __name__ == "__main__":
    IndodaxSmallCapScanner().run()
