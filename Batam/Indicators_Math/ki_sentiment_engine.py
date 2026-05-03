import time
import json
import os
from pathlib import Path

class SentimentEngine:
    """
    Sovereign Sentiment Engine.
    Analyzes world model data from KiBrain to determine market bias.
    """
    def __init__(self):
        self.root = Path(__file__).resolve().parent.parent
        self.brain_state = self.root / "state/world_model.json"
        self.output_file = self.root / "state/sentiment_pulse.json"
        
    def analyze_brain_data(self):
        """Extracts sentiment from KiBrain's collected headlines."""
        if not self.brain_state.exists():
            return "NEUTRAL", 0.5

        try:
            with open(self.brain_state, "r") as f:
                world = json.load(f)
            
            risk_bias = world.get("market_pulse", {}).get("risk_bias", "MIXED")
            headlines = world.get("market_pulse", {}).get("top_headlines", [])
            
            # Weighted sentiment calculation
            score = 0.5
            if risk_bias == "RISK_ON": score += 0.2
            elif risk_bias == "RISK_OFF": score -= 0.2
            
            # Simple keyword intensity
            pos_keywords = {"bull", "surge", "gain", "growth", "launch", "rally", "moon"}
            neg_keywords = {"bear", "dump", "crash", "loss", "ban", "hack", "risk", "fud"}
            
            hits = 0
            for h in headlines:
                words = set(h.lower().split())
                if words & pos_keywords: hits += 1
                if words & neg_keywords: hits -= 1
            
            score += (hits * 0.05)
            score = max(0.1, min(0.9, score))
            
            bias = "NEUTRAL"
            if score > 0.6: bias = "BULLISH"
            elif score < 0.4: bias = "BEARISH"
            
            return bias, round(score, 2)
        except Exception:
            return "NEUTRAL", 0.5

    def update_pulse(self):
        bias, score = self.analyze_brain_data()
        data = {
            "ts": time.time(),
            "global_bias": bias,
            "fear_greed_index": score,
            "source": "KiBrain-Aggregated",
            "autonomous_active": True
        }
        try:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_file, "w") as f:
                json.dump(data, f)
            print(f"[SENTIMENT] Pulse Updated: {bias} ({score})")
        except Exception as e:
            print(f"[SENTIMENT][ERROR] {e}")

    def run_loop(self):
        print("[SENTIMENT] Sovereign Sentiment Engine Loop Started.")
        while True:
            self.update_pulse()
            time.sleep(120) # Update every 2 mins

if __name__ == "__main__":
    SentimentEngine().run_loop()
