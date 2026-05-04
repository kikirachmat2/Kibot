"""KiKu — KuCoin Scanner | Port 8790 | Weight 0.20"""
import requests
from ki_scanner_base import KiScannerBase

class KiKuScanner(KiScannerBase):
    API = "https://api.kucoin.com/api/v1/market/allTickers"

    def __init__(self):
        super().__init__("KUCOIN", 8790)
        self._prev: dict[str, float] = {}

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            for item in r.json().get("data", {}).get("ticker", []):
                sym = item.get("symbol", "")
                if not sym.endswith("-USDT"): continue
                base = sym.replace("-USDT", "")
                try:
                    price   = float(item.get("last", 0) or 0)
                    vol_u   = float(item.get("volValue", 0) or 0)
                    chg_24h = float(item.get("changeRate", 0) or 0) * 100
                    prev    = self._prev.get(sym, price)
                    chg_1h  = ((price - prev) / prev * 100) if prev > 0 else 0
                    self._prev[sym] = price
                    result[base] = {
                        "price": price, "vol_usdt_24h": vol_u,
                        "change_24h": chg_24h, "change_1h": chg_1h
                    }
                except: continue
        except Exception as e: print(f"[KUCOIN] {e}")
        return result

if __name__ == "__main__": KiKuScanner().run()
