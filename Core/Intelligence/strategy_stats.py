"""Strategy Statistics Aggregator — calculates rolling historical stats for EV calculations.

SINGLE SOURCE OF TRUTH (SSOT):
This module is the canonical Single Source of Truth for live trading execution gates,
EV calculations, and strategy graduation decisions across KiBot.
All live trading gates and EV evaluations must derive from StrategyStatsAggregator.

Reads state/trade_history/*.jsonl and state/orders/*.json to compute:
- sample_size (total_trades)
- win_rate (fraction 0.0 - 1.0)
- avg_profit_pct (fraction > 0, e.g. 0.02 = 2%)
- avg_loss_pct (fraction > 0, e.g. 0.01 = 1%)

Maintains an in-memory cache refreshed periodically (default: 300s).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from Core.Intelligence.expected_value import compute_ev

logger = logging.getLogger("KiBot.StrategyStats")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT_DIR / "state"
TRADE_HISTORY_DIR = STATE_DIR / "trade_history"
ORDERS_DIR = STATE_DIR / "orders"

CACHE_TTL_SECONDS = 300.0  # 5 minutes


@dataclass
class StrategyMetrics:
    total_trades: int = 0
    sample_size_live: int = 0
    sample_size_paper: int = 0
    total_wins: int = 0
    total_losses: int = 0
    win_rate: float = 0.0
    avg_profit_pct: float = 0.0
    avg_loss_pct: float = 0.0
    insufficient_data: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "historical_sample_size": self.total_trades,
            "sample_size": self.total_trades,
            "sample_size_live": self.sample_size_live,
            "sample_size_paper": self.sample_size_paper,
            "win_rate": self.win_rate,
            "avg_profit_pct": self.avg_profit_pct,
            "avg_loss_pct": self.avg_loss_pct,
            "insufficient_data": self.insufficient_data,
        }


class StrategyStatsAggregator:
    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._last_refresh: float = 0.0
        self._cache: Dict[str, StrategyMetrics] = {}
        self._variant_cache: Dict[str, Dict[str, StrategyMetrics]] = {}  # variant_id -> {key -> metrics}
        self._global_metrics: StrategyMetrics = StrategyMetrics(insufficient_data=True)

    def get_metrics_for_candidate(self, candidate: Dict[str, Any], variant_id: Optional[str] = None) -> Tuple[StrategyMetrics, bool]:
        """Look up metrics matching candidate keys (strategy_id, pattern, pair).

        Returns:
            Tuple of (metrics, is_specific_match)
        """
        self.refresh_if_needed()
        keys_to_try = [
            str(candidate.get("strategy_id") or "").strip(),
            str(candidate.get("pattern") or candidate.get("stage") or "").strip(),
            str(candidate.get("pair") or candidate.get("symbol") or "").strip().upper().replace("_", "/"),
            str(candidate.get("pair") or candidate.get("symbol") or "").strip().upper().replace("/", "_"),
        ]
        
        target_cache = self._cache
        if variant_id and variant_id.upper().strip() in self._variant_cache:
            target_cache = self._variant_cache[variant_id.upper().strip()]

        for key in keys_to_try:
            if key and key in target_cache and key != "_GLOBAL_" and target_cache[key].total_trades > 0:
                return target_cache[key], True

        if variant_id and variant_id.upper().strip() in self._variant_cache:
            v_global = self._variant_cache[variant_id.upper().strip()].get("_GLOBAL_")
            if v_global:
                return v_global, False

        return self._global_metrics, False

    def get_variant_summary(self, variant_id: str) -> StrategyMetrics:
        """Get overall metrics for a specific variant_id."""
        self.refresh_if_needed()
        v_key = variant_id.upper().strip()
        if v_key in self._variant_cache:
            return self._variant_cache[v_key].get("_GLOBAL_", StrategyMetrics(insufficient_data=True))
        return StrategyMetrics(insufficient_data=True)

    def inject_stats(self, candidate: Dict[str, Any], variant_id: Optional[str] = None) -> Dict[str, Any]:
        """Inject historical statistics directly into the candidate dict."""
        metrics, is_specific_match = self.get_metrics_for_candidate(candidate, variant_id=variant_id)
        candidate["historical_sample_size"] = metrics.total_trades
        candidate["sample_size"] = metrics.total_trades
        candidate["sample_size_live"] = metrics.sample_size_live
        candidate["sample_size_paper"] = metrics.sample_size_paper
        candidate["win_rate"] = metrics.win_rate
        candidate["avg_profit_pct"] = metrics.avg_profit_pct
        candidate["avg_loss_pct"] = metrics.avg_loss_pct
        candidate["is_specific_match"] = is_specific_match
        candidate["insufficient_data"] = metrics.insufficient_data or not is_specific_match
        return candidate

    def refresh_if_needed(self, force: bool = False) -> None:
        now = time.time()
        if force or (now - self._last_refresh) >= self.ttl_seconds or not self._cache:
            self._rebuild_cache()
            self._last_refresh = now

    def _rebuild_cache(self) -> None:
        stats_acc: Dict[str, Dict[str, Any]] = {}
        variant_stats_acc: Dict[str, Dict[str, Dict[str, Any]]] = {}  # variant_id -> key -> acc

        def _init_acc() -> Dict[str, Any]:
            return {"wins": [], "losses": [], "total": 0, "live_count": 0, "paper_count": 0}

        def _record_trade(key: str, pnl_pct: float, is_paper: bool = False, variant_id: str = "DEFAULT") -> None:
            if not key:
                return
            acc = stats_acc.setdefault(key, _init_acc())
            acc["total"] += 1
            if is_paper:
                acc["paper_count"] += 1
            else:
                acc["live_count"] += 1

            if pnl_pct > 0:
                acc["wins"].append(pnl_pct)
            elif pnl_pct < 0:
                acc["losses"].append(abs(pnl_pct))

            # Record per variant
            v_key = (variant_id or "DEFAULT").upper().strip()
            v_dict = variant_stats_acc.setdefault(v_key, {})
            v_acc = v_dict.setdefault(key, _init_acc())
            v_acc["total"] += 1
            if is_paper:
                v_acc["paper_count"] += 1
            else:
                v_acc["live_count"] += 1

            if pnl_pct > 0:
                v_acc["wins"].append(pnl_pct)
            elif pnl_pct < 0:
                v_acc["losses"].append(abs(pnl_pct))

        # 1. Scan trade_history directory (*.jsonl including paper_*.jsonl)
        if TRADE_HISTORY_DIR.exists():
            for filepath in TRADE_HISTORY_DIR.glob("*.jsonl"):
                is_paper_file = filepath.name.startswith("paper_")
                try:
                    for line in filepath.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        st = str(row.get("state") or row.get("status") or "").upper()
                        evt = str(row.get("event_type") or row.get("trade_event_type") or "").upper()
                        if st == "RECONCILED" or evt in ("ORDER_RECONCILED", "SELL_FILLED", "EXIT_FILLED"):
                            # Filter corrupt/invalid valuation trades retroactively
                            exit_reason = str(row.get("exit_reason") or "").upper()
                            entry_px = float(row.get("entry_price_idr") or 0.0)
                            exit_px = float(row.get("exit_price_idr") or 0.0)
                            is_invalid = bool(row.get("is_invalid_valuation")) or exit_reason == "TIMEOUT_PRICE_UNAVAILABLE" or (exit_reason == "MAX_HOLD_TIME_EXPIRED" and entry_px > 0 and entry_px == exit_px)
                            if is_invalid:
                                continue

                            pnl_pct = float(row.get("realized_pnl_pct") or row.get("pnl_pct") or 0.0)
                            if abs(pnl_pct) >= 0.05:  # Convert % format to decimal fraction
                                pnl_pct = pnl_pct / 100.0

                            is_paper = is_paper_file or bool(row.get("is_paper"))
                            row_variant = str(row.get("variant_id") or "DEFAULT").upper().strip()
                            if is_paper_file and row_variant == "DEFAULT":
                                # Extract variant from filename if paper_<variant>_<date>.jsonl
                                parts = filepath.stem.split("_")
                                if len(parts) >= 3 and parts[0] == "paper":
                                    row_variant = parts[1].upper()

                            pair = str(row.get("pair") or row.get("symbol") or "").upper().strip()
                            pair_slash = pair.replace("_", "/")
                            pair_underscore = pair.replace("/", "_")
                            strat = str(row.get("strategy_id") or row.get("trade_profile") or "").strip()
                            pattern = str(row.get("trade_grade") or row.get("pattern") or "").strip()

                            _record_trade(pair_slash, pnl_pct, is_paper=is_paper, variant_id=row_variant)
                            _record_trade(pair_underscore, pnl_pct, is_paper=is_paper, variant_id=row_variant)
                            _record_trade(strat, pnl_pct, is_paper=is_paper, variant_id=row_variant)
                            _record_trade(pattern, pnl_pct, is_paper=is_paper, variant_id=row_variant)
                            _record_trade("_GLOBAL_", pnl_pct, is_paper=is_paper, variant_id=row_variant)
                except Exception as e:
                    logger.warning(f"Error reading trade history {filepath}: {e}")

        # 2. Scan orders directory (*.json)
        if ORDERS_DIR.exists():
            for filepath in ORDERS_DIR.glob("*.json"):
                if filepath.name == "_index.json":
                    continue
                try:
                    order = json.loads(filepath.read_text(encoding="utf-8"))
                    st = str(order.get("state") or order.get("status") or "").upper()
                    if st in ("RECONCILED", "FILLED", "CLOSED"):
                        pnl_idr = float(order.get("pnl_idr") or 0.0)
                        pnl_pct = float(order.get("pnl_pct") or 0.0)
                        if pnl_pct != 0.0:
                            pnl_val = pnl_pct / 100.0 if abs(pnl_pct) >= 0.05 else pnl_pct
                        elif pnl_idr != 0.0 and float(order.get("budget_idr") or 0.0) > 0:
                            pnl_val = pnl_idr / float(order["budget_idr"])
                        else:
                            continue

                        pair = str(order.get("pair") or order.get("symbol") or "").upper().strip()
                        pair_slash = pair.replace("_", "/")
                        pair_underscore = pair.replace("/", "_")
                        strat = str(order.get("strategy_id") or order.get("trade_profile") or "").strip()

                        _record_trade(pair_slash, pnl_val, is_paper=False, variant_id="LIVE")
                        _record_trade(pair_underscore, pnl_val, is_paper=False, variant_id="LIVE")
                        _record_trade(strat, pnl_val, is_paper=False, variant_id="LIVE")
                        _record_trade("_GLOBAL_", pnl_val, is_paper=False, variant_id="LIVE")
                except Exception:
                    pass

        # Build StrategyMetrics objects
        def _acc_to_metrics(acc: Dict[str, Any]) -> StrategyMetrics:
            total = acc["total"]
            if total == 0:
                return StrategyMetrics(insufficient_data=True)
            wins = acc["wins"]
            losses = acc["losses"]
            win_rate = len(wins) / total
            avg_win = sum(wins) / len(wins) if wins else 0.005
            avg_loss = sum(losses) / len(losses) if losses else 0.02
            insufficient_data = (len(wins) == 0 or len(losses) == 0)
            return StrategyMetrics(
                total_trades=total,
                sample_size_live=acc.get("live_count", 0),
                sample_size_paper=acc.get("paper_count", 0),
                total_wins=len(wins),
                total_losses=len(losses),
                win_rate=win_rate,
                avg_profit_pct=avg_win,
                avg_loss_pct=avg_loss,
                insufficient_data=insufficient_data,
            )

        new_cache: Dict[str, StrategyMetrics] = {}
        for key, acc in stats_acc.items():
            if acc["total"] > 0:
                new_cache[key] = _acc_to_metrics(acc)

        new_variant_cache: Dict[str, Dict[str, StrategyMetrics]] = {}
        for v_key, keys_map in variant_stats_acc.items():
            v_dict: Dict[str, StrategyMetrics] = {}
            for k, acc in keys_map.items():
                if acc["total"] > 0:
                    v_dict[k] = _acc_to_metrics(acc)
            new_variant_cache[v_key] = v_dict

        self._cache = new_cache
        self._variant_cache = new_variant_cache
        self._global_metrics = new_cache.get("_GLOBAL_", StrategyMetrics(insufficient_data=True))
        logger.info(f"[StrategyStats] Cache rebuilt with {len(new_cache)} global keys and {len(new_variant_cache)} variants. Global sample size: {self._global_metrics.total_trades}")
        self.evaluate_and_update_graduations()
        self.evaluate_and_update_graduations()

    def evaluate_and_update_graduations(self) -> Dict[str, Any]:
        """Evaluate cache entries for live graduation using canonical compute_ev().

        Criteria:
        - GRADUATED_LIVE_READY: total_trades >= 20 and ev_res.approved is True
          (compute_ev handles EV >= 0.3%, RR ratio >= 1.5, Kelly floor >= 0.01 net of fee+slippage)
        - QUARANTINED: total_trades >= 10 and ev_res.ev_pct < -0.005 (-0.5%)
        """
        graduated: Dict[str, Any] = {}
        for key, metrics in self._cache.items():
            if key == "_GLOBAL_":
                continue
            ev_res = compute_ev(
                win_prob=metrics.win_rate,
                avg_win_pct=metrics.avg_profit_pct,
                avg_loss_pct=metrics.avg_loss_pct,
            )
            if metrics.total_trades >= 20 and ev_res.approved:
                graduated[key] = {
                    "status": "GRADUATED_LIVE_READY",
                    "sample_size": metrics.total_trades,
                    "win_rate": round(metrics.win_rate, 4),
                    "ev_pct": round(ev_res.ev_pct * 100.0, 4),
                    "kelly_fraction": round(ev_res.kelly_fraction, 4),
                    "rr_ratio": round(ev_res.rr_ratio, 3),
                    "graduated_at": time.time(),
                }
            elif metrics.total_trades >= 10 and ev_res.ev_pct < -0.005:
                graduated[key] = {
                    "status": "QUARANTINED",
                    "sample_size": metrics.total_trades,
                    "win_rate": round(metrics.win_rate, 4),
                    "ev_pct": round(ev_res.ev_pct * 100.0, 4),
                    "quarantined_at": time.time(),
                }

        grad_file = STATE_DIR / "graduated_strategies.json"
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            grad_file.write_text(json.dumps(graduated, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"[StrategyStats] Failed to save graduated strategies: {e}")
        return graduated


def is_strategy_graduated(key: str) -> bool:
    """Check if a strategy/pair key has graduated to LIVE_READY status."""
    grad_file = STATE_DIR / "graduated_strategies.json"
    if not grad_file.exists():
        return False
    try:
        data = json.loads(grad_file.read_text(encoding="utf-8"))
        entry = data.get(key) or data.get(key.upper()) or data.get(key.lower())
        if isinstance(entry, dict):
            return entry.get("status") == "GRADUATED_LIVE_READY"
    except Exception:
        pass
    return False


_aggregator: Optional[StrategyStatsAggregator] = None


def get_stats_aggregator() -> StrategyStatsAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = StrategyStatsAggregator()
    return _aggregator
