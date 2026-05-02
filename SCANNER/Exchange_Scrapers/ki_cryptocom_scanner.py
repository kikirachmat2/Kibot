"""KiCom — Crypto.com Scanner | Port 8789 | Weight 0.15"""
import requests
from ki_scanner_base import KiScannerBase

class KiComScanner(KiScannerBase):
    API = "https://api.crypto.com/v2/public/get-ticker"

    def __init__(self): super().__init__("CRYPTOCOM", 8789)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            items = requests.get(self.API, timeout=8).json().get("result", {}).get("data", [])
            for item in items:
                inst = item.get("i", "")
                if not inst.endswith("_USDT"): continue
                base = inst.replace("_USDT", "")
                try:
                    price = float(item.get("a", 0) or 0)
                    vol_b = float(item.get("v", 0) or 0)
                    chg   = float(item.get("c", 0) or 0) * 100
                    result[base] = {"price": price, "vol_usdt_24h": vol_b * price,
                                    "change_24h": chg, "change_1h": 0.0}
                except: continue
        except Exception as e: print(f"[CRYPTOCOM] {e}")
        return result

if __name__ == "__main__": KiComScanner().run()
