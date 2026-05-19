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
        self._heartbeat_state()

    def _heartbeat_state(self) -> None:
        try:
            state = self._load_state()
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            self.updated_at = state["updated_at"]
        except Exception:
            pass

    def _blank_state(self) -> Dict[str, Any]:
        return {
            "updated_at": "",
            "objective": "maximize_risk_adjusted_profit_for_boss",
            "best_opportunities": [],
            "rejected": [],
            "routes": {"solana": {}, "base": {}, "polymarket": {}, "future_web3": {}},
            "meme_hunter": {
                "enabled": bool(int(os.getenv("WEB3_MEME_HUNTER_ENABLED", "1") or 1)),
                "best_candidate": {},
                "candidates_found": 0,
                "rejected_count": 0,
                "sources": [],
                "latest_update": "",
            },
        }

    def _load_state(self) -> Dict[str, Any]:
        if not OPPS_FILE.exists():
            return self._blank_state()
        try:
            payload = json.loads(OPPS_FILE.read_text())
            payload.setdefault("meme_hunter", self._blank_state()["meme_hunter"])
            return payload
        except Exception:
            return self._blank_state()

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
        from Core.Web3.solana_trending_scanner import SolanaTrendingScanner
        scout = PhantomOpportunityScout()
        meme_scanner = SolanaTrendingScanner()
        sol = {"ok": False, "reason": "not_run"}
        base = {"ok": False, "reason": "not_run"}
        best = []
        rejected = []
        meme_state: Dict[str, Any] = self._blank_state()["meme_hunter"]
        meme_best: Dict[str, Any] = {}

        try:
            sol = await self._solana_health()
            base = await self._base_health()
            meme_state = await meme_scanner.scan()
            meme_best = meme_state.get("best_candidate", {}) if isinstance(meme_state, dict) else {}

            try:
                defi = await scout.get_best_defi_opportunities()
                ev = float(defi.get('highest_apy', 0.0))
                safety_score = 80 if sol.get("ok") else 25
                decision = "APPROVE" if ev >= 1.0 and sol.get("ok") else "WAIT"
                best.append({
                    "route": "solana",
                    "asset": defi.get('highest_apy_protocol', 'kamino_apy'),
                    "ev_pct": ev,
                    "safety_score": safety_score,
                    "quote_ok": bool(sol.get("ok")),
                    "liquidity_ok": bool(sol.get("ok")),
                    "slippage_pct": 0.3 if sol.get("ok") else 2.5,
                    "max_trade_idr": 50000 if sol.get("ok") else 0,
                    "decision": decision,
                    "reason": defi.get('regime', ''),
                })
            except Exception as e:
                rejected.append({"route": "solana", "reason": f"defi scout failed: {e}"})

            if meme_best:
                meme_decision = {
                    "route": "solana",
                    "asset": meme_best.get("symbol") or meme_best.get("mint") or "meme_candidate",
                    "ev_pct": float(meme_best.get("ev_pct", 0) or 0),
                    "safety_score": float(meme_best.get("safety_score", 0) or 0),
                    "quote_ok": bool(meme_best.get("decision") == "APPROVE"),
                    "liquidity_ok": float(meme_best.get("liquidity_usd", 0) or 0) >= float(os.getenv("WEB3_MEME_MIN_LIQUIDITY_USD", "10000") or 10000),
                    "slippage_pct": float(meme_best.get("slippage_pct", 0) or 0),
                    "max_trade_idr": int(meme_best.get("max_trade_idr", 0) or 0),
                    "decision": str(meme_best.get("decision") or "WATCH"),
                    "reason": str(meme_best.get("reason") or ""),
                    "category": "solana_meme",
                    "candidate": meme_best,
                }
                if meme_decision["decision"] == "APPROVE":
                    best.insert(0, meme_decision)
                else:
                    rejected.append({
                        "route": "solana",
                        "reason": meme_decision["reason"],
                        "asset": meme_decision["asset"],
                        "category": "solana_meme",
                    })
        except Exception as e:
            rejected.append({"route": "solana", "reason": f"web3 scan failed: {e}"})

        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "objective": "maximize_risk_adjusted_profit_for_boss",
            "best_opportunities": best,
            "rejected": rejected,
            "routes": {
                "solana": {"health": sol, "status": "LIVE_READY" if sol.get('ok') else "SCOUTING"},
                "base": {"health": base, "status": "SCOUTING" if base.get('ok') else "SCOUTING"},
                "polymarket": {"status": "SCOUTING"},
                "future_web3": {"status": "SCOUTING"},
            },
            "meme_hunter": {
                "enabled": bool(int(os.getenv("WEB3_MEME_HUNTER_ENABLED", "1") or 1)),
                "best_candidate": meme_best if meme_best else {},
                "candidates_found": len(meme_state.get("candidates", []) if isinstance(meme_state, dict) else []),
                "rejected_count": len(meme_state.get("rejected", []) if isinstance(meme_state, dict) else []),
                "sources": meme_state.get("source", ["dexscreener", "jupiter"]) if isinstance(meme_state, dict) else ["dexscreener", "jupiter"],
                "latest_update": meme_state.get("updated_at", "") if isinstance(meme_state, dict) else "",
            },
        }
        self._save_state(state)
        self.updated_at = state["updated_at"]
        return state
