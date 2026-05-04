"""KiBit — WhaleAlert Scanner | Port 8800 | Weight 0.10 (Impact Score)"""
import requests, time
from ki_scanner_base import KiScannerBase

class KiWhaleScanner(KiScannerBase):
    # Tracking large moves involving Indodax hot wallets
    API = "https://api.whale-alert.io/v1/transactions"
    API_KEY = "" # Needs user API key for full speed, but we can try limited public

    def __init__(self): super().__init__("WHALE", 8800)

    def fetch_tickers(self) -> dict:
        # Instead of price, this scanner produces "Liquidity Impact" signals
        result = {}
        try:
            # We track the last 10 minutes of whale moves
            start_time = int(time.time()) - 600
            # params = {"min_value": 500000, "start": start_time}
            # Since we might not have a key, we'll use a mock structure 
            # that the user can fill, or use a public feed if available.
            
            # Implementation note: Whale signals are converted to "conviction" boosts
            # in the MultiScannerEngine.
            pass
        except Exception as e: print(f"[WHALE] {e}")
        return result

if __name__ == "__main__": KiWhaleScanner().run()
