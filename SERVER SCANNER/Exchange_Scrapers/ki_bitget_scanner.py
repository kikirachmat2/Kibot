"""KiBit — Bitget Scanner | Port 8795 | Weight 0.05"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://api.bitget.com/api/v2/spot/market/tickers"

    def __init__(self): super().__init__("BITGET", 8795)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json().get("data", []):
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"): continue
                base = sym[:-4]
                try:
                    price   = float(item.get("lastPr", 0))
                    vol_usdt = float(item.get("usdtVolume", 0))
                    pct_24h = float(item.get("change24h", 0)) * 100
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_usdt,
                        "change_24h": pct_24h, "change_1h": 0
                    }
                except: continue
        except Exception as e: print(f"[BITGET] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
