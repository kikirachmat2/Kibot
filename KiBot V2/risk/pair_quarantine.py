import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger("KiBotV2.PairQuarantine")

PERMANENT_BLOCKED_PAIRS = {
    "TRXIDR", "TRX_IDR", "TRX/IDR",
    "SHIBIDR", "SHIB_IDR", "SHIB/IDR",
    "BNBIDR", "BNB_IDR", "BNB/IDR",
}

class PairQuarantineManager:
    """
    Manages pair-level quarantines and cooldowns to prevent idiosyncratic
    fee bleeding and adverse market traps.
    - 3 consecutive losses on a pair -> 24h quarantine (86,400s)
    - 3 consecutive timeouts (MAX_HOLD_TIME_EXPIRED) -> 4h quarantine (14,400s)
    - Permanent blacklist enforcement
    - Automatic TTL-based expiry
    """
    def __init__(
        self,
        consecutive_loss_threshold: int = 3,
        consecutive_loss_cooldown_s: int = 86400,   # 24 hours
        consecutive_timeout_threshold: int = 3,
        consecutive_timeout_cooldown_s: int = 14400, # 4 hours
    ):
        self.loss_threshold = consecutive_loss_threshold
        self.loss_cooldown_s = consecutive_loss_cooldown_s
        self.timeout_threshold = consecutive_timeout_threshold
        self.timeout_cooldown_s = consecutive_timeout_cooldown_s
        
        self.consecutive_losses: Dict[str, int] = {}
        self.consecutive_timeouts: Dict[str, int] = {}
        self.quarantines: Dict[str, Dict[str, Any]] = {}

    def _normalize(self, symbol: str) -> str:
        return str(symbol or "").upper().replace("/", "").replace("_", "").strip()

    def is_quarantined(self, symbol: str) -> Tuple[bool, str]:
        """
        Checks if symbol is currently blacklisted or quarantined.
        Automatically purges expired quarantine entries.
        Returns:
            (is_quarantined: bool, reason: str)
        """
        norm = self._normalize(symbol)
        
        # 1. Check Permanent Blacklist
        if norm in PERMANENT_BLOCKED_PAIRS or symbol.upper() in PERMANENT_BLOCKED_PAIRS:
            return True, "PERMANENT_BLACKLIST"

        # 2. Check Active Quarantines
        rec = self.quarantines.get(norm)
        if rec:
            now = time.time()
            until_ts = rec.get("until_ts", 0)
            if now < until_ts:
                remaining_s = int(until_ts - now)
                until_iso = rec.get("until_iso", "")
                reason = rec.get("reason", "UNKNOWN")
                return True, f"QUARANTINED_UNTIL_{until_iso} ({remaining_s}s remaining, reason: {reason})"
            else:
                # Expired -> Clean up
                logger.info(f"[PairQuarantine] 🔓 Quarantine expired for {norm}. Cooldown lifted.")
                del self.quarantines[norm]

        return False, ""

    def record_trade_result(
        self,
        symbol: str,
        realized_pnl_idr: float,
        exit_reason: str,
    ) -> Optional[str]:
        """
        Updates consecutive loss/timeout counters and triggers quarantine if thresholds are breached.
        Returns triggered quarantine mode if newly quarantined, else None.
        """
        norm = self._normalize(symbol)

        # Update Loss Counter
        if realized_pnl_idr < 0:
            self.consecutive_losses[norm] = self.consecutive_losses.get(norm, 0) + 1
        else:
            self.consecutive_losses[norm] = 0

        # Update Timeout Counter
        if exit_reason == "MAX_HOLD_TIME_EXPIRED":
            self.consecutive_timeouts[norm] = self.consecutive_timeouts.get(norm, 0) + 1
        else:
            self.consecutive_timeouts[norm] = 0

        loss_count = self.consecutive_losses[norm]
        timeout_count = self.consecutive_timeouts[norm]

        # Evaluate Consecutive Timeouts (4h)
        if timeout_count >= self.timeout_threshold:
            self.quarantine_pair(
                symbol=symbol,
                reason=f"{timeout_count}_CONSECUTIVE_TIMEOUTS_CHURN",
                duration_seconds=self.timeout_cooldown_s,
            )
            self.consecutive_timeouts[norm] = 0
            self.consecutive_losses[norm] = 0
            return "QUARANTINED_CONSECUTIVE_TIMEOUTS"

        # Evaluate Consecutive Losses (24h)
        if loss_count >= self.loss_threshold:
            self.quarantine_pair(
                symbol=symbol,
                reason=f"{loss_count}_CONSECUTIVE_LOSSES",
                duration_seconds=self.loss_cooldown_s,
            )
            # Reset counters so we don't re-trigger immediately upon expiry
            self.consecutive_losses[norm] = 0
            self.consecutive_timeouts[norm] = 0
            return "QUARANTINED_CONSECUTIVE_LOSSES"

        return None

    def quarantine_pair(
        self,
        symbol: str,
        reason: str,
        duration_seconds: int = 86400,
    ) -> None:
        """Explicitly quarantines a symbol for the specified duration in seconds."""
        norm = self._normalize(symbol)
        now = time.time()
        until_ts = now + duration_seconds
        until_iso = datetime.fromtimestamp(until_ts, tz=timezone.utc).isoformat()
        
        self.quarantines[norm] = {
            "until_ts": until_ts,
            "until_iso": until_iso,
            "reason": reason,
            "created_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }
        logger.warning(
            f"[PairQuarantine] 🛑 Symbol {norm} placed under QUARANTINE until {until_iso} "
            f"({duration_seconds}s, Reason: {reason})"
        )

    def lift_quarantine(self, symbol: str) -> None:
        """Manually lifts quarantine for a symbol."""
        norm = self._normalize(symbol)
        if norm in self.quarantines:
            del self.quarantines[norm]
            logger.info(f"[PairQuarantine] 🔓 Manually lifted quarantine for {norm}")

    def state_dict(self) -> Dict[str, Any]:
        return {
            "consecutive_losses": dict(self.consecutive_losses),
            "consecutive_timeouts": dict(self.consecutive_timeouts),
            "quarantines": dict(self.quarantines),
        }

    def load_state(self, state: Dict[str, Any]) -> None:
        self.consecutive_losses = state.get("consecutive_losses", {})
        self.consecutive_timeouts = state.get("consecutive_timeouts", {})
        self.quarantines = state.get("quarantines", {})
