from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict

import httpx

JUPITER_QUOTE_URL = os.getenv("JUPITER_QUOTE_URL", "https://api.jup.ag/swap/v1/quote")
JUPITER_SWAP_URL = os.getenv("JUPITER_SWAP_URL", "https://api.jup.ag/swap/v1/swap")


@dataclass
class JupiterQuoteResult:
    ok: bool
    reason: str
    raw: Dict[str, Any]
    input_mint: str = ""
    output_mint: str = ""
    in_amount: int = 0
    out_amount: int = 0
    price_impact_pct: float = 999.0
    route_count: int = 0


class JupiterGateway:
    def __init__(self, timeout_s: float = 8.0):
        self.timeout_s = timeout_s

    async def quote(self, *, input_mint: str, output_mint: str, amount: int, slippage_bps: int) -> JupiterQuoteResult:
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(int(amount)),
            "slippageBps": str(int(slippage_bps)),
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.get(JUPITER_QUOTE_URL, params=params)
                data = response.json()
            if response.status_code != 200:
                return JupiterQuoteResult(False, f"quote_http_{response.status_code}", data)
            if not data or "outAmount" not in data:
                return JupiterQuoteResult(False, "quote_missing_out_amount", data)
            route_plan = data.get("routePlan") or []
            return JupiterQuoteResult(
                ok=True,
                reason="OK",
                raw=data,
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=int(data.get("inAmount") or amount),
                out_amount=int(data.get("outAmount") or 0),
                price_impact_pct=float(data.get("priceImpactPct") or 0.0) * 100.0,
                route_count=len(route_plan),
            )
        except Exception as exc:
            return JupiterQuoteResult(False, f"quote_exception:{exc}", {})

    async def build_swap_transaction(
        self,
        *,
        quote_response: Dict[str, Any],
        user_public_key: str,
        dynamic_compute_unit_limit: bool = True,
        prioritization_fee_lamports: Any = "auto",
    ) -> Dict[str, Any]:
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "dynamicComputeUnitLimit": dynamic_compute_unit_limit,
            "prioritizationFeeLamports": prioritization_fee_lamports,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(JUPITER_SWAP_URL, json=payload)
                data = response.json()
            if response.status_code != 200:
                return {"ok": False, "reason": f"swap_http_{response.status_code}", "raw": data}
            tx = data.get("swapTransaction")
            if not tx:
                return {"ok": False, "reason": "missing_swap_transaction", "raw": data}
            return {"ok": True, "reason": "OK", "swap_transaction": tx, "raw": data}
        except Exception as exc:
            return {"ok": False, "reason": f"swap_exception:{exc}", "raw": {}}
