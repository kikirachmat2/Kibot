#!/usr/bin/env python3
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

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
import asyncio
from Core.circuit_breaker import CircuitBreaker

from Core.Support.ki_config import STATE_DIR
from Core.Intelligence.defi_metrics_fetcher import DeFiMetricsFetcher

WORLD_MODEL_FILE = STATE_DIR / "world_model.json"
AI_TRACE_FILE = STATE_DIR / "ai_decision_trace.json"

# Lazy imports to avoid circular dependency
def get_ai_search():
    from Core.Intelligence.kibot_ai_search import AISearchService
    return AISearchService()

def get_ai_coordinator():
    from Core.Intelligence import kibot_ai_coordinator
    return kibot_ai_coordinator

def _load_daily_state() -> Dict[str, Any]:
    try:
        from Core.sovereign_state import load_strategy
        strategy = load_strategy()
        daily_state = strategy.get("daily_state", {})
        return daily_state if isinstance(daily_state, dict) else {}
    except Exception:
        return {}

class WorldScout:
    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.search_service = get_ai_search()
        self.coordinator = get_ai_coordinator()
        self.defi_fetcher = DeFiMetricsFetcher()
        self.breaker = CircuitBreaker("WORLD_SCOUT", max_failures=3, reset_after_sec=600)

    def _log(self, msg: str):
        print(f"[SCOUT][{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

    def _write_ai_trace(self, *, best_action: str = "WAIT", venue: str = "indodax", reason: str = "heartbeat", confidence: float = 0.0, risk_status: str = "UNKNOWN", next_check_seconds: int = 60, market_summary: str = ""):
        try:
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "objective": "maximize_risk_adjusted_profit_for_boss",
                "market_summary": market_summary,
                "best_action": best_action,
                "venue": venue,
                "reason": reason,
                "confidence": float(confidence),
                "risk_status": risk_status,
                "next_check_seconds": int(next_check_seconds),
            }
            AI_TRACE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log(f"[WARN] Failed to write ai_decision_trace heartbeat: {exc}")

    async def perform_scouting(self):
        self._log("Initiating global scouting mission...")
        
        # 1. Gather Raw Data from multiple sources
        scouting_data = {
            "defi_intelligence": await self.defi_fetcher.get_aggregated_defi_intelligence(),
            "security_threats": await self.search_service.ddg_search_async("crypto protocol exploit hack vulnerability latest", max_results=3),
            "market_catalysts": await self.search_service.tavily_search_async("top crypto market catalysts today bitcoin eth regulation", search_depth="advanced") or await self.search_service.jina_search_async("top crypto market catalysts today"),
            "trending_narratives": await self.search_service.gdelt_news_async("crypto trending AI meme RWA layer2"),
            "news_pulse": (await self.search_service.finnhub_news_async("crypto") or [])[:5],
            "indodax_intel": await self.search_service.get_market_consensus_async("Indodax latest listing rumors IDR premium"),
            "polymarket_intel": await self.search_service.get_market_consensus_async("Polymarket trending events crypto prediction odds")
        }

        # 2. Synthesize using Cloud AI (Non-Ollama preferred for global context)
        self._log("Synthesizing global intelligence...")
        daily_state = _load_daily_state()
        
        prompt_context = {
            "raw_data": scouting_data,
            "current_time": time.ctime(),
            "daily_state": daily_state,
        }

        self._write_ai_trace(
            best_action="WAIT",
            venue="indodax",
            reason="scouting_heartbeat",
            confidence=0.05,
            risk_status="SCOUTING",
            next_check_seconds=60,
            market_summary="global scouting in progress",
        )
        
        # We use a specific prompt type for intelligence synthesis
        analysis = await self.coordinator.query_ai(
            prompt_type="INTELLIGENCE_SYNTHESIS",
            context=prompt_context,
            cache_ttl_minutes=4 # Always fresh
        )

        # 2b. Specialized Possibility Mining (Using Multi-Agent Debate for higher confidence)
        self._log("Mining for high-performance possibilities (Indodax & Polymarket) using AI Debate...")
        possibilities = await self.coordinator.query_ai_debate(
            prompt_type="POSSIBILITY_MINING",
            context=prompt_context,
            debate_rounds=1
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
                    "possibility_matrix": possibilities.get("possibilities", []) if possibilities else [],
                    "raw_summary_length": len(str(scouting_data))
                })
                
                WORLD_MODEL_FILE.write_text(json.dumps(world_model, indent=2), encoding="utf-8")
                self._log("World Model updated successfully with Possibility Matrix.")
                summary_text = ""
                try:
                    summary_text = str((analysis or {}).get("market_summary") or (analysis or {}).get("summary") or "")
                except Exception:
                    summary_text = ""
                self._write_ai_trace(
                    best_action=str((analysis or {}).get("best_action") or "WAIT"),
                    venue=str((analysis or {}).get("venue") or "indodax"),
                    reason=str((analysis or {}).get("reason") or "analysis_update"),
                    confidence=float((analysis or {}).get("confidence") or 0.0),
                    risk_status=str((analysis or {}).get("risk_status") or "UNKNOWN"),
                    next_check_seconds=int((analysis or {}).get("next_check_seconds") or 60),
                    market_summary=summary_text,
                )
                self.breaker.record_success()
            except Exception as e:
                self._log(f"Failed to save World Model: {e}")
                self.breaker.record_failure()
        else:
            self._log("[WARN] Intelligence synthesis failed (no AI response).")
            self._write_ai_trace(
                best_action="WAIT",
                venue="indodax",
                reason="analysis_unavailable",
                confidence=0.0,
                risk_status="UNKNOWN",
                next_check_seconds=60,
                market_summary="analysis unavailable",
            )
            if self.breaker.record_failure() == "ESCALATE":
                self._log("[CRITICAL] Scout circuit opened. Escalating to Council/Human.")

    async def perform_targeted_scouting(self, pair: str):
        self._log(f"Initiating URGENT targeted scouting for {pair}...")
        
        # 1. Gather Targeted Data
        symbol = pair.split("_")[0]
        scouting_data = {
            "pair": pair,
            "specific_catalyst": await self.search_service.tavily_search_async(f"latest news catalyst pump reason for {symbol} crypto {pair}", search_depth="advanced") or await self.search_service.jina_search_async(f"latest news catalyst for {symbol}"),
            "social_pulse": await self.search_service.serper_search_async(f"{symbol} crypto price pump news twitter reddit") or await self.search_service.jina_search_async(f"{symbol} crypto social trending news"),
            "news_pulse": (await self.search_service.finnhub_news_async(symbol) or [])[:3]
        }

        # 2. Validate using AI
        self._log(f"Validating {pair} anomaly using AI...")
        daily_state = _load_daily_state()
        prompt_context = {
            "pair": pair,
            "raw_data": scouting_data,
            "current_time": time.ctime(),
            "daily_state": daily_state,
        }
        
        validation = await self.coordinator.query_ai(
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

async def run_scout_loop():
    print("[SCOUT] Starting World Scout service with Fast-Poll (5s) for urgent requests...", flush=True)
    scout = WorldScout()
    last_global_scout = 0
    last_trace_heartbeat = 0.0
    
    while True:
        now = time.time()
        
        # 1. Check for Urgent Targeted Scouting
        urgent_file = STATE_DIR / "urgent_scout.json"
        if urgent_file.exists():
            try:
                data = json.loads(urgent_file.read_text(encoding="utf-8"))
                pair = data.get("pair")
                if pair:
                    await scout.perform_targeted_scouting(pair)
                urgent_file.unlink() # Delete after processing
            except Exception as e:
                scout._log(f"[ERROR] Urgent scouting processing failed: {e}")

        # 2. Global Scouting every 5 minutes (300s)
        if (now - last_global_scout) >= 300:
            try:
                await scout.perform_scouting()
                last_global_scout = now
            except Exception as e:
                import traceback
                scout._log(f"[ERROR] Global scouting failed: {e}\n{traceback.format_exc()}")

        # 3. AI decision heartbeat every 60s so healthchecks see a fresh trace
        if (now - last_trace_heartbeat) >= 60:
            try:
                scout._write_ai_trace(
                    best_action="WAIT",
                    venue="indodax",
                    reason="heartbeat",
                    confidence=0.0,
                    risk_status="SCOUTING",
                    next_check_seconds=60,
                    market_summary="heartbeat refresh",
                )
                last_trace_heartbeat = now
            except Exception as e:
                scout._log(f"[WARN] AI trace heartbeat failed: {e}")
        
        await asyncio.sleep(5) # Fast poll interval

if __name__ == "__main__":
    asyncio.run(run_scout_loop())
