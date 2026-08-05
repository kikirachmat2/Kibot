"""Paper Trade Tracker — realistic virtual execution for PAPER_ONLY candidates.

Accumulates historical performance data safely without real capital risk.
Features:
- Fee-aware PnL calculation (default 0.3% roundtrip fee).
- Realistic exit rules (Stop Loss -1.5%, Take Profit +2.0%, Max Hold 2 Hours).
- Completely isolated from live order endpoints (reads public price ticker only).
- Persists open positions to state/paper_trades/open/<trade_id>.json.
- Appends closed positions to state/trade_history/paper_<date>.jsonl with is_paper=True.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("KiBot.PaperTradeTracker")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT_DIR / "state"
PAPER_OPEN_DIR = STATE_DIR / "paper_trades" / "open"
TRADE_HISTORY_DIR = STATE_DIR / "trade_history"
WIB_TZ = timezone(timedelta(hours=7))

from Core.Support.ki_config import KiConfig

DEFAULT_FEE_PCT = KiConfig.INDODAX_TAKER_BUY_FEE_PCT  # 0.31% single-leg taker fee (Indodax official)
DEFAULT_SLIPPAGE_PCT = KiConfig.KIBOT_DEFAULT_SLIPPAGE_PCT  # 0.10% slippage
MIN_NET_RR_BUFFER = 1.60  # Must be >= 1.6 to safely pass MIN_RR_RATIO (1.5) in compute_ev
DEFAULT_PAPER_BANKROLL_IDR = float(os.getenv("KIBOT_PAPER_BANKROLL_IDR", "5000000.0"))  # Rp 5,000,000 IDR paper balance
DEFAULT_PAPER_TRADE_SIZE_IDR = float(os.getenv("KIBOT_PAPER_TRADE_SIZE_IDR", "250000.0")) # 5% per trade (Rp 250,000)


def compute_net_rr_ratio(
    take_profit_pct: float = 0.03,
    stop_loss_pct: float = 0.01,
    fee_pct: float = DEFAULT_FEE_PCT,
    slippage_pct: float = DEFAULT_SLIPPAGE_PCT,
) -> float:
    """Calculate net risk-to-reward ratio accounting for fee and slippage friction."""
    friction = fee_pct + slippage_pct
    net_win = max(0.0001, take_profit_pct - friction)
    net_loss = max(0.0001, stop_loss_pct + friction)
    return net_win / net_loss


def _now_wib() -> datetime:
    return datetime.now(WIB_TZ)


def _today_date_str() -> str:
    return _now_wib().strftime("%Y-%m-%d")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp.{os.getpid()}_{time.time()}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class PaperTradeTracker:
    def __init__(
        self,
        open_dir: Path = PAPER_OPEN_DIR,
        history_dir: Path = TRADE_HISTORY_DIR,
        fee_pct: float = KiConfig.KIBOT_TAKER_FEE_ROUNDTRIP_PCT,
        bankroll_idr: float = DEFAULT_PAPER_BANKROLL_IDR,
    ):
        self.open_dir = open_dir
        self.history_dir = history_dir
        self.fee_pct = fee_pct
        self.bankroll_idr = bankroll_idr
        self.open_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def open_paper_trade(
        self,
        candidate: Dict[str, Any],
        budget_idr: float = DEFAULT_PAPER_TRADE_SIZE_IDR,
        stop_loss_pct: float = 0.010,   # -1.0% stop loss
        take_profit_pct: float = 0.030, # +3.0% take profit
        max_hold_seconds: float = 7200.0,
    ) -> Optional[Dict[str, Any]]:
        """Open a virtual paper trade for a candidate with PAPER_ONLY verdict."""
        # Enforce safety check: Net R:R ratio must be >= 1.6
        net_rr = compute_net_rr_ratio(take_profit_pct, stop_loss_pct, DEFAULT_FEE_PCT)
        if net_rr < MIN_NET_RR_BUFFER:
            logger.warning(
                f"[PaperTrade] Cannot open trade: net R:R ratio {net_rr:.2f} is below minimum required buffer {MIN_NET_RR_BUFFER:.2f}"
            )
            return None
        pair = str(candidate.get("pair") or candidate.get("symbol") or "").upper().strip()
        if not pair:
            return None

        # Check if pair already has an active open paper trade to avoid spamming
        for existing in self.get_open_paper_trades():
            if existing.get("pair", "").upper() == pair:
                return None

        entry_price = float(candidate.get("price_idr") or candidate.get("price") or candidate.get("last_price") or 0.0)
        if entry_price <= 0:
            # Fallback price default
            entry_price = 100.0

        trade_id = f"paper_{pair.lower().replace('/', '_')}_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        now = time.time()
        now_iso = _now_wib().isoformat()

        stop_loss_price = entry_price * (1.0 - stop_loss_pct)
        take_profit_price = entry_price * (1.0 + take_profit_pct)

        trade_record = {
            "trade_id": trade_id,
            "is_paper": True,
            "pair": pair,
            "symbol": pair,
            "strategy_id": str(candidate.get("strategy_id") or candidate.get("pattern") or "STANDARD"),
            "pattern": str(candidate.get("pattern") or candidate.get("stage") or "STANDARD"),
            "entry_price_idr": entry_price,
            "entry_time_ts": now,
            "entry_time_wib": now_iso,
            "budget_idr": budget_idr,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "max_hold_seconds": max_hold_seconds,
            "expire_ts": now + max_hold_seconds,
            "status": "OPEN",
            "scorecard_verdict": candidate.get("scorecard_verdict", "PAPER_ONLY"),
            "scorecard": candidate.get("scorecard", {}),
            "ev_analysis": candidate.get("ev_analysis", {}),
        }

        filepath = self.open_dir / f"{trade_id}.json"
        _atomic_write_json(filepath, trade_record)
        logger.info(f"[PaperTrade] Opened virtual position for {pair} at {entry_price:.2f} IDR (ID: {trade_id})")
        return trade_record

    def get_open_paper_trades(self) -> List[Dict[str, Any]]:
        """Retrieve all currently open paper trades."""
        trades: List[Dict[str, Any]] = []
        if not self.open_dir.exists():
            return trades
        for filepath in self.open_dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("status") == "OPEN":
                    trades.append(data)
            except Exception:
                pass
        return trades

    def evaluate_open_trades(self, price_map: Dict[str, float]) -> List[Dict[str, Any]]:
        """Evaluate open paper trades against current market prices and close triggered positions."""
        closed_trades: List[Dict[str, Any]] = []
        now = time.time()

        for trade in self.get_open_paper_trades():
            pair = trade.get("pair", "").upper()
            pair_slash = pair.replace("_", "/")
            pair_underscore = pair.replace("/", "_")

            current_price = price_map.get(pair) or price_map.get(pair_slash) or price_map.get(pair_underscore)
            entry_price = float(trade.get("entry_price_idr", 0.0))
            stop_price = float(trade.get("stop_loss_price", 0.0))
            tp_price = float(trade.get("take_profit_price", 0.0))
            expire_ts = float(trade.get("expire_ts", 0.0))

            should_close = False
            exit_reason = ""
            exit_price = current_price if current_price and current_price > 0 else entry_price

            if current_price and current_price > 0:
                # Dynamic Trailing Stop Ratchet: raise stop loss as price ascends
                if current_price > entry_price and entry_price > 0:
                    profit_pct = ((current_price - entry_price) / entry_price) * 100.0
                    try:
                        from Core.Intelligence.exit_plan import DEFAULT_TRAILING_SCHEDULE
                        best_new_stop = stop_price
                        for threshold_pct, buffer_pct in DEFAULT_TRAILING_SCHEDULE:
                            if profit_pct >= threshold_pct:
                                calculated_stop = entry_price * (1.0 + ((threshold_pct - buffer_pct) / 100.0))
                                if calculated_stop > best_new_stop:
                                    best_new_stop = calculated_stop
                        if best_new_stop > stop_price:
                            trade["stop_loss_price"] = best_new_stop
                            stop_price = best_new_stop
                            trade_file = self.open_dir / f"{trade.get('trade_id')}.json"
                            if trade_file.exists():
                                _atomic_write_json(trade_file, trade)
                    except Exception:
                        pass

                if current_price <= stop_price:
                    should_close = True
                    exit_reason = "STOP_LOSS_BREACHED"
                elif current_price >= tp_price:
                    should_close = True
                    exit_reason = "TAKE_PROFIT_TARGET_HIT"

            if not should_close and now >= expire_ts:
                should_close = True
                exit_reason = "MAX_HOLD_TIME_EXPIRED"

            if should_close:
                closed_record = self.close_paper_trade(trade, exit_price=exit_price, exit_reason=exit_reason)
                if closed_record:
                    closed_trades.append(closed_record)

        return closed_trades

    def close_paper_trade(
        self,
        trade: Dict[str, Any],
        exit_price: float,
        exit_reason: str,
    ) -> Dict[str, Any]:
        """Close a paper trade, compute fee-aware PnL, save to paper trade history, and remove open file."""
        trade_id = trade.get("trade_id")
        entry_price = float(trade.get("entry_price_idr", 1.0))
        if entry_price <= 0:
            entry_price = 1.0

        # Calculate gross & net fee-aware PnL
        gross_pct = (exit_price - entry_price) / entry_price
        net_pct = gross_pct - self.fee_pct  # Subtract roundtrip fee

        budget_idr = float(trade.get("budget_idr", 10000.0))
        net_pnl_idr = budget_idr * net_pct

        now_iso = _now_wib().isoformat()
        date_str = _today_date_str()

        closed_record = {
            "event_type": "ORDER_RECONCILED",
            "trade_event_type": "ORDER_RECONCILED",
            "is_paper": True,
            "trade_id": trade_id,
            "pair": trade.get("pair"),
            "symbol": trade.get("symbol"),
            "strategy_id": trade.get("strategy_id"),
            "pattern": trade.get("pattern"),
            "side": "BUY",
            "state": "RECONCILED",
            "status": "CLOSED",
            "entry_price_idr": entry_price,
            "exit_price_idr": exit_price,
            "amount_idr": budget_idr,
            "realized_pnl_idr": round(net_pnl_idr, 2),
            "realized_pnl_pct": round(net_pct * 100.0, 4),  # % format
            "fee_pct": self.fee_pct,
            "exit_reason": exit_reason,
            "entry_time_wib": trade.get("entry_time_wib"),
            "exit_time_wib": now_iso,
            "timestamp_wib": now_iso,
            "date_wib": date_str,
        }

        # 1. Append to state/trade_history/paper_<date>.jsonl
        history_file = self.history_dir / f"paper_{date_str}.jsonl"
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(closed_record, ensure_ascii=False) + "\n")

        # 1b. Update cumulative paper equity curve file (state/paper_equity.json)
        try:
            equity_file = STATE_DIR / "paper_equity.json"
            eq_data = {
                "initial_bankroll_idr": self.bankroll_idr,
                "current_equity_idr": self.bankroll_idr,
                "total_pnl_idr": 0.0,
                "total_paper_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "updated_at": now_iso,
            }
            if equity_file.exists():
                try:
                    eq_data = json.loads(equity_file.read_text(encoding="utf-8"))
                except Exception:
                    pass

            eq_data["total_paper_trades"] = int(eq_data.get("total_paper_trades", 0)) + 1
            if net_pnl_idr > 0:
                eq_data["winning_trades"] = int(eq_data.get("winning_trades", 0)) + 1
            elif net_pnl_idr < 0:
                eq_data["losing_trades"] = int(eq_data.get("losing_trades", 0)) + 1

            total_trades = eq_data["total_paper_trades"]
            wins = eq_data["winning_trades"]
            eq_data["win_rate_pct"] = round((wins / total_trades) * 100.0, 2) if total_trades > 0 else 0.0
            eq_data["total_pnl_idr"] = round(float(eq_data.get("total_pnl_idr", 0.0)) + net_pnl_idr, 2)
            eq_data["current_equity_idr"] = round(float(eq_data.get("initial_bankroll_idr", self.bankroll_idr)) + eq_data["total_pnl_idr"], 2)
            eq_data["updated_at"] = now_iso

            _atomic_write_json(equity_file, eq_data)
        except Exception as err:
            logger.warning(f"[PaperTrade] Failed to update paper equity curve file: {err}")

        # 2. Delete open position file
        open_file = self.open_dir / f"{trade_id}.json"
        if open_file.exists():
            try:
                open_file.unlink()
            except Exception as e:
                logger.warning(f"Error removing paper open trade file {open_file}: {e}")

        # 3. Trigger immediate strategy stats refresh & graduation check
        try:
            from Core.Intelligence.strategy_stats import get_stats_aggregator
            get_stats_aggregator().refresh_if_needed(force=True)
        except Exception as e:
            logger.warning(f"Failed to refresh strategy stats on paper trade close: {e}")

        # 4. Feed to Bayesian KiBot Learning Engine
        try:
            from Core.Intelligence.kibot_learning_engine import get_engine
            learning = get_engine()
            pair_key = str(trade.get("pair") or "").lower().replace("/", "_")
            won = net_pnl_idr > 0
            learning.record_trade(pair_key, net_pct, regime=trade.get("pattern", "NORMAL"), won=won, pnl_idr=net_pnl_idr)
            logger.info(f"[PaperTrade] Recorded paper trade to Bayesian learning engine: {pair_key} PnL={net_pnl_idr:+.2f} IDR")
        except Exception as e:
            logger.warning(f"[PaperTrade] Learning engine update failed: {e}")

        # 5. Feed to Pair Quarantine System
        try:
            from Core.Intelligence.pair_quarantine import record_pair_outcome
            pair_display = str(trade.get("pair") or "")
            quarantined = record_pair_outcome(pair_display, net_pnl_idr)
            if quarantined:
                logger.warning(f"[PaperTrade] Pair {pair_display} QUARANTINED after consecutive paper losses")
        except Exception as e:
            logger.warning(f"[PaperTrade] Pair quarantine update failed: {e}")

        logger.info(
            f"[PaperTrade] Closed virtual position for {trade.get('pair')} — Reason: {exit_reason}, PnL: {net_pnl_idr:+.2f} IDR ({net_pct*100:+.2f}%)"
        )
        return closed_record


_tracker_instance: Optional[PaperTradeTracker] = None


def get_paper_trade_tracker() -> PaperTradeTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = PaperTradeTracker()
    return _tracker_instance
