import time
from ki_scanner_base import KiScannerBase

class BitmartScanner(KiScannerBase):
    """Scanner for BitMart (Early altcoin listings)."""
    def __init__(self):
        super().__init__("BITMART", 8896)
        self.api_url = "https://api-cloud.bitmart.com/spot/v1/ticker"

    def fetch_tickers(self) -> dict:
        import requests
        try:
            r = requests.get(self.api_url, timeout=10)
            data = r.json()
            if not data or "data" not in data or "tickers" not in data["data"]: return {}
            
            result = {}
            for item in data["data"]["tickers"]:
                symbol = item.get("symbol", "")
                if not symbol.endswith("_USDT"): continue
                base = symbol.replace("_USDT", "")
                
                result[base] = {
                    "price": float(item.get("last_price", 0)),
                    "vol_usdt_24h": float(item.get("base_volume_24h", 0)),
                    "change_24h": float(item.get("fluctuation", 0)) * 100
                }
            return result
        except: return {}

if __name__ == "__main__":
    BitmartScanner().run()
