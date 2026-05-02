"""KiBinance — Binance Scanner | Port 8788 | Weight 0.30"""
import requests

from ki_scanner_base import KiScannerBase


class KiBinanceScanner(KiScannerBase):
    API = "https://api.binance.com/api/v3/ticker/24hr"

    def __init__(self):
        super().__init__("BINANCE", 8788)

    def fetch_tickers(self) -> dict:
        result = {}
        try:
            items = requests.get(self.API, timeout=8).json()
            if not isinstance(items, list):
                return result
            for item in items:
                sym = item.get("symbol", "")
                if not sym.endswith("USDT"):
                    continue
                base = sym[:-4]
                try:
                    price = float(item.get("lastPrice", 0) or 0)
                    vol = float(item.get("quoteVolume", 0) or 0)
                    chg = float(item.get("priceChangePercent", 0) or 0)
                    result[base] = {
                        "price": price,
                        "vol_usdt_24h": vol,
                        "change_24h": chg,
                        "change_1h": 0.0,
                    }
                except Exception:
                    continue
        except Exception as e:
            print(f"[BINANCE] {e}")
        return result


if __name__ == "__main__":
    KiBinanceScanner().run()
