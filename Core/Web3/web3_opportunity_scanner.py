import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import aiohttp

logger = logging.getLogger('Web3OpportunityScanner')

STATE_DIR = Path(__file__).resolve().parent.parent.parent / 'state'
OPPS_FILE = STATE_DIR / 'web3_opportunities.json'

class Web3OpportunityScanner:
    def __init__(self):
        self.solana_rpc = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')
        self.base_rpc = os.getenv('BASE_RPC_URL', 'https://mainnet.base.org')
        self.updated_at = None

    def _load_state(self) -> Dict[str, Any]:
        if not OPPS_FILE.exists():
            return {"updated_at": "", "best_opportunities": [], "rejected": [], "routes": {"solana": {}, "base": {}, "polymarket": {}, "future_web3": {}}}
        try:
            return json.loads(OPPS_FILE.read_text())
        except Exception:
            return {"updated_at": "", "best_opportunities": [], "rejected": [], "routes": {"solana": {}, "base": {}, "polymarket": {}, "future_web3": {}}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        OPPS_FILE.write_text(json.dumps(state, indent=2))

    async def _solana_health(self) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.solana_rpc, json={"jsonrpc":"2.0","id":1,"method":"getHealth"}, timeout=5) as resp:
                    return {"ok": resp.status == 200}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    async def _base_health(self) -> Dict[str, Any]:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.base_rpc, json={"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]}, timeout=5) as resp:
                    data = await resp.json()
                    block = int(str(data.get('result') or '0x0'), 16) if resp.status == 200 else 0
                    return {"ok": resp.status == 200, "latest_block": block}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    async def scan(self) -> Dict[str, Any]:
        from Core.Intelligence.phantom_opportunity_scout import PhantomOpportunityScout
        scout = PhantomOpportunityScout()
        sol = await self._solana_health()
        base = await self._base_health()
        best = []
        rejected = []

        try:
            defi = await scout.get_best_defi_opportunities()
            best.append({
                "route": "solana",
                "asset": defi.get('highest_apy_protocol', 'kamino_apy'),
                "ev": float(defi.get('highest_apy', 0.0)),
                "reason": defi.get('regime', ''),
            })
        except Exception as e:
            rejected.append({"route": "solana", "reason": f"defi scout failed: {e}"})

        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "best_opportunities": best,
            "rejected": rejected,
            "routes": {
                "solana": {"health": sol, "status": "LIVE_READY" if sol.get('ok') else "SCOUTING"},
                "base": {"health": base, "status": "SCOUTING" if base.get('ok') else "SCOUTING"},
                "polymarket": {"status": "SCOUTING"},
                "future_web3": {"status": "SCOUTING"},
            },
        }
        self._save_state(state)
        self.updated_at = state["updated_at"]
        return state
