import json
import logging
import os
import time
import pathlib
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

logger = logging.getLogger("KiBot.NoIdleScriptDirector")

DEFAULT_STATE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "state"

WIB_UTC_OFFSET_HOURS = int(os.getenv("KIBOT_WIB_UTC_OFFSET_HOURS", "7"))
WIB_TZ = timezone(timedelta(hours=WIB_UTC_OFFSET_HOURS))

class NoIdleScriptDirector:
    """
    No-Idle Script Director & Deadline-Aware Scanner Speed Controller (§11.3).
    Ensures scanners never idle or freeze, and dynamically scales scanner speed 
    as the WIB midnight deadline approaches.
    """

    def __init__(self, state_dir: pathlib.Path = DEFAULT_STATE_DIR):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.director_path = self.state_dir / "no_idle_script_director.json"
        self.pressure_path = self.state_dir / "scanner_pressure.json"
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        """Sets up default configuration states if missing."""
        if not self.director_path.exists():
            defaults = {
                "last_active_time": time.time(),
                "scanners_heartbeat": {
                    "solana_trending": time.time(),
                    "pumpfun": time.time(),
                    "indodax": time.time(),
                    "polymarket": time.time()
                },
                "idle_threshold_sec": 300,
                "status": "HEALTHY",
                "last_alert_time": 0.0
            }
            try:
                self.director_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to write default no-idle director file: {e}")

        if not self.pressure_path.exists():
            pressure_defaults = {
                "minutes_to_midnight": 1440,
                "interval_scale": 1.0,
                "pressure_level": "PATIENT",
                "timestamp": time.time()
            }
            try:
                self.pressure_path.write_text(json.dumps(pressure_defaults, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to write default scanner pressure file: {e}")

    def update_heartbeat(self, scanner_name: str) -> None:
        """Logs a heartbeat event for a given scanner name to prevent freezing false alarms."""
        self._ensure_defaults()
        try:
            state = json.loads(self.director_path.read_text(encoding="utf-8"))
            if "scanners_heartbeat" not in state:
                state["scanners_heartbeat"] = {}
            state["scanners_heartbeat"][scanner_name] = time.time()
            state["last_active_time"] = time.time()
            state["status"] = "HEALTHY"
            self.director_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to update heartbeat for {scanner_name}: {e}")

    def audit_heartbeats(self) -> Dict[str, Any]:
        """Audits heartbeats of all active scanners and flags frozen or hanging routines."""
        self._ensure_defaults()
        try:
            state = json.loads(self.director_path.read_text(encoding="utf-8"))
            now = time.time()
            threshold = float(state.get("idle_threshold_sec", 300))
            
            anomalies = []
            heartbeats = state.get("scanners_heartbeat", {})
            for name, last_ts in heartbeats.items():
                elapsed = now - float(last_ts)
                if elapsed > threshold:
                    anomalies.append({
                        "scanner": name,
                        "elapsed_seconds": round(elapsed, 1),
                        "status": "FROZEN"
                    })
            
            if anomalies:
                state["status"] = "DEGRADED"
                state["anomalies"] = anomalies
                logger.warning(f"⚠️ [NO-IDLE DIRECTOR] Frozen scanners detected: {anomalies}")
                # Rate limit alarm notifications or actions if necessary
            else:
                state["status"] = "HEALTHY"
                state.pop("anomalies", None)

            self.director_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            return state
        except Exception as e:
            logger.error(f"Failed to audit heartbeats: {e}")
            return {"status": "ERROR", "reason": str(e)}

    def calculate_deadline_pressure(self) -> Dict[str, Any]:
        """
        Calculates remaining WIB time until midnight and adjusts scanner intervals.
        Scale levels range from 1.0x (standard) down to 0.40x (max speed/high frequency).
        """
        self._ensure_defaults()
        
        # Calculate minutes remaining to WIB midnight
        now_wib = datetime.now(WIB_TZ)
        midnight_wib = now_wib.replace(hour=23, minute=59, second=59, microsecond=999999)
        time_left = midnight_wib - now_wib
        
        # If past midnight, set next midnight
        if time_left.total_seconds() < 0:
            time_left = timedelta(days=1) - (now_wib - midnight_wib)
            
        minutes_left = int(time_left.total_seconds() // 60)
        
        # Scale intervals based on time left
        if minutes_left > 720: # >12 hours
            scale = 1.0
            level = "PATIENT"
        elif minutes_left > 360: # 6-12 hours
            scale = 0.8
            level = "STEADY"
        elif minutes_left > 120: # 2-6 hours
            scale = 0.6
            level = "AGGRESSIVE"
        else: # <2 hours
            scale = 0.4
            level = "HYPER_SPEED"

        pressure = {
            "minutes_to_midnight": minutes_left,
            "interval_scale": scale,
            "pressure_level": level,
            "timestamp": time.time(),
            "wib_time": now_wib.strftime("%Y-%m-%d %H:%M:%S WIB")
        }
        
        try:
            self.pressure_path.write_text(json.dumps(pressure, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to write scanner pressure config: {e}")
            
        return pressure
