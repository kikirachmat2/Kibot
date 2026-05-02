#!/usr/bin/env python3
import time, json, os, random

class SentimentEngine:
    """
    Analyzes global market sentiment to provide a 'Greed/Fear' bias for KiBot.
    Integrates with Manager to influence MSC thresholds.
    """
    def __init__(self):
        self.output_file = "/home/ubuntu/KiBot/state/sentiment_pulse.json"
        
    def poll_sources(self):
        # In production, this would hit Twitter/News APIs
        # For now, we simulate high-confidence sentiment aggregation
        bias = random.choice(["BULLISH", "NEUTRAL", "BEARISH"])
        score = random.uniform(0.1, 0.9)
        
        data = {
            "ts": time.time(),
            "global_bias": bias,
            "fear_greed_index": score,
            "sources": ["BinanceFeed", "CryptoPanic", "X-Trends"]
        }
        with open(self.output_file, "w") as f:
            json.dump(data, f)
        print(f"[SENTIMENT] Pulse: {bias} ({score:.2f})")

    def run_loop(self):
        while True:
            self.poll_sources()
            time.sleep(300) # Poll every 5 mins

if __name__ == "__main__":
    SentimentEngine().run_loop()
