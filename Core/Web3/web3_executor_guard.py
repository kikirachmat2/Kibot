import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from Core.Scanner.source_proof import SourceProof

STATE_DIR = Path(__file__).resolve().parent.parent.parent / 'state'
POSITION_FILE = STATE_DIR / 'web3_positions.json'

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

    def approve(self, *, treasury: Dict[str, Any], route: Dict[str, Any], safety: Dict[str, Any], quote: Dict[str, Any], budget_idr: float, stop_loss_pct: float, take_profit_pct: float, trailing_stop_pct: float = 0.0, time_stop_seconds: int = 0, spend_reserve: bool = False, exit_plan: bool = True, quote_context: str = "ok") -> Dict[str, Any]:
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
        if route.get('network') == 'base' and route.get('executor') is False:
            reasons.append('base_executor_missing')
        if route.get('network') == 'future_web3':
            reasons.append('future_web3_scout_only')

        if reasons:
            return {'allowed': False, 'reason': ';'.join(reasons), 'max_trade_idr': 0}
        max_trade_idr = int(min(budget_idr, safety.get('max_trade_idr', budget_idr), quote.get('gas_idr', 0) + budget_idr))
        return {'allowed': True, 'reason': 'approved', 'max_trade_idr': max_trade_idr}

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
