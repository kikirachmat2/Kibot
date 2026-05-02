"""KiBit — LBank Scanner | Port 8797 | Weight 0.05"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://api.lbank.info/v2/ticker.do?symbol=all"

    def __init__(self): super().__init__("LBANK", 8797)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json().get("data", []):
                sym = item.get("symbol", "")
                if not sym.endswith("_usdt"): continue
                base = sym.split("_")[0].upper()
                try:
                    price   = float(item.get("ticker", {}).get("latest", 0))
                    vol_usdt = float(item.get("ticker", {}).get("turnover", 0))
                    pct_24h = float(item.get("ticker", {}).get("change", 0))
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_usdt,
                        "change_24h": pct_24h, "change_1h": 0
                    }
                except: continue
        except Exception as e: print(f"[LBANK] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
