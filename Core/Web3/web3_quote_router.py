import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import aiohttp

from Core.Web3.web3_fee_intelligence import build_fee_intelligence

STATE_DIR = Path(__file__).resolve().parent.parent.parent / 'state'
QUOTE_STATE_FILE = STATE_DIR / 'web3_quote_state.json'

class Web3QuoteRouter:
    def __init__(self):
        self.solana_quote_url = os.getenv('JUPITER_QUOTE_URL', 'https://quote-api.jup.ag/v6/quote')
        self.base_quote_url = os.getenv('BASE_QUOTE_URL', '')

    def _save(self, data: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        QUOTE_STATE_FILE.write_text(json.dumps(data, indent=2))

    async def quote(
        self,
        route: str,
        input_asset: str,
        output_asset: str,
        amount_raw: int,
        *,
        trade_size_idr: float | None = None,
        balance_snapshot: Dict[str, Any] | None = None,
        route_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        route = str(route or '').lower()
        if amount_raw <= 0:
            fee_state = build_fee_intelligence(route, trade_size_idr=float(trade_size_idr or 0.0), balance_snapshot=balance_snapshot, route_context=route_context)
            result = {'route': route, 'input_asset': input_asset, 'output_asset': output_asset, 'quote_ok': False, 'reason': 'invalid amount', 'gas_idr': 0, 'gas_floor_idr': 0, 'gas_mode': fee_state.get("gas_mode", "unknown"), 'gas_reason': fee_state.get("gas_reason", "invalid amount"), 'gas_affordable': False, 'fee_breakdown': fee_state.get("fee_breakdown", {}), 'fee_intelligence': fee_state}
            self._save(result)
            return result
        if route == 'solana':
            try:
                params = {'inputMint': input_asset, 'outputMint': output_asset, 'amount': str(int(amount_raw)), 'slippageBps': '50'}
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.solana_quote_url, params=params, timeout=6) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f'quote http {resp.status}')
                        payload = await resp.json()
                        result = {
                            'route': route,
                            'input_asset': input_asset,
                            'output_asset': output_asset,
                            'quote_ok': True,
                            'expected_out': int(payload.get('outAmount') or 0),
                            'slippage_pct': float(payload.get('priceImpactPct') or 0) * 100,
                            'gas_idr': 0,
                            'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=45)).isoformat(),
                            'fresh_at': datetime.now(timezone.utc).isoformat(),
                            'raw': payload,
                        }
                        fee_state = build_fee_intelligence(route, trade_size_idr=float(trade_size_idr or 0.0), balance_snapshot=balance_snapshot, quote=result, route_context=route_context)
                        result.update({
                            'gas_idr': float(fee_state.get('gas_fee_idr', 0.0) or 0.0),
                            'gas_floor_idr': float(fee_state.get('gas_floor_idr', 0.0) or 0.0),
                            'gas_mode': fee_state.get('gas_mode', 'unknown'),
                            'gas_reason': fee_state.get('gas_reason', ''),
                            'gas_affordable': bool(fee_state.get('gas_affordable', True)),
                            'gasless_cap_idr': float(fee_state.get('gasless_cap_idr', 0.0) or 0.0),
                            'fee_breakdown': fee_state.get('fee_breakdown', {}),
                            'fee_intelligence': fee_state,
                        })
                        self._save(result)
                        return result
            except Exception as e:
                fee_state = build_fee_intelligence(route, trade_size_idr=float(trade_size_idr or 0.0), balance_snapshot=balance_snapshot, route_context=route_context)
                result = {'route': route, 'input_asset': input_asset, 'output_asset': output_asset, 'quote_ok': False, 'reason': str(e), 'expected_out': 0, 'slippage_pct': 999, 'gas_idr': float(fee_state.get('gas_fee_idr', 0.0) or 0.0), 'gas_floor_idr': float(fee_state.get('gas_floor_idr', 0.0) or 0.0), 'gas_mode': fee_state.get('gas_mode', 'unknown'), 'gas_reason': fee_state.get('gas_reason', str(e)), 'gas_affordable': bool(fee_state.get('gas_affordable', False)), 'expires_at': None, 'fresh_at': datetime.now(timezone.utc).isoformat(), 'fee_breakdown': fee_state.get('fee_breakdown', {}), 'fee_intelligence': fee_state}
                self._save(result)
                return result
        fee_state = build_fee_intelligence(route, trade_size_idr=float(trade_size_idr or 0.0), balance_snapshot=balance_snapshot, route_context=route_context)
        result = {'route': route, 'input_asset': input_asset, 'output_asset': output_asset, 'quote_ok': False, 'reason': 'route not configured', 'expected_out': 0, 'slippage_pct': 999, 'gas_idr': float(fee_state.get('gas_fee_idr', 0.0) or 0.0), 'gas_floor_idr': float(fee_state.get('gas_floor_idr', 0.0) or 0.0), 'gas_mode': fee_state.get('gas_mode', 'unknown'), 'gas_reason': fee_state.get('gas_reason', 'route not configured'), 'gas_affordable': bool(fee_state.get('gas_affordable', False)), 'expires_at': None, 'fresh_at': datetime.now(timezone.utc).isoformat(), 'fee_breakdown': fee_state.get('fee_breakdown', {}), 'fee_intelligence': fee_state}
        self._save(result)
        return result
