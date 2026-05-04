import os
import time
import json
import httpx
import logging
from Support.ki_storage import atomic_save, atomic_load

# Configuration
MARKET_DATA_PATH = "/home/ubuntu/KiBot/state/market_intelligence.json"
SCANNER_URL = "http://localhost:5000/api/top_movers" # Asumsi scanner jalan di port 5000

logging.basicConfig(level=logging.INFO, format='%(asctime)s - ORACLE - %(message)s')

async def update_market_intelligence():
    """Mengambil data market terbaru dan merangkumnya untuk AI."""
    while True:
        try:
            # 1. Ambil data dari Scanner
            async with httpx.AsyncClient() as client:
                # Simulasi ambil data (Nanti hubungkan ke API Scanner riil)
                market_summary = {
                    "top_gainers": ["BTC/IDR (+2.5%)", "ETH/IDR (+1.8%)", "PEPE/IDR (+15.2%)"],
                    "unusual_volume": ["DOGE/IDR (3x Avg)", "SHIB/IDR (2x Avg)"],
                    "market_sentiment": "BULLISH",
                    "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                
                # 2. Simpan secara Atomic
                atomic_save(market_summary, MARKET_DATA_PATH)
                logging.info("Market Intelligence Updated for AI.")
                
        except Exception as e:
            logging.error(f"Oracle Sync Error: {e}")
        
        await asyncio.sleep(60) # Update setiap menit

if __name__ == "__main__":
    import asyncio
    asyncio.run(update_market_intelligence())
