import os
import json
import time
import asyncio
import logging
import subprocess
from typing import Dict, List, Optional, Any
from pathlib import Path

# Load core modules
from SERVER_BATAM.Core.circuit_breaker import CircuitBreaker
from SERVER_BATAM.Intelligence.kibot_ai_search import AISearchService

logger = logging.getLogger("SovereignCouncil")

class SovereignCouncil:
    def __init__(self):
        self.state_dir = Path("/Users/kiki/Documents/Web Develop/KiBot/SERVER_BATAM/state")
        self.decision_log = self.state_dir / "council_decisions.jsonl"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Thresholds based on design spec
        self.CONFIDENCE_AUTO_THRESHOLD = 0.85
        self.RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        self.search_service = AISearchService()

    async def _query_ollama(self, model: str, prompt: str, system_prompt: str = "") -> str:
        """Helper to query Ollama with RAM management (keep_alive: 0)"""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "system": system_prompt,
                        "stream": False,
                        "keep_alive": "90s" # Unload after 90s to save RAM
                    }
                )
                if response.status_code == 200:
                    return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama error ({model}): {e}")
        return ""

    async def deliberate(self, issue_context: Dict) -> Dict:
        """The 5-step deliberation process of the Council"""
        logger.info(f"Council deliberation started for issue: {issue_context.get('type', 'Unknown')}")
        
        # 1. OBSERVER (0.6b) - Sensory Analysis (The Watchman)
        snapshot = issue_context.get("snapshot", {})
        
        # Hard-coded Safety Net: Detect obvious failures first
        snapshot_str = json.dumps(snapshot).upper()
        manual_anomaly = any(x in snapshot_str for x in ["OFFLINE", "NEEDSAUTH", "DEGRADED", "FAILED"])
        
        obs_prompt = (
            f"System Snapshot: {json.dumps(snapshot)}\n"
            f"CRITICAL RULE: Any status like 'OFFLINE', 'NeedsAuth', or 'Degraded' MUST be flagged as ANOMALY. "
            f"Output ONLY: NORMAL or ANOMALY."
        )
        obs_analysis = await self._query_ollama("qwen2.5:0.5b", obs_prompt, "You are a strict KiBot System Auditor.")
        
        # Decision logic: Either AI says ANOMALY or Python found a failure string
        if not manual_anomaly and "NORMAL" in obs_analysis.upper() and issue_context.get("type") != "CIRCUIT_BREAKER_OPEN":
            logger.info("Watchman analysis: System NORMAL. Ending deliberation.")
            return {"action": "NONE", "confidence": 1.0, "risk": "LOW", "reasoning": "Watchman confirmed system stability."}
        
        reason = "Manual override" if manual_anomaly else obs_analysis
        logger.info(f"Watchman/Safety-Net detected: {reason}. Proceeding to Diagnostician.")
        
        # 2. DIAGNOSTICIAN (1.7b) - Root Cause Analysis
        diag_prompt = f"Analyze this issue snapshot and provide the root cause:\n{json.dumps(snapshot)}"
        diagnosis = await self._query_ollama("qwen2.5:1.5b", diag_prompt, "You are the KiBot Diagnostician. Be precise.")
        
        # 3. STRATEGIST (DeepSeek-R1 / Reasoning Mode) - Propose Solutions
        # Add External Intelligence if needed
        external_context = ""
        if any(kw in diagnosis.lower() for kw in ["market", "price", "error", "connectivity", "outage"]):
            logger.info("Council calling Global Eye (Web Search)...")
            try:
                external_context = self.search_service.get_market_consensus(diagnosis[:100])
            except Exception as e:
                logger.warning(f"Search failed: {e}")

        # 3. STRATEGIST (1.5b) - Situational Planning
        strat_prompt = (
            f"--- SITUATIONAL WAR-ROOM ANALYSIS ---\n"
            f"INTERNAL DIAGNOSIS: {diagnosis}\n"
            f"GLOBAL CONTEXT (WEB): {external_context}\n"
            f"\n"
            f"You are the KiBot Chief Strategist. Provide a NON-ROBOTIC, SITUATIONAL response:\n"
            f"1. LOCAL vs GLOBAL: Is this specific to us or a market-wide outage?\n"
            f"2. WHAT-IF ANALYSIS: What happens if this continues for 1 hour? 24 hours?\n"
            f"3. DYNAMIC SCENARIOS:\n"
            f"   - Scenario A (Low Impact): If it's a minor glitch, suggest RESTART_REDIS or RECONNECT_TAILSCALE.\n"
            f"   - Scenario B (High Impact/Black Swan): If it looks like a cyberattack or systemic failure, suggest SAFE_SHUTDOWN.\n"
            f"\n"
            f"Respond in Indonesian/English. Be tactical and provide clear reasoning."
        )
        
        # Using Qwen 1.5b for reliability on local machine
        strategies = await self._query_ollama("qwen2.5:1.5b", strat_prompt, "You are a Tactical War-Room Strategist. Analyze the Black Swan risks.")
        
        # 4. RISK ARBITER (0.5b) - Final Scoring
        arb_prompt = (
            f"Based on these situational strategies:\n{strategies}\n"
            f"Pick the most realistic action for NOW.\n"
            f"Output ONLY valid JSON: {{'action': '...', 'confidence': 0.XX, 'risk': '...', 'reasoning': '...'}}"
        )
        decision_raw = await self._query_ollama("qwen2.5:0.5b", arb_prompt, "You are the Final Arbiter. Output JSON only.")
        
        # Clean JSON and parse
        try:
            # Simple cleanup for LLM output
            if "```json" in decision_raw:
                decision_raw = decision_raw.split("```json")[1].split("```")[0]
            decision = json.loads(decision_raw.strip())
        except:
            decision = {
                "action": "ESCALATE_TO_HUMAN",
                "confidence": 0.0,
                "risk": "CRITICAL",
                "reasoning": "Council deliberation failed to produce parseable JSON."
            }

        # 5. EXECUTOR BRIDGE (Logic Only)
        decision["auto_execute"] = (
            decision.get("confidence", 0) >= self.CONFIDENCE_AUTO_THRESHOLD and 
            decision.get("risk", "HIGH") in ["LOW", "MEDIUM"]
        )
        
        # Final safety: Never auto-execute CRITICAL
        if decision.get("risk") == "CRITICAL":
            decision["auto_execute"] = False
            
        self._log_decision(decision)
        return decision

    def _log_decision(self, decision: Dict):
        """Audit trail for decisions"""
        with open(self.decision_log, "a") as f:
            log_entry = {
                "timestamp": time.time(),
                "at_str": time.ctime(),
                "decision": decision
            }
            f.write(json.dumps(log_entry) + "\n")

    def get_decision_history(self, limit: int = 10) -> List[Dict]:
        if not self.decision_log.exists(): return []
        with open(self.decision_log, "r") as f:
            lines = f.readlines()
            return [json.loads(l) for l in lines[-limit:]]
