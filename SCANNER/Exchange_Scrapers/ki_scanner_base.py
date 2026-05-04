"""
KiBot Trinity — Base Scanner Class (Lobotomized Version)
Semua scanner global extend class ini.
Filosofi: Hanya sebagai "Mata" (Sensory Node). Tidak ada filter otonom.
Data dikirim secara RAW ke Batam Control Plane.
"""
import json, time, socket, os, requests, asyncio, aiohttp
from typing import Optional, Any
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

MANAGER_HOST = os.environ.get("KIBOT_MANAGER_HOST", "168.110.201.228")
MANAGER_UDP_PORT = int(os.environ.get("KIBOT_UDP_PORT", "9999"))
# Default 5 detik agar lebih real-time dibandingkan 30 detik sebelumnya
SCAN_INTERVAL_S = int(os.environ.get("SCAN_INTERVAL_S", "5"))
RUNTIME_ROOT = Path(os.environ.get("KIBOT_RUNTIME_ROOT", str(Path(__file__).resolve().parent.parent)))

# Cache Indodax Pairs
_indodax_pairs_cache: dict[str, str] = {}
_indodax_cache_ttl = 0

def fetch_indodax_pairs() -> dict[str, str]:
    global _indodax_pairs_cache, _indodax_cache_ttl
    if time.time() < _indodax_cache_ttl and _indodax_pairs_cache:
        return _indodax_pairs_cache
    try:
        r = requests.get("https://indodax.com/api/pairs", timeout=10)
        pairs = r.json()
        result = {p.get("traded_currency", "").upper(): p.get("ticker_id", "") for p in pairs if p.get("base_currency") == "idr" or p.get("quote_currency") == "idr"}
        _indodax_pairs_cache = result
        _indodax_cache_ttl = time.time() + 3600
        return result
    except Exception as e:
        return _indodax_pairs_cache

class KiScannerBase(ABC):
    def __init__(self, exchange_name: str, port: int):
        self.exchange = exchange_name.upper()
        self.port = port
        self.scan_interval = SCAN_INTERVAL_S
        self._indodax_pairs = fetch_indodax_pairs()
        print(f"[{self.exchange}] Sensory Node initialized. Reporting to Batam: {MANAGER_HOST}")

    @abstractmethod
    def fetch_tickers(self) -> dict:
        """Return: {symbol: {price, vol_usdt_24h, change_24h, change_1h}}"""
        pass

    def symbol_to_indodax(self, base_symbol: str) -> str | None:
        if time.time() >= _indodax_cache_ttl:
            self._indodax_pairs = fetch_indodax_pairs()
        return self._indodax_pairs.get(base_symbol.upper())

    def process_ticker(self, base_symbol: str, data: dict):
        """
        No filtering here. If it's on Indodax, Batam wants to know.
        """
        pair = self.symbol_to_indodax(base_symbol)
        if not pair:
            return

        # Prepare Raw Sensory Data
        raw_signal = {
            "exchange": self.exchange,
            "base_symbol": base_symbol.upper(),
            "pair_indodax": pair,
            "price_usdt": data.get("price", 0),
            "vol_usdt_24h": data.get("vol_usdt_24h", 0),
            "change_24h": round(data.get("change_24h", 0), 3),
            "change_1h": round(data.get("change_1h", 0), 3),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "is_raw": True
        }
        self.send_signal(raw_signal)

    def send_signal(self, signal: dict):
        try:
            msg = {
                "type": "SENSORY_DATA_STREAM", 
                "node": self.exchange,
                **signal
            }
            msg["sentAtEpochMs"] = int(time.time() * 1000)
            
            # HMAC Signing for security
            key = os.environ.get("KIBOT_SIGNAL_KEY", "SOVEREIGN_DEFAULT_SIGNAL_SECRET").encode()
            canonical_payload = json.dumps(msg, separators=(',', ':'), sort_keys=True)
            import hmac, hashlib, base64
            signature = hmac.new(key, canonical_payload.encode(), hashlib.sha256).digest()
            msg["signature"] = base64.b64encode(signature).decode()
            
            payload = json.dumps(msg).encode()
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(payload, (MANAGER_HOST, MANAGER_UDP_PORT))
        except Exception as e:
            print(f"[{self.exchange}] UDP send err: {e}")

    def run(self):
        print(f"[{self.exchange}] Scanning...")
        while True:
            try:
                t0 = time.time()
                tickers = self.fetch_tickers()
                for base_sym, data in tickers.items():
                    self.process_ticker(base_sym, data)
                
                elapsed = time.time() - t0
                time.sleep(max(0.1, self.scan_interval - elapsed))
            except Exception as e:
                print(f"[{self.exchange}] Runtime Err: {e}")
                time.sleep(5)

class KiScannerBaseAsync(KiScannerBase):
    async def run_async(self):
        print(f"[{self.exchange}] Async Sensory Node active.")
        while True:
            try:
                await self.handle_async_logic()
            except Exception as e:
                print(f"[{self.exchange}] Async Err: {e}")
                await asyncio.sleep(5)

    @abstractmethod
    async def handle_async_logic(self):
        pass
