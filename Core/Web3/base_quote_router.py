from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import aiohttp

STATE_DIR = Path(__file__).resolve().parent.parent.parent / "state"
BASE_QUOTE_STATE_FILE = STATE_DIR / "base_quote_state.json"


def _save(payload: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    BASE_QUOTE_STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


class BaseQuoteRouter:
    def __init__(self) -> None:
        self.base_quote_url = os.getenv("BASE_QUOTE_URL", "").strip()
        self.router = os.getenv("BASE_SWAP_ROUTER", "").strip().lower()

    async def quote(self, input_asset: str, output_asset: str, amount_raw: int) -> Dict[str, Any]:
        route = "base"
        if amount_raw <= 0:
            payload = {"route": route, "input_asset": input_asset, "output_asset": output_asset, "quote_ok": False, "reason": "invalid amount", "expected_out": 0, "slippage_pct": 999, "gas_idr": 0, "expires_at": None, "fresh_at": datetime.now(timezone.utc).isoformat()}
            _save(payload)
            return payload
        if self.base_quote_url:
            try:
                params = {"sellToken": input_asset, "buyToken": output_asset, "sellAmount": str(int(amount_raw))}
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.base_quote_url, params=params, timeout=8) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"quote http {resp.status}")
                        data = await resp.json()
                        payload = {
                            "route": route,
                            "input_asset": input_asset,
                            "output_asset": output_asset,
                            "quote_ok": True,
                            "reason": "",
                            "expected_out": int(data.get("buyAmount") or data.get("toTokenAmount") or 0),
                            "slippage_pct": float(os.getenv("BASE_MAX_SLIPPAGE_PCT", "2.5") or 2.5),
                            "gas_idr": int(float(os.getenv("BASE_GAS_IDR_ESTIMATE", "15000") or 15000)),
                            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=45)).isoformat(),
                            "fresh_at": datetime.now(timezone.utc).isoformat(),
                            "raw": data,
                        }
                        _save(payload)
                        return payload
            except Exception as exc:
                payload = {"route": route, "input_asset": input_asset, "output_asset": output_asset, "quote_ok": False, "reason": str(exc), "expected_out": 0, "slippage_pct": 999, "gas_idr": 0, "expires_at": None, "fresh_at": datetime.now(timezone.utc).isoformat()}
                _save(payload)
                return payload
        payload = {"route": route, "input_asset": input_asset, "output_asset": output_asset, "quote_ok": False, "reason": "base_quote_router_missing", "expected_out": 0, "slippage_pct": 999, "gas_idr": 0, "expires_at": None, "fresh_at": datetime.now(timezone.utc).isoformat()}
        _save(payload)
        return payload
