import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from Core.Scanner.wave_detection_engine import WaveDetectionEngine
from Core.Web3.pumpfun_route_detector import PumpfunRouteDetector

logger = logging.getLogger("PumpfunFastScanner")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
PUMPFUN_WAVE_FILE = STATE_DIR / "pumpfun_wave_candidates.json"

class PumpfunFastScanner:
    """
    Sub-second level fast wave scanner specifically engineered for the Pump.fun ecosystem.
    Tracks new launches, curve acceleration, buy pressure, migrations, and Jupiter routability.
    """

    def __init__(self) -> None:
        self.engine = WaveDetectionEngine()
        self.route_detector = PumpfunRouteDetector()
        self.state_dir = STATE_DIR
        self.scan_interval_ms = int(os.getenv("KIBOT_PUMPFUN_SCAN_INTERVAL_MS", "1000") or 1000)

    async def scan_waves(self) -> Dict[str, Any]:
        return await self.scan()

    async def scan(self) -> Dict[str, Any]:
        logger.info("⚡ Executing high-frequency Pump.fun wave scanner cycle...")
        
        # Pull raw real-time stream / mock candidates
        raw_candidates = await self._fetch_live_pumpfun_feed()

        new_launches = []
        early_pumps = []
        migrated = []
        jup_routable = []
        approved = []
        rejected = []

        for item in raw_candidates:
            evaluated = self.engine.evaluate_token(item)
            decision = evaluated.get("decision")
            phase = evaluated.get("wave_phase")

            # Route validation
            route_status = evaluated.get("route_status", "UNAVAILABLE")
            
            # Map sectors
            if phase == "NEW_LAUNCH":
                new_launches.append(evaluated)
            elif phase == "EARLY_PUMP":
                early_pumps.append(evaluated)
            elif phase == "MIGRATED":
                migrated.append(evaluated)
            
            if route_status == "AVAILABLE" and phase != "UNSAFE":
                jup_routable.append(evaluated)

            if decision == "APPROVE":
                approved.append(evaluated)
            elif decision == "REJECT":
                rejected.append(evaluated)

        best_candidate = approved[0] if approved else (early_pumps[0] if early_pumps else {})

        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "runner": "ACTIVE",
            "scan_interval_ms": self.scan_interval_ms,
            "new_launches": new_launches[:10],
            "early_pumps": early_pumps[:10],
            "migrated_candidates": migrated[:10],
            "jupiter_routable_candidates": jup_routable[:10],
            "best_candidate": best_candidate,
            "candidates": approved,
            "rejected": rejected,
            "approved_candidates": approved[:10],
            "rejected_candidates": rejected[:10],
            "reason": "Successfully evaluated Pump.fun ecosystem metrics." if approved else "No approved waves matching thresholds."
        }

        self.state_dir.mkdir(parents=True, exist_ok=True)
        PUMPFUN_WAVE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        logger.info(f"💾 Saved Pump.fun control wave state to {PUMPFUN_WAVE_FILE}")

        return state

    async def _fetch_live_pumpfun_feed(self) -> List[Dict[str, Any]]:
        # Simulation source of fresh Pump.fun token updates
        return [
            {
                "symbol": "SOULGUY",
                "mint": "soulguy_pumpfun_mint_address",
                "chain": "solana",
                "sector": "pumpfun_bonding_curve",
                "price_acceleration": 42.0,
                "volume_acceleration": 25.0,
                "buy_sell_imbalance": 0.85,
                "liquidity_expansion": 20.0,
                "bonding_curve_progress": 92.5,
                "holder_growth_pct": 28.0,
                "fresh_pair_creation": True,
                "migration_event": False,
                "route_availability": True,
                "exit_liquidity_quality": 0.9
            },
            {
                "symbol": "DUMMYPUMP",
                "mint": "dummy_pumpfun_mint_address",
                "chain": "solana",
                "sector": "pumpfun_bonding_curve",
                "price_acceleration": 2.0,
                "volume_acceleration": 1.0,
                "buy_sell_imbalance": 0.1,
                "liquidity_expansion": 1.0,
                "bonding_curve_progress": 10.0,
                "holder_growth_pct": 1.0,
                "fresh_pair_creation": False,
                "migration_event": False,
                "route_availability": False,
                "exit_liquidity_quality": 0.1
            },
            {
                "symbol": "PEPEFAST",
                "mint": "pepefast_pumpfun_migrated_address",
                "chain": "solana",
                "sector": "pumpfun_migrated",
                "price_acceleration": 35.0,
                "volume_acceleration": 30.0,
                "buy_sell_imbalance": 0.78,
                "liquidity_expansion": 45.0,
                "bonding_curve_progress": 100.0,
                "holder_growth_pct": 40.0,
                "fresh_pair_creation": False,
                "migration_event": True,
                "route_availability": True,
                "exit_liquidity_quality": 0.95
            }
        ]
