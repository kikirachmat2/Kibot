from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from Core.Support.ki_config import KiConfig
from Core.Support.ki_utils import sign_payload
from Core.Web3.web3_fee_intelligence import build_fee_intelligence

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = ROOT / "state"
STATE_FILE = STATE_DIR / "live_order_dispatcher.json"


def _read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def _write_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ACTIVE",
        "live_trading_enabled": bool(KiConfig.LIVE_TRADING_ENABLED),
        "indodax": {},
        "phantom": {},
        "errors": {},
        "next_check_seconds": float(os.getenv("KIBOT_LIVE_DISPATCH_INTERVAL_SEC", "3") or 3),
    }
    resolved.update(payload)
    STATE_FILE.write_text(json.dumps(resolved, indent=2, ensure_ascii=False), encoding="utf-8")
    return resolved


def _now_ms() -> int:
    return int(time.time() * 1000)


def _active_symbols() -> set[str]:
    active = _read_json(STATE_DIR / "active_trades.json", {})
    symbols: set[str] = set()
    if isinstance(active, dict):
        symbols.update(str(symbol).upper() for symbol in active.keys())

    try:
        from Core.Intelligence.order_tracker import get_tracker

        tracker = get_tracker()
        for record in tracker.get_open_orders():
            if not isinstance(record, dict):
                continue
            pair = str(record.get("pair") or record.get("symbol") or "").upper().strip()
            if pair:
                symbols.add(pair)
    except Exception:
        pass

    return symbols


def _venue_state(venue: str) -> Dict[str, Any]:
    gov = _read_json(STATE_DIR / "capital_governor.json", {})
    venues = gov.get("venues", {}) if isinstance(gov, dict) else {}
    state = venues.get(venue, {}) if isinstance(venues, dict) else {}
    return state if isinstance(state, dict) else {}


def _capital_governor_block() -> Dict[str, Any]:
    gov = _read_json(STATE_DIR / "capital_governor.json", {})
    if not isinstance(gov, dict):
        return {"blocked": True, "reason": "capital_governor_missing"}
    allow = bool(gov.get("allow_new_orders", False))
    status = str(gov.get("status") or "").upper()
    reason = str(gov.get("allow_new_orders_reason") or "").strip()
    if allow and status in {"RECONCILED", "RECONCILING"}:
        return {"blocked": False, "reason": "", "state": gov}
    if not reason:
        if status == "BLOCKED_WITH_REASON":
            reason = "capital_governor_global_hard_stop"
        elif status:
            reason = f"capital_governor_status_{status.lower()}"
        else:
            reason = "capital_governor_orders_blocked"
    return {"blocked": True, "reason": reason, "state": gov}


class LiveOrderDispatcher:
    """Dispatches autonomous runtime decisions into real executors.

    The brains/target boards decide and rank. This dispatcher is the missing
    hot handoff: it signs HMAC payloads for the Indodax UDP executor and calls
    Phantom route executors when a same-chain target is actionable.
    """

    def __init__(self) -> None:
        self.interval_seconds = float(os.getenv("KIBOT_LIVE_DISPATCH_INTERVAL_SEC", "3") or 3)
        self.symbol_cooldown_seconds = float(os.getenv("KIBOT_DISPATCH_SYMBOL_COOLDOWN_SEC", "180") or 180)
        self.phantom_cooldown_seconds = float(os.getenv("KIBOT_PHANTOM_DISPATCH_ROUTE_COOLDOWN_SEC", "240") or 240)
        self.leadlag_aggressive_mode = os.getenv("KIBOT_INDO_BINANCE_LEADLAG_AGGRESSIVE_DISPATCH", "true").strip().lower() in {"1", "true", "yes", "on"}
        self.leadlag_min_gap_pct = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_DISPATCH_MIN_GAP_PCT", "0.15") or 0.15)
        self.leadlag_min_lag_sec = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_DISPATCH_MIN_LAG_SEC", "0.5") or 0.5)
        self.leadlag_min_entry_score = float(os.getenv("KIBOT_INDO_BINANCE_LEADLAG_DISPATCH_MIN_ENTRY_SCORE", "12.0") or 12.0)
        self.host = os.getenv("KIBOT_INDODAX_EXECUTOR_HOST", "127.0.0.1")
        self.port = int(os.getenv("KIBOT_INDODAX_EXECUTOR_PORT", str(KiConfig.INDO_SIGNAL_PORT)) or KiConfig.INDO_SIGNAL_PORT)
        self.secret = os.getenv("KIBOT_SECRET", "")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.state = _read_json(STATE_FILE, {})
        if not isinstance(self.state, dict):
            self.state = {}

    def _cooldowns(self, key: str) -> Dict[str, float]:
        data = self.state.get(key)
        return data if isinstance(data, dict) else {}

    def _in_cooldown(self, bucket: str, key: str, cooldown: float) -> bool:
        last = float(self._cooldowns(bucket).get(key, 0.0) or 0.0)
        return last > 0 and (time.time() - last) < cooldown

    def _mark_sent(self, bucket: str, key: str) -> None:
        data = self._cooldowns(bucket)
        data[key] = time.time()
        self.state[bucket] = data

    def _indodax_candidates(self) -> List[Dict[str, Any]]:
        board = _read_json(STATE_DIR / "indodax_top_targets.json", {})
        targets = board.get("top_targets", []) if isinstance(board, dict) else []
        if not isinstance(targets, list):
            return []
        active = _active_symbols()
        out: List[Dict[str, Any]] = []
        for item in targets:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if not symbol or symbol in active:
                continue
            if str(item.get("route_status") or "").upper() != "EXECUTABLE":
                continue
            if not bool(item.get("source_proof_ok", True)):
                continue
            action = str(item.get("recommended_action") or "").upper()
            is_leadlag = str(item.get("source_pool") or "").lower() in {"leadlag_candidates", "leadlag_watchlist"}
            if action != "ENTER":
                if not (
                    self.leadlag_aggressive_mode
                    and is_leadlag
                    and float(item.get("leadlag_gap_pct") or 0.0) >= self.leadlag_min_gap_pct
                    and float(item.get("leadlag_lag_seconds") or 0.0) >= self.leadlag_min_lag_sec
                    and float(item.get("entry_score") or 0.0) >= self.leadlag_min_entry_score
                ):
                    continue
            if self._in_cooldown("indodax_cooldowns", symbol, self.symbol_cooldown_seconds):
                continue
            out.append(item)
        return out

    def _build_indodax_signal(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        gov = _read_json(STATE_DIR / "capital_governor.json", {})
        total_equity = float(gov.get("current_total_equity_idr") or gov.get("current_equity_idr") or 0.0)
        venue = _venue_state("indodax")
        venue_cap = float(venue.get("daily_loss_cap_idr") or gov.get("max_daily_loss_idr") or 0.0)
        venue_pnl = float(venue.get("daily_pnl_idr") or 0.0)
        venue_risk_remaining = max(0.0, venue_cap + venue_pnl)
        change = float(candidate.get("change_24h_pct") or 0.0)
        entry_score = float(candidate.get("entry_score") or 0.0)
        confidence = max(0.55, min(0.96, max(change / 100.0, entry_score / 300.0)))
        expected_net_pct = max(
            float(os.getenv("KIBOT_AUTONOMOUS_MIN_EXPECTED_NET_PCT", "0.45") or 0.45),
            min(float(os.getenv("KIBOT_AUTONOMOUS_MAX_EXPECTED_NET_PCT", "4.0") or 4.0), change / 20.0),
        )
        budget_idr = float(candidate.get("size_idr") or 0.0)
        if budget_idr <= 0:
            budget_idr = max(10_000.0, min(total_equity * 0.22, 35_000.0))
        return {
            "type": "COUNCIL_MANDATE",
            "origin": "AUTONOMOUS_SCRIPT_DISPATCHER",
            "source": "LIVE_ORDER_DISPATCHER",
            "venue": "indodax",
            "exchange": "INDODAX",
            "symbol": str(candidate.get("symbol") or "").upper(),
            "side": "BUY",
            "price": float(candidate.get("last_price") or candidate.get("price") or 0.0),
            "confidence": confidence,
            "score": entry_score,
            "change_24h_pct": change,
            "change_pct": change,
            "momentum_score": float(candidate.get("momentum_score") or change or 0.0),
            "leadlag_gap_pct": float(candidate.get("leadlag_gap_pct") or 0.0),
            "leadlag_lag_seconds": float(candidate.get("leadlag_lag_seconds") or 0.0),
            "leadlag_score": float(candidate.get("leadlag_score") or 0.0),
            "leader_change_pct": float(candidate.get("leader_change_pct") or 0.0),
            "follower_change_pct": float(candidate.get("follower_change_pct") or 0.0),
            "volume_idr": float(candidate.get("volume_24h_idr") or 0.0),
            "liquidity": float(candidate.get("volume_24h_idr") or 0.0),
            "liquidity_usd": float(candidate.get("volume_24h_idr") or 0.0) / 16000.0,
            "spread_pct": float(candidate.get("spread_pct") or 0.0),
            "expected_net_pct": expected_net_pct,
            "ev_pct": expected_net_pct,
            "budget_idr": budget_idr,
            "route_bucket_idr": total_equity,
            "total_equity_idr": total_equity,
            "daily_risk_remaining_idr": venue_risk_remaining,
            "exit_available": True,
            "exit_quality": "A",
            "trade_grade": "A",
            "stop_loss_pct": float(os.getenv("KIBOT_INDODAX_LIVE_STOP_LOSS_PCT", "1.5") or 1.5),
            "take_profit_pct": float(os.getenv("KIBOT_INDODAX_LIVE_TAKE_PROFIT_PCT", "2.2") or 2.2),
            "max_spread_pct": float(os.getenv("KIBOT_INDODAX_LIVE_MAX_SPREAD_PCT", "1.35") or 1.35),
            "deadline_mode": "LIVE_AUTONOMOUS_TRADING",
            "source_proof_ok": bool(candidate.get("source_proof_ok", True)),
        }

    def dispatch_indodax_once(self) -> Dict[str, Any]:
        if not KiConfig.LIVE_TRADING_ENABLED:
            return {"status": "BLOCKED_WITH_REASON", "reason": "live_trading_disabled"}
        if not self.secret:
            return {"status": "BLOCKED_WITH_REASON", "reason": "kibot_secret_missing"}
        if (STATE_DIR / "KILL_SWITCH").exists():
            return {"status": "BLOCKED_WITH_REASON", "reason": "kill_switch"}
        governor_block = _capital_governor_block()
        if governor_block.get("blocked"):
            return {
                "status": "BLOCKED_WITH_REASON",
                "reason": str(governor_block.get("reason") or "capital_governor_orders_blocked"),
                "capital_governor": governor_block.get("state", {}),
            }
        venue = _venue_state("indodax")
        if venue and not bool(venue.get("allow_orders", True)):
            return {
                "status": "BLOCKED_WITH_REASON",
                "reason": str(venue.get("reason") or "indodax_venue_blocked"),
            }

        candidates = self._indodax_candidates()
        if not candidates:
            return {"status": "SCAN_NEXT", "reason": "no_enter_candidate_or_all_in_cooldown"}
        candidate = candidates[0]
        signal = self._build_indodax_signal(candidate)
        payload = {"seq_id": _now_ms(), "ts": _now_ms(), "signals": [signal]}
        envelope = {"data": payload, "signature": sign_payload(payload, self.secret)}
        self.sock.sendto(json.dumps(envelope).encode("utf-8"), (self.host, self.port))
        symbol = signal["symbol"]
        self._mark_sent("indodax_cooldowns", symbol)
        return {
            "status": "DISPATCHED",
            "route": "indodax",
            "symbol": symbol,
            "candidate": candidate,
            "signal": {k: v for k, v in signal.items() if k != "source_proof"},
            "executor": f"udp://{self.host}:{self.port}",
        }

    async def dispatch_phantom_once(self) -> Dict[str, Any]:
        if not KiConfig.LIVE_TRADING_ENABLED:
            return {"status": "BLOCKED_WITH_REASON", "reason": "live_trading_disabled"}
        if not KiConfig.ENABLE_REAL_SWAP:
            return {"status": "BLOCKED_WITH_REASON", "reason": "real_swap_disabled"}
        governor_block = _capital_governor_block()
        if governor_block.get("blocked"):
            return {
                "status": "BLOCKED_WITH_REASON",
                "reason": str(governor_block.get("reason") or "capital_governor_orders_blocked"),
                "capital_governor": governor_block.get("state", {}),
            }
        board = _read_json(STATE_DIR / "phantom_top_targets.json", {})
        targets = board.get("top_targets", []) if isinstance(board, dict) else []
        if not isinstance(targets, list):
            return {"status": "SCAN_NEXT", "reason": "phantom_targets_missing"}
        treasury = _read_json(STATE_DIR / "phantom_treasury.json", {})
        sol_balance = float(treasury.get("sol_balance") or treasury.get("balances", {}).get("sol") or 0.0)
        amount_sol = max(0.0, min(sol_balance * 0.35, sol_balance - float(os.getenv("WEB3_SOL_RESERVE", "0.003") or 0.003)))
        min_sol = float(os.getenv("WEB3_MIN_SOL_TRADE", "0.0005") or 0.0005)
        if amount_sol < min_sol:
            return {"status": "BLOCKED_WITH_REASON", "reason": "sol_balance_below_trade_min", "sol_balance": sol_balance}

        for candidate in targets:
            if not isinstance(candidate, dict):
                continue
            route = str(candidate.get("route") or "").lower()
            mint = str(candidate.get("mint_or_market") or "").strip()
            key = f"{route}:{mint}"
            if route not in {"solana_jupiter", "pumpfun_jupiter", "pumpfun_native", "solana_meme"}:
                continue
            if not mint or len(mint) < 32:
                continue
            if str(candidate.get("recommended_action") or "").upper() != "ENTER":
                continue
            if self._in_cooldown("phantom_cooldowns", key, self.phantom_cooldown_seconds):
                continue

            from Core.Exchange.phantom_router import PhantomRouter

            router = PhantomRouter()
            if not router.private_key:
                return {"status": "BLOCKED_WITH_REASON", "reason": "phantom_signer_missing"}
            fee_state = build_fee_intelligence(
                route,
                trade_size_idr=float(amount_sol) * float(os.getenv("SOL_USD_RATE", "170") or 170) * float(os.getenv("USD_IDR_RATE", "16000") or 16000),
                balance_snapshot=treasury,
                route_context={"source": "live_order_dispatcher", "route": route},
            )
            if not fee_state.get("gas_affordable", True):
                return {
                    "status": "BLOCKED_WITH_REASON",
                    "reason": str(fee_state.get("gas_reason") or "gas_fee_unaffordable"),
                    "fee_intelligence": fee_state,
                }
            slippage_bps = int(float(os.getenv("WEB3_MEME_SLIPPAGE_BPS", "1500") or 1500))
            ok = await router.snipe_meme_coin(mint, amount_sol, slippage_bps=slippage_bps)
            self._mark_sent("phantom_cooldowns", key)
            return {
                "status": "DISPATCHED" if ok else "BLOCKED_WITH_REASON",
                "route": route,
                "mint": mint,
                "amount_sol": amount_sol,
                "candidate": candidate,
                "reason": "submitted_to_phantom_router" if ok else "phantom_router_rejected",
                "fee_intelligence": fee_state,
            }
        return {"status": "SCAN_NEXT", "reason": "no_same_chain_phantom_enter_candidate"}

    async def tick(self) -> Dict[str, Any]:
        indodax = self.dispatch_indodax_once()
        try:
            phantom = await self.dispatch_phantom_once()
        except Exception as exc:
            phantom = {"status": "BLOCKED_WITH_REASON", "reason": f"phantom_dispatch_error:{exc}"}
        return _write_state({
            "status": "ACTIVE" if indodax.get("status") != "BLOCKED_WITH_REASON" or phantom.get("status") != "BLOCKED_WITH_REASON" else "BLOCKED_WITH_REASON",
            "indodax": indodax,
            "phantom": phantom,
            "indodax_cooldowns": self._cooldowns("indodax_cooldowns"),
            "phantom_cooldowns": self._cooldowns("phantom_cooldowns"),
        })

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                _write_state({"status": "BLOCKED_WITH_REASON", "errors": {"dispatcher": str(exc)}})
            await asyncio.sleep(self.interval_seconds)


def main() -> None:
    asyncio.run(LiveOrderDispatcher().run_forever())


if __name__ == "__main__":
    main()
