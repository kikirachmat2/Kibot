"""KiMex — MEXC Scanner | Port 8792 | Weight 0.10 | STRICT threshold"""
import requests
from ki_scanner_base import KiScannerBase

class KiMexScanner(KiScannerBase):
    API = "https://api.mexc.com/api/v3/ticker/24hr"

    def __init__(self): super().__init__("MEXC", 8792)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            items = requests.get(self.API, timeout=10).json()
            if not isinstance(items, list): return result
            for item in items:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"): continue
                base = sym[:-4]
                try:
                    price = float(item.get("lastPrice", 0) or 0)
                    vol   = float(item.get("quoteVolume", 0) or 0)
                    chg   = float(item.get("priceChangePercent", 0) or 0)
                    result[base] = {"price": price, "vol_usdt_24h": vol,
                                    "change_24h": chg, "change_1h": 0.0}
                except: continue
        except Exception as e: print(f"[MEXC] {e}")
        return result

if __name__ == "__main__": KiMexScanner().run()
