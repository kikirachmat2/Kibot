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

logger = logging.getLogger("SovereignCouncil")

class SovereignCouncil:
    def __init__(self):
        self.state_dir = Path("/Users/kiki/Documents/Web Develop/KiBot/SERVER_BATAM/state")
        self.decision_log = self.state_dir / "council_decisions.jsonl"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        
        # Thresholds based on design spec
        self.CONFIDENCE_AUTO_THRESHOLD = 0.85
        self.RISK_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

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
        
        # 1. OBSERVER (0.6b) - Context gathering (already provided in issue_context for now)
        snapshot = issue_context.get("snapshot", {})
        
        # 2. DIAGNOSTICIAN (1.7b) - Root Cause Analysis
        diag_prompt = f"Analyze this issue snapshot and provide the root cause:\n{json.dumps(snapshot)}"
        diagnosis = await self._query_ollama("qwen2.5:1.5b", diag_prompt, "You are the KiBot Diagnostician. Be precise.")
        
        # 3. STRATEGIST (1.7b/4b) - Propose Solutions
        strat_prompt = f"Diagnosis: {diagnosis}\nPropose 2-3 solutions with Risk (LOW/MEDIUM/HIGH) and Impact scores."
        strategies = await self._query_ollama("qwen2.5:1.5b", strat_prompt, "You are the KiBot Strategist.")
        
        # 4. RISK ARBITER (0.6b) - Final Scoring
        arb_prompt = f"Strategies: {strategies}\nPick the best one. Output JSON: {{'action': '...', 'confidence': 0.XX, 'risk': '...', 'reasoning': '...'}}"
        decision_raw = await self._query_ollama("qwen2.5:0.5b", arb_prompt, "Output ONLY valid JSON.")
        
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
