"""KiBit — Upbit Scanner | Port 8796 | Weight 0.10"""
import requests
from ki_scanner_base import KiScannerBase

class KiBitScanner(KiScannerBase):
    API_PAIRS = "https://api.upbit.com/v1/market/all"
    API_TICKER = "https://api.upbit.com/v1/ticker"

    def __init__(self): super().__init__("UPBIT", 8796)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            # Upbit needs a list of markets to fetch tickers
            # We filter for KRW markets as they drive Indodax
            markets_r = requests.get(self.API_PAIRS, timeout=8)
            krw_markets = [m['market'] for m in markets_r.json() if m['market'].startswith("KRW-")]
            
            # Fetch in chunks of 50
            for i in range(0, len(krw_markets), 50):
                chunk = krw_markets[i:i+50]
                r = requests.get(self.API_TICKER, params={"markets": ",".join(chunk)}, timeout=8)
                for item in r.json():
                    sym = item.get("market", "")
                    base = sym.split("-")[1]
                    try:
                        price_krw = float(item.get("trade_price", 0))
                        # Approx conversion to USDT for volume normalization
                        price_usdt = price_krw / 1350.0 
                        vol_krw = float(item.get("acc_trade_price_24h", 0))
                        pct_24h = float(item.get("signed_change_rate", 0)) * 100
                        result[base] = {
                            "price": price_usdt, "vol_usdt_24h": vol_krw / 1350.0,
                            "change_24h": pct_24h, "change_1h": 0
                        }
                    except: continue
        except Exception as e: print(f"[UPBIT] {e}")
        return result

if __name__ == "__main__": KiBitScanner().run()
