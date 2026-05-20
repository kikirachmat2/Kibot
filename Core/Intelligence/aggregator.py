import os
import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import httpx
import inspect

from pathlib import Path
from datetime import datetime, timedelta

from Core.Support.ki_config import WIB
from Core.Treasury.accounting_truth import build_accounting_truth

class CouncilDataAggregator:
    """
    Council Data Aggregator
    Consolidates data from across the KiBot ecosystem to provide context for the Trading Council sessions.
    
    Data sources:
    - FastPathLogger (Signal History)
    - WhatIfTracker (Audit Results)
    - KiBotMaster State (Portfolio, Mesh Health)
    - Market Sentiment (Brain)
    """
    def __init__(self, master_node):
        self.master = master_node
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.fast_path_log = base_dir / "Logs" / "fast_path_signals.jsonl"
        self.what_if_log = base_dir / "Logs" / "what_if_analysis.json"

    async def get_debate_context(self, tier="TIER_1_SYNC"):
        """
        Builds a comprehensive data snapshot for a council session.
        """
        rejection_stats = self._get_fast_path_stats()
        missed_opps = self._get_missed_opportunities()
        portfolio = await self._get_portfolio_snapshot()
        market = await self._get_market_context()
        
        # Collect unique pairs from audit
        unique_pairs = set()
        for opp in missed_opps:
            unique_pairs.add(opp.get("symbol"))
            
        context = {
            "session_tier": tier,
            "timestamp": datetime.now().isoformat(),
            "philosophy": {
                "core": "Sedikit Demi Sedikit, Lama-Lama Jadi Bukit",
                "rules": [
                    "Capital preservation first",
                    "Profit probability > 85%",
                    "Early TP at 0.5%"
                ]
            },
            "market_context": market,
            "portfolio_state": portfolio,
            "audit_data": {
                "rejection_analysis": rejection_stats,
                "missed_opportunities": missed_opps
            },
            "pair_memory": self._get_pair_memory(list(unique_pairs)),
            "council_history": self._get_council_history(),
            "system_health": self.master.last_state.get("mesh_nodes", {})
        }
        return context

    def _get_pair_memory(self, signal_pairs: list) -> dict:
        memory = {}
        try:
            from Core.Intelligence.kibot_learning_engine import get_engine
            engine = get_engine()
            for pair in signal_pairs:
                # Basic health and stats
                memory[pair] = engine.get_pair_stats(pair)
        except Exception:
            pass
        return memory

    def _get_council_history(self) -> list:
        history = []
        try:
            base_dir = Path(__file__).resolve().parent.parent
            path = base_dir / "Logs" / "council_directives.json"
            if path.exists():
                with open(path, "r") as f:
                    directives = json.load(f)
                    # Return last 3 directives for context
                    history = directives[-3:] if isinstance(directives, list) else []
        except Exception:
            pass
        return history

    def _get_fast_path_stats(self, hours=24):
        """Analyzes recent signal rejections."""
        stats = {"total": 0, "vetoed": 0, "math_skipped": 0, "approved": 0, "reasons": {}}
        cutoff = datetime.now() - timedelta(hours=hours)
        
        if not self.fast_path_log.exists():
            return stats
            
        try:
            with open(self.fast_path_log, "r") as f:
                for line in f:
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"])
                    if ts < cutoff: continue
                    
                    stats["total"] += 1
                    status = entry["status"]
                    if status == "APPROVED": stats["approved"] += 1
                    elif status == "VETOED": stats["vetoed"] += 1
                    elif status == "MATH_SKIP": stats["math_skipped"] += 1
                    
                    reason = entry["reason"]
                    stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
        except Exception as e:
            print(f"ERROR [Aggregator]: Rejection analysis failed: {e}")
            
        return stats

    def _get_missed_opportunities(self):
        """Extracts significant missed gains from what-if analysis."""
        opportunities = []
        if not self.what_if_log.exists():
            return opportunities
            
        try:
            with open(self.what_if_log, "r") as f:
                data = json.load(f)
                for tid, track in data.items():
                    # Only report opportunities that gained > 1% but were rejected
                    if track.get("max_gain_pct", 0) > 1.0:
                        opportunities.append({
                            "symbol": track["symbol"],
                            "reason": track["reason"],
                            "gain_missed": f"{track['max_gain_pct']:.2f}%",
                            "entry_price": track["entry_price"]
                        })
        except Exception as e:
            print(f"ERROR [Aggregator]: Missed opportunity analysis failed: {e}")
            
        return sorted(opportunities, key=lambda x: x["gain_missed"], reverse=True)[:5]

    def _load_state_json(self, name: str, default):
        path = ROOT_DIR / "state" / name
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return default

    def _coin_from_pair(self, pair: str) -> str:
        raw = str(pair or "").strip().lower()
        if "/" in raw:
            return raw.split("/", 1)[0]
        if "_" in raw:
            return raw.split("_", 1)[0]
        return raw.replace("idr", "")

    def _realized_daily_pnl_idr(self) -> float:
        risk_state = self._load_state_json("risk_state.json", {})
        if not isinstance(risk_state, dict):
            return 0.0
        today = datetime.now(WIB).strftime("%Y-%m-%d")
        state_date = str(risk_state.get("last_reset_date") or "")
        if state_date and state_date != today:
            return 0.0
        try:
            return float(risk_state.get("daily_pnl", 0.0) or 0.0)
        except Exception:
            return 0.0

    def _active_trade_unrealized_pnl(self, active_positions: list) -> dict:
        active_trades = self._load_state_json("active_trades.json", {})
        if not isinstance(active_trades, dict):
            return {"unrealized_pnl_idr": 0.0, "position_cost_basis_idr": 0.0, "positions": []}

        values_by_coin = {}
        for position in active_positions:
            if not isinstance(position, dict):
                continue
            coin = str(position.get("coin") or position.get("symbol") or "").lower().strip()
            if not coin or coin == "idr":
                continue
            try:
                values_by_coin[coin] = {
                    "amount": float(position.get("amount", 0.0) or 0.0),
                    "price_idr": float(position.get("price_idr", 0.0) or 0.0),
                    "value_idr": float(position.get("value_idr", 0.0) or 0.0),
                }
            except Exception:
                continue

        total_pnl = 0.0
        total_cost = 0.0
        details = []
        for pair, trade in active_trades.items():
            if not isinstance(trade, dict):
                continue
            coin = self._coin_from_pair(pair)
            if not coin:
                continue
            try:
                cost = float(trade.get("cost") or trade.get("budget_idr") or trade.get("notional_idr") or 0.0)
                amount = float(trade.get("amount", 0.0) or 0.0)
            except Exception:
                continue
            if cost <= 0:
                continue
            position = values_by_coin.get(coin, {})
            current_value = float(position.get("value_idr", 0.0) or 0.0)
            current_price = float(position.get("price_idr", 0.0) or 0.0)
            if current_value <= 0.0 and amount > 0.0 and current_price > 0.0:
                current_value = amount * current_price
            pnl = current_value - cost
            total_pnl += pnl
            total_cost += cost
            details.append({
                "pair": str(pair).upper(),
                "cost_idr": round(cost, 0),
                "current_value_idr": round(current_value, 0),
                "unrealized_pnl_idr": round(pnl, 0),
                "current_price_idr": current_price,
            })

        return {
            "unrealized_pnl_idr": total_pnl,
            "position_cost_basis_idr": total_cost,
            "positions": details,
        }

    async def _get_portfolio_snapshot(self):
        """Gets current holdings and PnL from live exchange/state endpoints."""
        snapshot = {
            "equity_idr": 0.0,
            "idr_cash": 0.0,
            "coin_holdings_idr": 0.0,
            "pnl_idr": 0.0,
            "return_pct": 0.0,
            "daily_pnl_idr": 0.0,
            "daily_pnl_pct": 0.0,
            "active_positions": [],
            "combined_equity_idr": 0.0,
            "source": "live",
            "polymarket": {
                "usdc_balance": 0.0,
                "equity_idr": 0.0,
                "pnl_idr": 0.0,
                "daily_pnl_usd": 0.0,
                "daily_pnl_idr": 0.0,
                "active_positions": [],
                "active_bets": [],
            },
        }

        idr_cash = 0.0
        idr_balance = 0.0
        coin_holdings_value_idr = 0.0
        active_positions = []
        try:
            info = await self.master.indodax.get_info()
            if info.get("success") == 1:
                balances = info.get("return", {}).get("balance", {})
                idr_cash = float(balances.get("idr", 0) or 0)
                held_coins = []
                for coin, amount in balances.items():
                    if coin == "idr":
                        continue
                    try:
                        amt = float(amount)
                    except Exception:
                        continue
                    if amt > 1e-6:
                        held_coins.append({"coin": coin, "amount": amt})

                if held_coins:
                    import asyncio

                    async def get_coin_value(coin_data):
                        coin = coin_data["coin"]
                        amount = coin_data["amount"]
                        try:
                            ticker = await self.master.indodax.get_ticker(f"{coin}_idr")
                            price = float(ticker.get("last", 0) or 0)
                            value_idr = amount * price
                            return {
                                "coin": coin,
                                "amount": amount,
                                "price_idr": price,
                                "value_idr": round(value_idr, 0),
                            }
                        except Exception:
                            return {
                                "coin": coin,
                                "amount": amount,
                                "price_idr": 0.0,
                                "value_idr": 0.0,
                            }

                    results = await asyncio.gather(
                        *[get_coin_value(coin_data) for coin_data in held_coins],
                        return_exceptions=True,
                    )
                    for result in results:
                        if isinstance(result, dict):
                            if result.get("value_idr", 0) > 0:
                                coin_holdings_value_idr += float(result["value_idr"])
                            active_positions.append(result)

                idr_balance = idr_cash + coin_holdings_value_idr
        except Exception as e:
            print(f"ERROR [Aggregator]: Indodax balance fetch failed: {e}")

        phantom_state = self._load_state_json("phantom_treasury.json", {})
        phantom_equity_idr = 0.0
        if isinstance(phantom_state, dict):
            phantom_equity_idr = _safe_float(
                phantom_state.get("total_value_idr"),
                _safe_float(phantom_state.get("chains", {}).get("base", {}).get("value_idr"), 0.0),
            )

        poly_state = {}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get("http://127.0.0.1:11600/api/state")
                if resp.status_code == 200:
                    poly_state = resp.json() or {}
        except Exception:
            poly_state = {}

        if not poly_state:
            try:
                poly_state = dict(self.master.last_state.get("polymarket", {}) or {})
            except Exception:
                poly_state = {}

        usdc_balance = float(poly_state.get("usdc_balance", 0) or 0)
        usd_idr_rate = float(os.getenv("USD_IDR_RATE", "16000"))
        poly_daily_pnl_usd = float(poly_state.get("daily_pnl_usd", 0) or 0)
        poly_daily_pnl_idr = poly_daily_pnl_usd * usd_idr_rate
        poly_equity_idr = usdc_balance * usd_idr_rate
        active_bets = list(poly_state.get("active_bets") or poly_state.get("top_opportunities") or [])

        accounting_truth = build_accounting_truth()
        live_total_equity_idr = float(idr_balance + phantom_equity_idr)
        combined_equity_idr = float(accounting_truth.get("current_total_equity_idr", live_total_equity_idr) or 0.0)
        realized_daily_pnl_idr = self._realized_daily_pnl_idr()
        open_pnl = self._active_trade_unrealized_pnl(active_positions)
        unrealized_daily_pnl_idr = float(open_pnl.get("unrealized_pnl_idr", 0.0) or 0.0)
        position_cost_basis_idr = float(open_pnl.get("position_cost_basis_idr", 0.0) or 0.0)
        reset_total_balance_idr = float(accounting_truth.get("reset_total_balance_idr", max(combined_equity_idr - (realized_daily_pnl_idr + unrealized_daily_pnl_idr), 0.0)) or 0.0)
        daily_pnl_idr = float(accounting_truth.get("daily_pnl_idr", combined_equity_idr - reset_total_balance_idr) or 0.0)
        daily_pnl_pct = float(accounting_truth.get("daily_pnl_pct", (daily_pnl_idr / max(reset_total_balance_idr, 1.0)) * 100.0) or 0.0)
        total_balance_idr = combined_equity_idr
        gov_state = self._load_state_json("capital_governor.json", {})
        today = datetime.now(WIB).strftime("%Y-%m-%d")
        governor_fresh_today = isinstance(gov_state, dict) and str(gov_state.get("date") or "") == today and _safe_float(gov_state.get("current_total_equity_idr"), 0.0) > 0.0
        if governor_fresh_today:
            total_balance_idr = _safe_float(gov_state.get("current_total_equity_idr"), total_balance_idr)
            reset_total_balance_idr = _safe_float(
                gov_state.get("reset_total_balance_idr"),
                _safe_float(gov_state.get("start_total_equity_idr"), reset_total_balance_idr),
            )
            daily_pnl_idr = _safe_float(
                gov_state.get("daily_return_idr"),
                _safe_float(gov_state.get("daily_pnl_idr"), daily_pnl_idr),
            )
            daily_pnl_pct = _safe_float(
                gov_state.get("daily_return_pct"),
                _safe_float(gov_state.get("daily_pnl_pct"), daily_pnl_pct),
            )
            open_buy_order_reserve_idr = _safe_float(gov_state.get("open_buy_order_reserve_idr"), 0.0)
        else:
            open_buy_order_reserve_idr = 0.0
            if live_total_equity_idr > 0.0:
                total_balance_idr = live_total_equity_idr
            daily_pnl_idr = total_balance_idr - reset_total_balance_idr
            pnl_base = max(reset_total_balance_idr, 1.0)
            daily_pnl_pct = (daily_pnl_idr / pnl_base * 100.0)
        green_state = "GREEN" if daily_pnl_idr > 0 else "RECOVERY" if daily_pnl_idr < 0 else "FLAT"

        snapshot.update({
            "equity_idr": idr_balance,
            "idr_cash": idr_cash,
            "coin_holdings_idr": coin_holdings_value_idr,
            "pnl_idr": daily_pnl_idr,
            "return_pct": daily_pnl_pct,
            "daily_pnl_idr": daily_pnl_idr,
            "daily_pnl_pct": daily_pnl_pct,
            "combined_pnl_idr": daily_pnl_idr,
            "daily_return_idr": daily_pnl_idr,
            "daily_return_pct": daily_pnl_pct,
            "realized_pnl_idr": realized_daily_pnl_idr,
            "unrealized_pnl_idr": unrealized_daily_pnl_idr,
            "position_cost_basis_idr": position_cost_basis_idr,
            "open_position_pnl": open_pnl.get("positions", []),
            "daily_state": {
                "color": green_state,
                "hold_winners": green_state == "GREEN",
                "take_profit_multiplier": 1.75 if green_state == "GREEN" else 1.0,
                "reason": "open_trade_mark_to_market" if open_pnl.get("positions") else "realized_daily_pnl",
            },
            "active_positions": active_positions,
            "combined_equity_idr": total_balance_idr,
            "total_balance_idr": total_balance_idr,
            "reset_total_balance_idr": reset_total_balance_idr,
            "start_total_equity_idr": reset_total_balance_idr,
            "open_buy_order_reserve_idr": open_buy_order_reserve_idr,
            "phantom_equity_idr": phantom_equity_idr,
            "accounting_truth": {
                **accounting_truth,
                "current_total_equity_idr": total_balance_idr,
                "total_balance_idr": total_balance_idr,
                "reset_total_balance_idr": reset_total_balance_idr,
                "start_total_equity_idr": reset_total_balance_idr,
                "daily_pnl_idr": daily_pnl_idr,
                "combined_pnl_idr": daily_pnl_idr,
                "daily_return_idr": daily_pnl_idr,
                "daily_pnl_pct": daily_pnl_pct,
                "daily_return_pct": daily_pnl_pct,
                "live_total_equity_idr": live_total_equity_idr,
                "governor_fresh_today": governor_fresh_today,
            },
            "polymarket": {
                "usdc_balance": usdc_balance,
                "equity_idr": poly_equity_idr,
                "pnl_idr": poly_daily_pnl_idr,
                "daily_pnl_usd": poly_daily_pnl_usd,
                "daily_pnl_idr": poly_daily_pnl_idr,
                "active_positions": active_bets[:5],
                "active_bets": active_bets[:5],
            },
        })
        return snapshot

    async def _get_market_context(self):
        """Gets market mood and global regime."""
        mood = getattr(self.master, "market_mood", "NEUTRAL")
        # Attempt to get deeper context from Brain snapshot if available
        brain_snap = {}
        if hasattr(self.master, "brain") and self.master.brain:
            if hasattr(self.master.brain, "snapshot") and callable(self.master.brain.snapshot):
                # Check if it's async
                import inspect
                if inspect.iscoroutinefunction(self.master.brain.snapshot):
                    brain_snap = await self.master.brain.snapshot()
                else:
                    brain_snap = self.master.brain.snapshot()
            elif isinstance(self.master.brain, dict):
                brain_snap = self.master.brain
            
        return {
            "mood": mood,
            "regime": brain_snap.get("market_pulse", {}).get("risk_bias", "UNKNOWN"),
            "fear_greed": brain_snap.get("fear_greed", "N/A")
        }
