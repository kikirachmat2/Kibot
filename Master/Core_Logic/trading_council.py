import json
import httpx
import asyncio
from pathlib import Path
from datetime import datetime
from SERVER_BATAM.Core_Logic.council_data_aggregator import CouncilDataAggregator

class TradingCouncil:
    """
    Sovereign Trading Council
    Orchestrates automated debates between specialized AI personas to govern trading operations.
    
    Personas:
    - MomentumHawk: Focused on market strength and trend following.
    - RiskSentinel: Focused on capital preservation and risk mitigation.
    - OpportunityScout: Focused on auditing missed opportunities and pattern recognition.
    """
    def __init__(self, master_node):
        self.master = master_node
        self.aggregator = CouncilDataAggregator(master_node)
        self.ollama_url = getattr(master_node, "ollama_url", "http://127.0.0.1:11434")
        self.model = "qwen3:1.7b" # Use 3B for reasoning if available, fallback to 1B
        
        base_dir = Path(__file__).resolve().parent.parent
        self.directive_log = base_dir / "Logs" / "council_directives.json"

    async def conduct_session(self, tier="TIER_1_SYNC"):
        """
        Executes a full council session: data aggregation -> multi-persona debate -> final directive.
        """
        print(f"🏛️ Starting Council Session: {tier}")
        context = self.aggregator.get_debate_context(tier)
        
        # 1. Persona Debates
        hawk_view = await self._query_persona("MomentumHawk", "Aggressive analyst looking for volume/momentum strength.", context)
        sentinel_view = await self._query_persona("RiskSentinel", "Conservative guard focused on capital preservation and loss avoidance.", context)
        scout_view = await self._query_persona("OpportunityScout", "System auditor analyzing missed gains and rejection patterns.", context)
        
        # 2. Synthesis & Final Directive
        directive = await self._synthesize_directive(hawk_view, sentinel_view, scout_view, context)
        
        # 3. Log and Dispatch
        self._log_directive(directive)
        
        # 4. Notify Telegram
        await self._notify_council_result(directive)
        
        return directive

    async def _query_persona(self, name, philosophy, context):
        """Queries a specific persona for their take on the current state."""
        prompt = (
            f"Persona: {name}\n"
            f"Philosophy: {philosophy}\n"
            f"Core Tenet: {context['philosophy']['core']}\n\n"
            f"Current Data Snapshot:\n"
            f"- Market Mood: {context['market_context']['mood']}\n"
            f"- Regime: {context['market_context']['regime']}\n"
            f"- Portfolio PnL: {context['portfolio_state'].get('daily_pnl', '0%')}\n"
            f"- Recent Rejections: {context['audit_data']['rejection_analysis']['total']}\n"
            f"- Missed Opportunities: {len(context['audit_data']['missed_opportunities'])}\n\n"
            f"Analyze this data from your persona's perspective. Be concise (max 2 sentences)."
        )
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{self.ollama_url}/api/generate", json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False
                }, timeout=30.0)
                return resp.json().get("response", "No response.")
        except Exception as e:
            return f"Persona {name} failed to respond: {e}"

    async def _synthesize_directive(self, hawk, sentinel, scout, context):
        """Synthesizes the persona views into a single actionable directive."""
        prompt = (
            f"Council Debate Summary:\n"
            f"- MomentumHawk: {hawk}\n"
            f"- RiskSentinel: {sentinel}\n"
            f"- OpportunityScout: {scout}\n\n"
            f"Generate a 'Council Directive' in JSON format:\n"
            f"{{\n"
            f"  \"bias\": \"BULLISH/BEARISH/CAUTIOUS\",\n"
            f"  \"risk_level\": 1-5,\n"
            f"  \"action_summary\": \"one sentence directive\",\n"
            f"  \"logic\": \"brief reasoning\"\n"
            f"}}"
        )
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{self.ollama_url}/api/generate", json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }, timeout=30.0)
                directive = json.loads(resp.json().get("response", "{}"))
                directive["timestamp"] = datetime.now().isoformat()
                return directive
        except Exception:
            return {
                "bias": "CAUTIOUS",
                "risk_level": 1,
                "action_summary": "System maintenance; AI synthesis failed.",
                "logic": "Fallback safety directive.",
                "timestamp": datetime.now().isoformat()
            }

    def _log_directive(self, directive):
        """Saves the directive to a persistent log."""
        directives = []
        if self.directive_log.exists():
            try:
                with open(self.directive_log, "r") as f:
                    directives = json.load(f)
                    if not isinstance(directives, list): directives = []
            except: pass
            
        directives.append(directive)
        # Keep only last 50 directives
        directives = directives[-50:]
        
        with open(self.directive_log, "w") as f:
            json.dump(directives, f, indent=2)

    async def _notify_council_result(self, directive):
        """Sends a formatted summary of the council session to Telegram."""
        emoji = "📈" if directive["bias"] == "BULLISH" else ("📉" if directive["bias"] == "BEARISH" else "🛡️")
        msg = (
            f"🏛️ **SOVEREIGN COUNCIL DIRECTIVE**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Status: {emoji} **{directive['bias']}**\n"
            f"Risk Level: `[{'●' * int(directive.get('risk_level', 1))}{'○' * (5 - int(directive.get('risk_level', 1)))}]`\n\n"
            f"**Action**: _{directive['action_summary']}_\n"
            f"**Logic**: {directive['logic']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Tier: `TIER_1_SYNC`"
        )
        if hasattr(self.master, "notify_telegram"):
            await self.master.notify_telegram(msg)
