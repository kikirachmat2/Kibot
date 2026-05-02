#!/usr/bin/env python3
"""
KiBot AI World Scout
====================
Proactive intelligence agent that searches the world every 5 minutes.
Synthesizes market catalysts, security threats, and trending narratives.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, List, Any

# Path resolution
ROOT_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT_DIR / "state"
WORLD_MODEL_FILE = STATE_DIR / "world_model.json"

# Lazy imports to avoid circular dependency
def get_ai_search():
    from kibot_ai_search import AISearchService
    return AISearchService()

def get_ai_coordinator():
    import kibot_ai_coordinator
    return kibot_ai_coordinator

class WorldScout:
    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.search_service = get_ai_search()
        self.coordinator = get_ai_coordinator()

    def _log(self, msg: str):
        print(f"[SCOUT][{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

    def perform_scouting(self):
        self._log("Initiating global scouting mission...")
        
        # 1. Gather Raw Data from multiple sources
        scouting_data = {
            "security_threats": self.search_service.ddg_search("crypto protocol exploit hack vulnerability latest", max_results=3),
            "market_catalysts": self.search_service.tavily_search("top crypto market catalysts today bitcoin eth regulation", search_depth="advanced") or self.search_service.jina_search("top crypto market catalysts today"),
            "trending_narratives": self.search_service.gdelt_news("crypto trending AI meme RWA layer2"),
            "news_pulse": (self.search_service.finnhub_news("crypto") or [])[:5]
        }

        # 2. Synthesize using Cloud AI (Non-Ollama preferred for global context)
        self._log("Synthesizing intelligence using Cloud AI...")
        
        prompt_context = {
            "raw_data": scouting_data,
            "current_time": time.ctime()
        }
        
        # We use a specific prompt type for intelligence synthesis
        analysis = self.coordinator.query_ai(
            prompt_type="INTELLIGENCE_SYNTHESIS",
            context=prompt_context,
            cache_ttl_minutes=4 # Always fresh
        )

        if analysis:
            self._log("Intelligence synthesis complete.")
            # 3. Update World Model
            try:
                world_model = {}
                if WORLD_MODEL_FILE.exists():
                    world_model = json.loads(WORLD_MODEL_FILE.read_text(encoding="utf-8"))
                
                world_model.update({
                    "last_updated": time.time(),
                    "last_updated_str": time.ctime(),
                    "intelligence": analysis,
                    "raw_summary_length": len(str(scouting_data))
                })
                
                WORLD_MODEL_FILE.write_text(json.dumps(world_model, indent=2), encoding="utf-8")
                self._log("World Model updated successfully.")
            except Exception as e:
                self._log(f"Failed to save World Model: {e}")
        else:
            self._log("[WARN] Intelligence synthesis failed (no AI response).")

    def perform_targeted_scouting(self, pair: str):
        self._log(f"Initiating URGENT targeted scouting for {pair}...")
        
        # 1. Gather Targeted Data
        symbol = pair.split("_")[0]
        scouting_data = {
            "pair": pair,
            "specific_catalyst": self.search_service.tavily_search(f"latest news catalyst pump reason for {symbol} crypto {pair}", search_depth="advanced") or self.search_service.jina_search(f"latest news catalyst for {symbol}"),
            "social_pulse": self.search_service.serper_search(f"{symbol} crypto price pump news twitter reddit") or self.search_service.jina_search(f"{symbol} crypto social trending news"),
            "news_pulse": (self.search_service.finnhub_news(symbol) or [])[:3]
        }

        # 2. Validate using AI
        self._log(f"Validating {pair} anomaly using AI...")
        prompt_context = {
            "pair": pair,
            "raw_data": scouting_data,
            "current_time": time.ctime()
        }
        
        validation = self.coordinator.query_ai(
            prompt_type="TARGETED_VALIDATION",
            context=prompt_context,
            cache_ttl_minutes=1 # Instant validation, no cache
        )

        if validation:
            self._log(f"Targeted validation for {pair} complete: {validation.get('verdict')}")
            # 3. Update World Model with Urgent Alert
            try:
                world_model = {}
                if WORLD_MODEL_FILE.exists():
                    world_model = json.loads(WORLD_MODEL_FILE.read_text(encoding="utf-8"))
                
                if "urgent_alerts" not in world_model:
                    world_model["urgent_alerts"] = []
                
                world_model["urgent_alerts"].insert(0, {
                    "at": time.time(),
                    "pair": pair,
                    "validation": validation
                })
                # Keep only last 5 urgent alerts
                world_model["urgent_alerts"] = world_model["urgent_alerts"][:5]
                world_model["last_updated"] = time.time()
                
                WORLD_MODEL_FILE.write_text(json.dumps(world_model, indent=2), encoding="utf-8")
                self._log(f"World Model updated with urgent alert for {pair}.")
            except Exception as e:
                self._log(f"Failed to update World Model with urgent alert: {e}")
        else:
            self._log(f"[WARN] Targeted validation for {pair} failed (no AI response).")

if __name__ == "__main__":
    print("[SCOUT] Starting World Scout service with Fast-Poll (5s) for urgent requests...", flush=True)
    scout = WorldScout()
    last_global_scout = 0
    
    while True:
        now = time.time()
        
        # 1. Check for Urgent Targeted Scouting
        urgent_file = STATE_DIR / "urgent_scout.json"
        if urgent_file.exists():
            try:
                data = json.loads(urgent_file.read_text(encoding="utf-8"))
                pair = data.get("pair")
                if pair:
                    scout.perform_targeted_scouting(pair)
                urgent_file.unlink() # Delete after processing
            except Exception as e:
                scout._log(f"[ERROR] Urgent scouting processing failed: {e}")

        # 2. Global Scouting every 5 minutes (300s)
        if (now - last_global_scout) >= 300:
            try:
                scout.perform_scouting()
                last_global_scout = now
            except Exception as e:
                scout._log(f"[ERROR] Global scouting failed: {e}")
        
        time.sleep(5) # Fast poll interval
