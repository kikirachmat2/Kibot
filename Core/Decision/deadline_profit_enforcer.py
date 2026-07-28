import json
import logging
import os
import time
import pathlib
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger("KiBot.DeadlineProfitEnforcer")

DEFAULT_STATE_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "state"

# Throttle: only log when reason changes or every N seconds
_THROTTLE_INTERVAL = 300  # 5 minutes


class DeadlineProfitEnforcer:
    """
    Deadline Profit Enforcer (§12.1).
    Locks in trading gains and blocks further entry/execution when daily targets
    are hit, or when the midnight deadline approaches under profitable postures.
    """

    def __init__(self, state_dir: pathlib.Path = DEFAULT_STATE_DIR):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.enforcer_path = self.state_dir / "deadline_profit_enforcer.json"
        self.authority_path = self.state_dir / "decision_authority.json"
        self._last_logged_reason: str = ""
        self._last_logged_time: float = 0.0
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        """Sets up default enforcer config if missing."""
        if not self.enforcer_path.exists():
            defaults = {
                "locked_for_day": False,
                "lock_reason": "No lock active",
                "daily_pnl_pct": 0.0,
                "daily_pnl_idr": 0.0,
                "last_evaluated_at": time.time()
            }
            try:
                self.enforcer_path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to write default enforcer file: {e}")

    def evaluate_enforcer(self, daily_pnl_pct: float, daily_pnl_idr: float, minutes_to_midnight: int) -> Dict[str, Any]:
        """
        Main enforcer evaluation loop.
        Applies targets and deadlines to lock/protect PnL.
        """
        self._ensure_defaults()
        
        # Load profit targets from Decision Authority config
        target_pct = 1.5
        global_loss_cap_idr = 0.0
        capital_governor_path = self.state_dir / "capital_governor.json"
        if capital_governor_path.exists():
            try:
                gov = json.loads(capital_governor_path.read_text(encoding="utf-8"))
                global_loss_cap_idr = float(gov.get("max_daily_loss_idr", 0.0) or 0.0)
            except Exception:
                global_loss_cap_idr = 0.0
        if self.authority_path.exists():
            try:
                auth_cfg = json.loads(self.authority_path.read_text(encoding="utf-8"))
                target_pct = float(auth_cfg.get("lock_green_pnl_pct", 1.5))
            except Exception:
                pass

        locked = False
        reason = "No lock active"
        stage = "NORMAL"
        if daily_pnl_idr < 0.0:
            stage = "RECOVERY"
        elif daily_pnl_pct > 0.0:
            stage = "GREEN"
        if minutes_to_midnight <= 180 and daily_pnl_pct > 0.0:
            stage = "AGGRESSIVE_SEARCH"
        if daily_pnl_pct <= 0.0:
            stage = "RECOVERY"

        if global_loss_cap_idr > 0.0 and daily_pnl_idr <= -global_loss_cap_idr:
            locked = True
            reason = (
                f"LOSS_CUTOFF: Daily loss cap breached ({daily_pnl_idr:.2f} <= -{global_loss_cap_idr:.2f})"
            )
            stage = "FATAL_BLOCKED"

        # Rule 1: Lock Green Target reached
        if not locked and daily_pnl_pct >= target_pct:
            locked = True
            reason = f"LOCK_GREEN: Daily profit target reached ({daily_pnl_pct:.2f}% >= {target_pct:.2f}%)"
            stage = "CLOSING_WINDOW"
        
        # Rule 2: Midnight deadline approaching protection
        elif not locked and minutes_to_midnight <= 30 and daily_pnl_pct > 0.0:
            locked = True
            reason = f"LOCK_GREEN: Midnight approaching ({minutes_to_midnight}m left) and green profit protected (+{daily_pnl_pct:.2f}%)"
            stage = "CLOSING_WINDOW"

        if stage == "FATAL_BLOCKED" and not locked:
            locked = True
        if stage == "RECOVERY" and not locked:
            reason = "RECOVERY: day is red; widen scan, lower nonfatal thresholds, keep searching"
        elif stage == "GREEN" and not locked:
            reason = "GREEN: profits present; keep hunting for continuation setups"
        elif stage == "AGGRESSIVE_SEARCH" and not locked:
            reason = f"AGGRESSIVE_SEARCH: {minutes_to_midnight}m left; continue hunting with tighter execution"

        required_action = "SCAN_NEXT"
        if stage == "FATAL_BLOCKED":
            required_action = "EXIT_ONLY"
        elif stage == "RECOVERY" and not locked:
            required_action = "ENTER_CAUTIOUSLY"
        elif stage == "AGGRESSIVE_SEARCH" and not locked:
            required_action = "SCAN_AND_ENTER"

        enforcer_state = {
            "locked_for_day": locked,
            "lock_reason": reason,
            "daily_pnl_pct": round(daily_pnl_pct, 4),
            "daily_pnl_idr": round(daily_pnl_idr, 2),
            "last_evaluated_at": time.time(),
            "wib_date": datetime.now(timezone.utc).date().isoformat(),
            "minutes_to_midnight": int(minutes_to_midnight),
            "stage": stage,
            "indodax_pressure": "MAX" if stage in {"RECOVERY", "AGGRESSIVE_SEARCH", "CLOSING_WINDOW", "FATAL_BLOCKED"} else "NORMAL",
            "required_action": required_action if not locked else ("EXIT_ONLY" if stage == "FATAL_BLOCKED" else "CLOSE_WINDOW"),
            "reason": reason,
        }

        try:
            self.enforcer_path.write_text(json.dumps(enforcer_state, indent=2), encoding="utf-8")
            if locked:
                now = time.time()
                reason_changed = (reason != self._last_logged_reason)
                throttle_elapsed = (now - self._last_logged_time) >= _THROTTLE_INTERVAL
                if reason_changed or throttle_elapsed:
                    logger.warning(f"🔒 [DEADLINE ENFORCER] Active Lock Engaged: {reason}")
                    self._last_logged_reason = reason
                    self._last_logged_time = now
            else:
                # Lock released — always log transition
                if self._last_logged_reason:
                    logger.info(f"🔓 [DEADLINE ENFORCER] Lock released (was: {self._last_logged_reason})")
                    self._last_logged_reason = ""
                    self._last_logged_time = 0.0
        except Exception as e:
            logger.error(f"Failed to write deadline enforcer state: {e}")

        return enforcer_state

    def reset_daily_lock(self) -> None:
        """Manually unlocks the daily profit enforcer (typically run at midnight)."""
        self._ensure_defaults()
        try:
            state = {
                "locked_for_day": False,
                "lock_reason": "Daily reset performed",
                "daily_pnl_pct": 0.0,
                "daily_pnl_idr": 0.0,
                "last_evaluated_at": time.time()
            }
            self.enforcer_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
            logger.info("🔓 [DEADLINE ENFORCER] Daily lock reset successfully.")
        except Exception as e:
            logger.error(f"Failed to reset daily enforcer lock: {e}")
