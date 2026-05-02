#!/usr/bin/env python3
"""
KiBot Local Conviction Scanner (v7.3.1)
======================================
Focus: Indodax-only signal detection using mathematical conviction.
Philosophy: "Don't trust, verify locally."

Metrics:
1. Volume Anomaly (24h Avg vs. 15m Burst)
2. Orderbook Imbalance (Weighted Bid/Ask ratio)
3. Spread Tightness
4. Mid-price Momentum
"""

import os
import json
import time
import logging
import urllib.request
from typing import Dict, List, Optional

# Constants
API_BASE = "https://indodax.com/api"
CONVICTION_THRESHOLD = 0.85
STAGNANCY_MIN_VOLUME = 50_000_000  # 50M IDR 24h min volume to care

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("kicryp_signal")

class LocalConvictionScanner:
    def __init__(self):
        self.last_depths = {}
        self.last_tickers = {}

    def fetch_tickers(self) -> Dict:
        try:
            with urllib.request.urlopen(f"{API_BASE}/tickers") as resp:
                data = json.loads(resp.read().decode())
                return data.get("tickers", {})
        except Exception as e:
            logger.error(f"Ticker fetch failed: {e}")
            return {}

    def fetch_depth(self, pair: str) -> Dict:
        try:
            with urllib.request.urlopen(f"{API_BASE}/{pair}/depth") as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.error(f"Depth fetch failed for {pair}: {e}")
            return {}

    def calculate_imbalance(self, depth: Dict) -> float:
        bids = depth.get("buy", [])[:10]  # Top 10 bids
        asks = depth.get("sell", [])[:10] # Top 10 asks
        
        bid_vol = sum(float(b[0]) * float(b[1]) for b in bids)
        ask_vol = sum(float(a[0]) * float(a[1]) for a in asks)
        
        if bid_vol + ask_vol == 0: return 0.5
        return bid_vol / (bid_vol + ask_vol)

    def scan(self):
        logger.info("Starting conviction scan...")
        tickers = self.fetch_tickers()
        signals = []

        for pair, data in tickers.items():
            vol_24h = float(data.get("vol_idr", 0))
            if vol_24h < STAGNANCY_MIN_VOLUME: continue

            last_price = float(data.get("last", 0))
            buy_price = float(data.get("buy", 0))
            sell_price = float(data.get("sell", 0))
            spread = (sell_price - buy_price) / buy_price if buy_price > 0 else 1.0

            # 1. Price Momentum (simple 24h change)
            # Low priority, we want burst markers
            
            # 2. Depth Analysis (The "Math" part)
            depth = self.fetch_depth(pair)
            imbalance = self.calculate_imbalance(depth)
            
            # Conviction calculation
            # Weights: Imbalance (60%), Spread (30%), Volume Rank (10%)
            conviction = (imbalance * 0.6) + ((1.0 - min(spread * 10, 1.0)) * 0.3) + (min(vol_24h / 1_000_000_000, 1.0) * 0.1)
            
            if conviction >= CONVICTION_THRESHOLD:
                signal = {
                    "pair": pair,
                    "price": last_price,
                    "conviction": round(conviction, 3),
                    "imbalance": round(imbalance, 3),
                    "spread_pct": round(spread * 100, 3),
                    "timestamp": int(time.time() * 1000)
                }
                signals.append(signal)
                logger.info(f"High Conviction Detected: {pair} @ {last_price} Score: {conviction:.3f}")

        return signals

if __name__ == "__main__":
    scanner = LocalConvictionScanner()
    while True:
        results = scanner.scan()
        if results:
            # Placeholder for Supabase push
            logger.info(f"Found {len(results)} opportunities.")
        time.sleep(60) # Scan every minute
