import json
import time
import os
import httpx
import asyncio
from datetime import datetime
from pathlib import Path
from threading import Thread

class WhatIfTracker:
    """
    Sovereign What-If Tracker
    Tracks signals that were rejected by the Fast Path (Vetoed or Math-Skipped).
    Calculates hypothetical PnL over time to determine if rejections were 'correct' or 'missed opportunities'.
    """
    def __init__(self, tracking_file=None):
        base_dir = Path(__file__).resolve().parent.parent
        self.tracking_file = Path(tracking_file) if tracking_file else base_dir / "Logs" / "what_if_analysis.json"
        self.tracking_file.parent.mkdir(parents=True, exist_ok=True)
        self.active_tracks = self._load()
        self.running = False

    def _load(self):
        if self.tracking_file.exists():
            try:
                with open(self.tracking_file, "r") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except Exception as e:
                print(f"ERROR [WhatIfTracker]: Failed to load tracking file: {e}")
                return {}
        return {}

    def _save(self):
        try:
            # Atomic-ish save
            tmp_file = f"{self.tracking_file}.tmp"
            with open(tmp_file, "w") as f:
                json.dump(self.active_tracks, f, indent=2)
            os.replace(tmp_file, self.tracking_file)
        except Exception as e:
            print(f"ERROR [WhatIfTracker]: Failed to save tracks: {e}")

    def track_rejection(self, symbol, entry_price, reason):
        """
        Adds a rejected signal to the tracking list.
        """
        # Unique ID for this specific rejection instance
        track_id = f"{symbol}_{int(time.time())}"
        
        self.active_tracks[track_id] = {
            "symbol": symbol,
            "entry_price": float(entry_price),
            "entry_timestamp": time.time(),
            "entry_time_human": datetime.now().isoformat(),
            "reason": reason,
            "current_price": float(entry_price),
            "max_gain_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "status": "TRACKING",
            "last_update": time.time()
        }
        self._save()

    async def update_prices(self):
        """
        Fetches current prices for all active tracks and updates their performance metrics.
        """
        active_ids = [tid for tid, data in self.active_tracks.items() if data["status"] == "TRACKING"]
        if not active_ids:
            return

        try:
            # Fetch from Indodax Summary API (contains all tickers)
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://indodax.com/api/summaries", timeout=15)
                if resp.status_code != 200:
                    return
                
                data = resp.json()
                tickers = data.get("tickers", {})
                
                for tid in active_ids:
                    track = self.active_tracks[tid]
                    # Indodax uses symbol_idr format (e.g. btc_idr)
                    # Input symbol might be BTC-IDR or BTC_IDR
                    sym_key = track["symbol"].lower().replace("-", "_")
                    ticker = tickers.get(sym_key)
                    
                    if not ticker:
                        continue
                        
                    current_price = float(ticker.get("last", 0))
                    if current_price <= 0:
                        continue
                        
                    track["current_price"] = current_price
                    track["last_update"] = time.time()
                    
                    # Calculate PnL
                    pnl_pct = (current_price - track["entry_price"]) / track["entry_price"] * 100
                    track["max_gain_pct"] = max(track["max_gain_pct"], pnl_pct)
                    track["max_drawdown_pct"] = min(track["max_drawdown_pct"], pnl_pct)
                    
                    # Auto-expire tracking after 12 hours (Sovereign Fast Path focus)
                    if time.time() - track["entry_timestamp"] > 43200:
                        track["status"] = "COMPLETED"
                        
                self._save()
        except Exception as e:
            print(f"ERROR [WhatIfTracker]: Update prices failed: {e}")

    def start_background_loop(self, interval_sec=300):
        """
        Starts the background thread to periodically update prices.
        """
        if self.running: return
        self.running = True
        
        def _loop():
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            while self.running:
                try:
                    loop.run_until_complete(self.update_prices())
                except Exception as e:
                    print(f"ERROR [WhatIfTracker]: Loop execution error: {e}")
                time.sleep(interval_sec)
                
        thread = Thread(target=_loop, name="kibot-whatif-tracker", daemon=True)
        thread.start()

if __name__ == "__main__":
    # Quick Test
    tracker = WhatIfTracker()
    tracker.track_rejection("BTC-IDR", 1000000000, "Vetoed: Too Volatile")
    print("Test track added. Running price update...")
    asyncio.run(tracker.update_prices())
    print("Done.")
