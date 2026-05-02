"""KiBit — Bybit Scanner | Port 8791 | Weight 0.25"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://api.bybit.com/v5/market/tickers"

    def __init__(self): super().__init__("BYBIT", 8791)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, params={"category": "spot"}, timeout=8)
            for item in r.json().get("result", {}).get("list", []):
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"): continue
                base = sym[:-4]
                try:
                    price   = float(item.get("lastPrice", 0))
                    vol_b   = float(item.get("volume24h", 0))
                    pct_24h = float(item.get("price24hPcnt", 0)) * 100
                    prev_1h = float(item.get("prevPrice1h", price) or price)
                    chg_1h  = ((price - prev_1h) / prev_1h * 100) if prev_1h > 0 else 0
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_b * price,
                        "change_24h": pct_24h, "change_1h": chg_1h
                    }
                except: continue
        except Exception as e: print(f"[BYBIT] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
