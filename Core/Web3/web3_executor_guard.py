import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Scanner.source_proof import SourceProof
from Core.Web3.web3_fee_intelligence import build_fee_intelligence

STATE_DIR = Path(__file__).resolve().parent.parent.parent / 'state'
POSITION_FILE = STATE_DIR / 'web3_positions.json'


def _normalize_venue_key(route: Dict[str, Any]) -> str:
    raw = str(route.get("venue") or route.get("network") or route.get("route") or "").strip().lower()
    if raw in {"indodax", "indodax_real", "indodax_spot"}:
        return "indodax"
    if raw in {"base", "solana", "pumpfun", "polymarket", "future_web3", "phantom"}:
        return "phantom"
    return raw or "phantom"

class Web3ExecutorGuard:
    def __init__(self):
        self.max_daily_loss_pct = float(os.getenv('WEB3_DAILY_LOSS_CAP_PCT', '1.5'))
        self.source_proof_required = os.getenv('WEB3_SOURCE_PROOF_REQUIRED', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}

    def _read_json(self, path: Path, default: Any):
        try:
            if path.exists():
                return json.loads(path.read_text())
        except Exception:
            pass
        return default

    def approve(self, *, treasury: Dict[str, Any], route: Dict[str, Any], safety: Dict[str, Any], quote: Dict[str, Any], budget_idr: float, stop_loss_pct: float, take_profit_pct: float, trailing_stop_pct: float = 0.0, time_stop_seconds: int = 0, spend_reserve: bool = False, exit_plan: bool = True, quote_context: str = "ok", trade_size_idr: float = 0.0, fee_intelligence: Dict[str, Any] | None = None, route_min_trade_idr: float = 0.0) -> Dict[str, Any]:
        reasons = []
        proof = route.get("source_proof")
        if proof is None and self.source_proof_required:
            reasons.append("source_proof_missing")
        elif proof is not None and not SourceProof.validate(proof):
            reasons.append("invalid_source_proof")
        if not treasury or treasury.get('status') != 'OK' or not treasury.get('reconciliation', {}).get('matches_user_wallet'):
            reasons.append('phantom_not_reconciled')
        if not route.get('allowed'):
            reasons.append(route.get('reason', 'route_blocked'))
        if not quote.get('quote_ok'):
            reasons.append(quote.get('reason', 'quote_missing'))
        if not safety.get('passed'):
            reasons.append(safety.get('reason', 'unsafe_token'))
        # Low/unclear EV is advisory for Phantom-style high-risk routes. The
        # fatal checks remain wallet, treasury, route, quote, tx, and loss cap.

        governor = self._read_json(STATE_DIR / 'capital_governor.json', {})
        global_allow = bool(governor.get("allow_new_orders", False))
        global_status = str(governor.get("status") or "").upper()
        global_reason = str(governor.get("allow_new_orders_reason") or "").strip()
        if not global_allow or global_status == "BLOCKED_WITH_REASON":
            reasons.append(global_reason or f"capital_governor_global_block:{global_status.lower() or 'blocked'}")
        venue_key = _normalize_venue_key(route if isinstance(route, dict) else {})
        venues = governor.get('venues', {}) if isinstance(governor, dict) else {}
        venue_state = venues.get(venue_key, {}) if isinstance(venues, dict) else {}
        if isinstance(venue_state, dict) and venue_state:
            if not bool(venue_state.get('allow_orders', False)):
                reasons.append(str(venue_state.get('reason') or f'{venue_key}_orders_blocked'))
            venue_loss_cap = float(venue_state.get('daily_loss_cap_idr', 0.0) or 0.0)
            venue_daily_pnl = float(venue_state.get('daily_pnl_idr', 0.0) or 0.0)
            if venue_loss_cap and venue_daily_pnl < -venue_loss_cap:
                reasons.append(f'{venue_key}_daily_cap_breached')
        else:
            daily_pnl = float(governor.get('daily_pnl_idr', 0.0) or 0.0)
            max_loss = float(governor.get('max_daily_loss_idr', 0.0) or 0.0)
            if max_loss and daily_pnl < -max_loss:
                reasons.append('daily_cap_breached')

        if stop_loss_pct <= 0 or take_profit_pct <= 0:
            reasons.append('missing_stop_or_take_profit')
        if not exit_plan:
            reasons.append('exit_plan_missing')
        if quote_context == "quote_context_missing":
            reasons.append('quote_context_missing')
        if spend_reserve:
            reasons.append('reserve_locked')
        route_network = str(route.get('network') or route.get('route') or "").strip().lower()
        route_status = str(route.get("status") or "").upper()
        route_reason = str(route.get("reason") or "").strip()
        if route_network == 'base':
            if route_status.startswith("BLOCKED") or route.get('executor') is False:
                reasons.append(route_reason or 'base_executor_missing')
        if route_network == 'future_web3':
            if route_status.startswith("BLOCKED") or route.get('executor') is False:
                reasons.append(route_reason or 'future_web3_blocked')

        fee_state = fee_intelligence or route.get("fee_intelligence") or quote.get("fee_intelligence")
        if not isinstance(fee_state, dict) or not fee_state:
            fee_state = build_fee_intelligence(
                str(route.get("network") or route.get("route") or ""),
                trade_size_idr=float(trade_size_idr or budget_idr or 0.0),
                balance_snapshot=treasury,
                quote=quote,
                route_context={"source": "web3_executor_guard"},
            )
        fee_floor_idr = float(
            fee_state.get("gas_floor_idr")
            or fee_state.get("gas_fee_idr")
            or quote.get("gas_floor_idr")
            or quote.get("gas_idr")
            or 0.0
        )
        gas_reason = str(fee_state.get("gas_reason") or quote.get("gas_reason") or "").strip()
        gas_mode = str(fee_state.get("gas_mode") or quote.get("gas_mode") or "unknown").strip().lower()
        gas_affordable = bool(fee_state.get("gas_affordable", True))
        if fee_floor_idr > 0:
            if fee_floor_idr >= float(budget_idr or 0.0):
                reasons.append(gas_reason or "gas_fee_unaffordable")
            if route_min_trade_idr > 0 and (float(budget_idr or 0.0) - fee_floor_idr) < float(route_min_trade_idr):
                reasons.append("gas_fee_consumes_min_trade")
            if gas_mode == "gasless" and float(trade_size_idr or budget_idr or 0.0) > 0:
                gas_ratio = fee_floor_idr / max(float(trade_size_idr or budget_idr or 0.0), 1.0)
                if gas_ratio > 0.10:
                    reasons.append("gasless_surcharge_exceeds_10pct_cap")
            if not gas_affordable:
                reasons.append(gas_reason or "gas_fee_unaffordable")

        if reasons:
            return {'allowed': False, 'reason': ';'.join(dict.fromkeys(reasons)), 'max_trade_idr': 0, 'fee_intelligence': fee_state, 'fee_floor_idr': fee_floor_idr}
        max_trade_idr = max(0.0, min(float(budget_idr), float(safety.get('max_trade_idr', budget_idr) or budget_idr)) - fee_floor_idr)
        return {'allowed': True, 'reason': 'approved', 'max_trade_idr': int(max_trade_idr), 'fee_intelligence': fee_state, 'fee_floor_idr': fee_floor_idr}

    def persist_position(self, position: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        payload = []
        if POSITION_FILE.exists():
            try:
                payload = json.loads(POSITION_FILE.read_text())
            except Exception:
                payload = []
        payload.append(position)
        POSITION_FILE.write_text(json.dumps(payload, indent=2))
