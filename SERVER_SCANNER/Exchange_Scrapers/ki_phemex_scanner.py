import time
from ki_scanner_base import KiScannerBase

class PhemexScanner(KiScannerBase):
    """Scanner for Phemex (High-speed exchange)."""
    def __init__(self):
        super().__init__("PHEMEX", 8895) # Assign a virtual port
        self.api_url = "https://api.phemex.com/public/md/ticker/24hr/all"

    def fetch_tickers(self) -> dict:
        import requests
        try:
            r = requests.get(self.api_url, timeout=10)
            data = r.json()
            if not data or "result" not in data: return {}
            
            result = {}
            for item in data.get("result", []):
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"): continue
                base = symbol.replace("USDT", "")
                
                result[base] = {
                    "price": float(item.get("last", 0)),
                    "vol_usdt_24h": float(item.get("turnoverEv", 0)) / 1e8,
                    "change_24h": float(item.get("priceChangePercent", 0)) / 100
                }
            return result
        except: return {}

if __name__ == "__main__":
    PhemexScanner().run()
