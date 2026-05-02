"""KiBit — Bithumb Scanner | Port 8798 | Weight 0.08"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API = "https://api.bithumb.com/public/ticker/ALL_KRW"

    def __init__(self): super().__init__("BITHUMB", 8798)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            r = requests.get(self.API, timeout=8)
            data = r.json().get("data", {})
            for sym, item in data.items():
                if sym == "date": continue
                try:
                    price_krw = float(item.get("closing_price", 0))
                    # Normalization to USDT
                    price_usdt = price_krw / 1350.0
                    vol_krw = float(item.get("acc_trade_value_24H", 0))
                    # pct_24h calculation (Bithumb provides 24h fluctuate rate)
                    pct_24h = float(item.get("fluctate_rate_24H", 0))
                    result[sym] = {
                        "price": price_usdt, "vol_usdt_24h": vol_krw / 1350.0,
                        "change_24h": pct_24h, "change_1h": 0
                    }
                except: continue
        except Exception as e: print(f"[BITHUMB] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
