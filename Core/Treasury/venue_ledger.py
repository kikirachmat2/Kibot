import logging
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("VenueLedger")

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
LEDGER_FILE = STATE_DIR / "venue_ledger.json"

class VenueLedger:
    """
    Sovereign Venue Ledger
    Tracks equity, realized PnL, unrealized PnL, and open exposure per venue.
    Modes: REAL | CONTROLLED_LIVE | SCOUTING_ONLY | SHADOW
    """
    def __init__(self):
        self.venues: Dict[str, Dict[str, Any]] = {}
        self._load_ledger()

    def _load_ledger(self):
        if LEDGER_FILE.exists():
            try:
                with open(LEDGER_FILE, "r") as f:
                    self.venues = json.load(f)
                    if self._sanitize_ledger():
                        self.save()
                    logger.info("✅ Venue Ledger state successfully loaded.")
            except Exception as e:
                logger.error(f"❌ Failed to load Venue Ledger state: {e}")
                self._initialize_default()
        else:
            self._initialize_default()

    def _sanitize_ledger(self) -> bool:
        allowed_modes = {"LIVE", "REAL", "RECONCILED", "BLOCKED_WITH_REASON", "SCOUTING", "OFFLINE"}
        legacy_terms = ("paper", "simulation", "shadow", "mock", "canary", "view-only")
        before = json.dumps(self.venues or {}, sort_keys=True, default=str)
        clean: Dict[str, Dict[str, Any]] = {}
        for key, venue in (self.venues or {}).items():
            lowered = f"{key} {json.dumps(venue, default=str)}".lower()
            if any(term in lowered for term in legacy_terms):
                continue
            item = venue if isinstance(venue, dict) else {}
            mode = str(item.get("mode") or "LIVE").upper()
            if mode not in allowed_modes:
                mode = "LIVE"
            item["mode"] = mode
            item.setdefault("status", "ACTIVE")
            item.setdefault("reason", "Operational")
            clean[key] = item
        self.venues = clean
        after = json.dumps(self.venues or {}, sort_keys=True, default=str)
        return before != after

    def _initialize_default(self):
        self.venues = {
            "indodax_real": {
                "venue": "Indodax Real",
                "mode": "LIVE",
                "equity_idr": 0.0,
                "daily_pnl_idr": 0.0,
                "open_exposure_idr": 0.0,
                "status": "ACTIVE",
                "reason": "Operational"
            },
            "phantom": {
                "venue": "Phantom Treasury",
                "mode": "LIVE",
                "equity_idr": 0.0,
                "daily_pnl_idr": 0.0,
                "open_exposure_idr": 0.0,
                "status": "ACTIVE",
                "reason": "Treasury visibility"
            },
            "polymarket": {
                "venue": "Polymarket",
                "mode": "LIVE",
                "equity_idr": 0.0,
                "daily_pnl_idr": 0.0,
                "open_exposure_idr": 0.0,
                "status": "ACTIVE",
                "reason": "Prediction market scouting"
            },
            "cash_wait": {
                "venue": "Cash Wait",
                "mode": "LIVE",
                "equity_idr": 0.0,
                "daily_pnl_idr": 0.0,
                "open_exposure_idr": 0.0,
                "status": "ACTIVE",
                "reason": "Sovereign reserve liquidity"
            }
        }
        self.save()

    def save(self):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with open(LEDGER_FILE, "w") as f:
                json.dump(self.venues, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save Venue Ledger: {e}")

    def update_venue(self, venue_key: str, **kwargs):
        """Update metrics for a specific venue and save state."""
        legacy_terms = ("paper", "simulation", "shadow", "mock", "canary", "view-only")
        if any(term in str(venue_key).lower() for term in legacy_terms):
            return
        if venue_key not in self.venues:
            self.venues[venue_key] = {
                "venue": venue_key.replace("_", " ").title(),
                "mode": "LIVE",
                "equity_idr": 0.0,
                "daily_pnl_idr": 0.0,
                "open_exposure_idr": 0.0,
                "status": "ACTIVE",
                "reason": "Initialized dynamically"
            }
        for k, v in kwargs.items():
            self.venues[venue_key][k] = v
        self.save()

    def get_venue(self, venue_key: str) -> Dict[str, Any]:
        return self.venues.get(venue_key, {})

    def get_all_venues(self) -> Dict[str, Dict[str, Any]]:
        return self.venues
