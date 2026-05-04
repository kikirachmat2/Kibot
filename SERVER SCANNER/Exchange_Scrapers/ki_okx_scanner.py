"""KiBit — OKX Scanner | Port 8792 | Weight 0.15"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://www.okx.com/api/v5/market/tickers?instType=SPOT"

    def __init__(self): super().__init__("OKX", 8792)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json().get("data", []):
                instId = item.get("instId", "")
                if not instId.endswith("-USDT"): continue
                base = instId.split("-")[0]
                try:
                    price   = float(item.get("last", 0))
                    vol_usdt = float(item.get("vol24h", 0)) * price # OKX vol is in base
                    # OKX gives open24h, we calculate change
                    open_24h = float(item.get("open24h", price))
                    pct_24h = ((price - open_24h) / open_24h * 100) if open_24h > 0 else 0
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_usdt,
                        "change_24h": pct_24h, "change_1h": 0 # OKX v5 doesn't give 1h in simple ticker
                    }
                except: continue
        except Exception as e: print(f"[OKX] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
