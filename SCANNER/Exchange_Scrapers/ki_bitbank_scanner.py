"""KiBit — Bitbank Scanner | Port 8799 | Weight 0.05"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://public.bitbank.cc/tickers"

    def __init__(self): super().__init__("BITBANK", 8799)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json().get("data", []):
                pair = item.get("pair", "")
                if not pair.endswith("_jpy"): continue
                base = pair.split("_")[0].upper()
                try:
                    price_jpy = float(item.get("last", 0))
                    # Normalization to USDT (Approx 150 JPY/USD)
                    price_usdt = price_jpy / 150.0
                    vol_jpy = float(item.get("vol", 0)) * price_jpy
                    # Bitbank ticker doesn't give 24h change directly in this endpoint easily,
                    # we estimate or set to 0 to be filled by history
                    result[base] = {
                        "price": price_usdt, "vol_usdt_24h": vol_jpy / 150.0,
                        "change_24h": 0, "change_1h": 0
                    }
                except: continue
        except Exception as e: print(f"[BITBANK] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
