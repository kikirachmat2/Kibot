"""KiBit — HTX Scanner | Port 8794 | Weight 0.10"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://api.huobi.pro/market/tickers"

    def __init__(self): super().__init__("HTX", 8794)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json().get("data", []):
                sym = item.get("symbol", "")
                if not sym.endswith("usdt"): continue
                base = sym[:-4].upper()
                try:
                    price   = float(item.get("close", 0))
                    vol_usdt = float(item.get("vol", 0))
                    # HTX doesn't give direct 24h change in /tickers, we'd need another endpoint
                    # but we can at least provide price and vol for MSC
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_usdt,
                        "change_24h": 0, "change_1h": 0
                    }
                except: continue
        except Exception as e: print(f"[HTX] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
