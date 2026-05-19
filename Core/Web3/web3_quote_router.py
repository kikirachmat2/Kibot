import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import aiohttp

STATE_DIR = Path(__file__).resolve().parent.parent.parent / 'state'
QUOTE_STATE_FILE = STATE_DIR / 'web3_quote_state.json'

class Web3QuoteRouter:
    def __init__(self):
        self.solana_quote_url = os.getenv('JUPITER_QUOTE_URL', 'https://quote-api.jup.ag/v6/quote')
        self.base_quote_url = os.getenv('BASE_QUOTE_URL', '')

    def _save(self, data: Dict[str, Any]) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        QUOTE_STATE_FILE.write_text(json.dumps(data, indent=2))

    async def quote(self, route: str, input_asset: str, output_asset: str, amount_raw: int) -> Dict[str, Any]:
        route = str(route or '').lower()
        if amount_raw <= 0:
            result = {'route': route, 'input_asset': input_asset, 'output_asset': output_asset, 'quote_ok': False, 'reason': 'invalid amount'}
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
                            'gas_idr': int(float(os.getenv('WEB3_GAS_IDR_ESTIMATE', '10000'))),
                            'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=45)).isoformat(),
                            'fresh_at': datetime.now(timezone.utc).isoformat(),
                            'raw': payload,
                        }
                        self._save(result)
                        return result
            except Exception as e:
                result = {'route': route, 'input_asset': input_asset, 'output_asset': output_asset, 'quote_ok': False, 'reason': str(e), 'expected_out': 0, 'slippage_pct': 999, 'gas_idr': 0, 'expires_at': None, 'fresh_at': datetime.now(timezone.utc).isoformat()}
                self._save(result)
                return result
        result = {'route': route, 'input_asset': input_asset, 'output_asset': output_asset, 'quote_ok': False, 'reason': 'route not configured', 'expected_out': 0, 'slippage_pct': 999, 'gas_idr': 0, 'expires_at': None, 'fresh_at': datetime.now(timezone.utc).isoformat()}
        self._save(result)
        return result
