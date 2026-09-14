"""
Capital Governor for KiBot V2.
Ported and streamlined from KiBot V1 Core/Treasury/capital_governor.py.

Acts as an additional safety and exposure governance layer on top of RiskGate:
1. Max Concurrent Open Positions Cap:
   Prevents capital fragmentation and excessive exposure to illiquid altcoins.
   Limits active focus to top high-conviction opportunities.
2. Max Total Exposure Cap (% of Bankroll):
   Guarantees that a substantial reserve of liquid IDR cash remains intact,
   preventing catastrophic drawdowns during market-wide correlated crashes.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, Tuple, Optional, List
from config import settings
from risk.coin_category import get_coin_category, classify_coin_category
from risk.pair_quarantine import PairQuarantineManager
from risk.churn_guard import ChurnGuard

logger = logging.getLogger("KiBotV2.CapitalGovernor")


class CapitalGovernor:
    """
    Sovereign Capital Governor.
    Enforces macro portfolio allocation limits before orders reach execution:
    1. Pair Quarantine: 3 consecutive losses (24h) or 3 consecutive timeouts (4h)
    2. Churn Guard: Rolling PF < 0.80 restricts to 3 trades/day; Fee cap 0.75% equity
    3. Max Concurrent Open Positions Cap
    4. Max Total Exposure Cap (% of Bankroll)
    5. Sector Concentration Cap (e.g. Max 1 position per MEME_ROTATION coin)
    """
    def __init__(
        self,
        max_concurrent_positions: Optional[int] = None,
        max_total_exposure_pct: Optional[float] = None,
        max_positions_per_category: Optional[Dict[str, int]] = None,
        pair_quarantine: Optional[PairQuarantineManager] = None,
        churn_guard: Optional[ChurnGuard] = None,
    ):
        self.max_concurrent_positions = (
            max_concurrent_positions
            if max_concurrent_positions is not None
            else settings.MAX_CONCURRENT_POSITIONS
        )
        self.max_total_exposure_pct = (
            max_total_exposure_pct
            if max_total_exposure_pct is not None
            else settings.MAX_TOTAL_EXPOSURE_PCT
        )
        self.max_positions_per_category: Dict[str, int] = max_positions_per_category or {
            "MEME_ROTATION": 1,
            "LOCAL_MOMENTUM": 1,
            "AVOID_STABLE": 0,
            "UNKNOWN": 0,
        }
        self.pair_quarantine = pair_quarantine or PairQuarantineManager()
        self.churn_guard = churn_guard or ChurnGuard()

        self.total_evaluations: int = 0
        self.total_rejections: int = 0
        logger.info(
            f"[CapitalGovernor] Initialized with Max Concurrent Positions: {self.max_concurrent_positions}, "
            f"Max Total Exposure: {self.max_total_exposure_pct:.1f}%, "
            f"Sector Limits: {self.max_positions_per_category}"
        )

    def evaluate_order_allocation(
        self,
        symbol: str,
        notional_idr: float,
        current_open_positions_count: int,
        current_open_exposure_idr: float,
        total_equity_idr: float,
        open_positions_symbols: Optional[List[str]] = None,
        trade_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether adding the requested new position complies with portfolio governance.
        Returns:
            (is_allowed: bool, reason: str)
        """
        self.total_evaluations += 1

        # 1. Check Pair Quarantine (Phase 3: Consecutive losses/timeouts & blacklist)
        is_quar, quar_reason = self.pair_quarantine.is_quarantined(symbol)
        if is_quar:
            self.total_rejections += 1
            reason = f"BLOCKED: Symbol {symbol} is quarantined ({quar_reason})."
            logger.warning(f"[CapitalGovernor] 🛑 {reason}")
            return False, reason

        # 2. Check Churn Guard (Phase 3: Rolling PF < 0.80 & Daily Fee Cap 0.75%)
        is_cg_ok, cg_reason = self.churn_guard.evaluate_entry_allowed(
            trade_history=trade_history or [],
            current_equity_idr=total_equity_idr,
        )
        if not is_cg_ok:
            self.total_rejections += 1
            reason = f"BLOCKED: {cg_reason}"
            logger.warning(f"[CapitalGovernor] 🛑 {reason}")
            return False, reason

        # 3. Check Max Concurrent Open Positions
        if current_open_positions_count >= self.max_concurrent_positions:
            self.total_rejections += 1
            reason = (
                f"BLOCKED: Max concurrent positions limit ({self.max_concurrent_positions}) reached. "
                f"Currently open: {current_open_positions_count} positions. Cannot open {symbol}."
            )
            logger.warning(f"[CapitalGovernor] 🛑 {reason}")
            return False, reason

        # 4. Check Total Capital Exposure Cap
        projected_exposure_idr = current_open_exposure_idr + notional_idr
        if total_equity_idr > 0:
            projected_exposure_pct = (projected_exposure_idr / total_equity_idr) * 100.0
        else:
            projected_exposure_pct = 100.0

        if projected_exposure_pct > self.max_total_exposure_pct:
            self.total_rejections += 1
            reason = (
                f"BLOCKED: Projected exposure {projected_exposure_pct:.1f}% exceeds limit "
                f"{self.max_total_exposure_pct:.1f}% "
                f"(Current: Rp {current_open_exposure_idr:,.0f}, Adding: Rp {notional_idr:,.0f}, "
                f"Projected: Rp {projected_exposure_idr:,.0f} / Total: Rp {total_equity_idr:,.0f})."
            )
            logger.warning(f"[CapitalGovernor] 🛑 {reason}")
            return False, reason

        # 5. Sector Diversification Check (coin_category.py integration)
        cand_cat = get_coin_category(symbol)
        cat_policy = classify_coin_category(symbol)
        if not cat_policy.get("allowed", True):
            self.total_rejections += 1
            reason = f"BLOCKED: Sector '{cand_cat}' is not allowed for trading ({cat_policy.get('reason')})."
            logger.warning(f"[CapitalGovernor] 🛑 {reason}")
            return False, reason

        if open_positions_symbols:
            cat_limit = self.max_positions_per_category.get(cand_cat, self.max_concurrent_positions)
            matching_open = [s for s in open_positions_symbols if get_coin_category(s) == cand_cat]
            if len(matching_open) >= cat_limit:
                self.total_rejections += 1
                reason = (
                    f"BLOCKED: Sector concentration limit reached for category '{cand_cat}' "
                    f"(Max allowed: {cat_limit}, currently open: {len(matching_open)} [{', '.join(matching_open)}]). "
                    f"Cannot open {symbol}."
                )
                logger.warning(f"[CapitalGovernor] 🛑 {reason}")
                return False, reason

        return True, "APPROVED_BY_CAPITAL_GOVERNOR"

    def on_trade_closed(
        self,
        symbol: str,
        realized_pnl_idr: float,
        exit_reason: str,
        fee_idr: float = 0.0,
    ) -> None:
        """
        Informs risk subsystems of closed trade results.
        Updates consecutive loss/timeout counters in PairQuarantine and daily metrics in ChurnGuard.
        """
        self.pair_quarantine.record_trade_result(symbol, realized_pnl_idr, exit_reason)
        self.churn_guard.record_trade_closed(realized_pnl_idr, fee_idr)

    def state_dict(self) -> Dict[str, Any]:
        return {
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_total_exposure_pct": self.max_total_exposure_pct,
            "total_evaluations": self.total_evaluations,
            "total_rejections": self.total_rejections,
            "pair_quarantine": self.pair_quarantine.state_dict(),
            "churn_guard": self.churn_guard.state_dict(),
        }

    def load_state(self, state: Dict[str, Any]) -> None:
        self.total_evaluations = state.get("total_evaluations", 0)
        self.total_rejections = state.get("total_rejections", 0)
        if "pair_quarantine" in state:
            self.pair_quarantine.load_state(state["pair_quarantine"])
        if "churn_guard" in state:
            self.churn_guard.load_state(state["churn_guard"])
