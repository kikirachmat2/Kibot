import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("DeadlineProfitEnforcer")

STATE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "state"
STATE_FILE = STATE_DIR / "deadline_profit_enforcer.json"

class DeadlineProfitEnforcer:
    """
    Deterministic Daily Profit Enforcer.
    Tracks and enforces daily trading PnL against hard targets.
    If profit targets are hit or exceeded, the enforcer sets a persistent lockout
    so that no further trading actions are executed for the remainder of the trading day.
    """

    def __init__(self) -> None:
        self.profit_target_pct = float(os.getenv("DAILY_PROFIT_TARGET_PCT", "5.0") or 5.0)
        self.profit_target_idr = float(os.getenv("DAILY_PROFIT_TARGET_IDR", "1000000.0") or 1000000.0)
        self._load_state()

    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self.locked_for_day = bool(data.get("locked_for_day", False))
                self.lock_reason = str(data.get("lock_reason", "No lock active"))
                self.daily_pnl_pct = float(data.get("daily_pnl_pct", 0.0))
                self.daily_pnl_idr = float(data.get("daily_pnl_idr", 0.0))
                self.last_evaluated_at = float(data.get("last_evaluated_at", datetime.now(timezone.utc).timestamp()))
                return
            except Exception as e:
                logger.error(f"Failed to load profit enforcer state: {e}")
        
        # Default fallback state
        self.locked_for_day = False
        self.lock_reason = "No lock active"
        self.daily_pnl_pct = 0.0
        self.daily_pnl_idr = 0.0
        self.last_evaluated_at = datetime.now(timezone.utc).timestamp()
        self._save_state()

    def _save_state(self) -> None:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "locked_for_day": self.locked_for_day,
                "lock_reason": self.lock_reason,
                "daily_pnl_pct": self.daily_pnl_pct,
                "daily_pnl_idr": self.daily_pnl_idr,
                "last_evaluated_at": self.last_evaluated_at
            }
            STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save profit enforcer state: {e}")

    async def evaluate_enforcement(self, daily_pnl_pct: float, daily_pnl_idr: float) -> bool:
        """
        Evaluate current daily PnL against hard targets.
        If target hit, lock trading and persist state.
        Returns:
            bool: True if locked, False otherwise.
        """
        # Reload state to check if we are already locked persistently
        self._load_state()
        if self.locked_for_day:
            return True

        self.daily_pnl_pct = daily_pnl_pct
        self.daily_pnl_idr = daily_pnl_idr
        self.last_evaluated_at = datetime.now(timezone.utc).timestamp()

        # Check if targets are hit (percentage or absolute IDR profit)
        pct_hit = daily_pnl_pct >= self.profit_target_pct
        idr_hit = daily_pnl_idr >= self.profit_target_idr

        if pct_hit or idr_hit:
            self.locked_for_day = True
            reasons = []
            if pct_hit:
                reasons.append(f"PnL % ({daily_pnl_pct:.2f}%) >= Target ({self.profit_target_pct:.2f}%)")
            if idr_hit:
                reasons.append(f"PnL IDR ({daily_pnl_idr:,.0f}) >= Target ({self.profit_target_idr:,.0f})")
            
            self.lock_reason = f"Daily target reached: {', '.join(reasons)}"
            logger.warning(f"[LOCKOUT] Daily profit target achieved. Enforcing safe lockout. Reason: {self.lock_reason}")
            self._save_state()
            return True

        self._save_state()
        return False

    def reset_lockout(self) -> None:
        """
        Manually resets the lockout and daily parameters.
        Permits operators to reset the daily limit state via script interface.
        """
        self.locked_for_day = False
        self.lock_reason = "Manual reset by operator"
        self.daily_pnl_pct = 0.0
        self.daily_pnl_idr = 0.0
        self.last_evaluated_at = datetime.now(timezone.utc).timestamp()
        logger.info("[RESET] Daily profit enforcer lockout has been reset by operator.")
        self._save_state()
