"""KiBit — Gate.io Scanner | Port 8793 | Weight 0.10"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://api.gateio.ws/api/v4/spot/tickers"

    def __init__(self): super().__init__("GATE", 8793)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json():
                curr_pair = item.get("currency_pair", "")
                if not curr_pair.endswith("_USDT"): continue
                base = curr_pair.split("_")[0]
                try:
                    price   = float(item.get("last", 0))
                    vol_usdt = float(item.get("quote_volume", 0))
                    pct_24h = float(item.get("change_percentage", 0))
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_usdt,
                        "change_24h": pct_24h, "change_1h": 0
                    }
                except: continue
        except Exception as e: print(f"[GATE] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
