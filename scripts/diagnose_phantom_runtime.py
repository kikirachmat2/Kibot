#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

import aiohttp

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state" / "live_truth.json"


def _hydrate_dotenv() -> None:
    env_path = ROOT / ".env"
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except Exception:
        pass

    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


_hydrate_dotenv()


def _mask_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "SECRET_REDACTED"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


async def _get_json(url: str) -> tuple[bool, Dict[str, Any]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=6) as resp:
                if resp.status != 200:
                    return False, {"status_code": resp.status}
                try:
                    return True, await resp.json()
                except Exception:
                    return False, {}
    except Exception as exc:
        return False, {"error": str(exc)}


async def _post_json(url: str, body: Dict[str, Any]) -> tuple[bool, Dict[str, Any]]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, timeout=8) as resp:
                try:
                    data = await resp.json()
                except Exception:
                    data = {}
                if resp.status != 200:
                    return False, {"status_code": resp.status, "body": data}
                return True, data
    except Exception as exc:
        return False, {"error": str(exc)}


async def main() -> int:
    enabled = str(os.getenv("KIBOT_PHANTOM_ENABLED", "true")).lower() in {"1", "true", "yes", "on"}
    rpc_url = os.getenv("SOLANA_RPC_URL") or os.getenv("KIBOT_SOLANA_RPC_URL") or ""
    private_key = os.getenv("PHANTOM_PRIVATE_KEY") or os.getenv("KIBOT_PHANTOM_PRIVATE_KEY") or ""
    live_truth = _read_json(STATE)
    phantom_truth = live_truth.get("phantom", {}) if isinstance(live_truth, dict) else {}

    rpc_ok, rpc_payload = (False, {})
    jupiter_quote_ok, quote_payload = (False, {})
    jupiter_swap_ok, swap_payload = (False, {})
    signing_ok = False
    wallet_ok = False
    keypair = None

    if enabled and rpc_url and private_key:
        try:
            import base58
            from solders.keypair import Keypair

            key_bytes = base58.b58decode(private_key.strip())
            keypair = Keypair.from_bytes(key_bytes)
            wallet_ok = bool(str(keypair.pubkey()))
            signing_ok = True
        except Exception:
            signing_ok = False
            wallet_ok = False

        rpc_ok, rpc_payload = await _post_json(
            rpc_url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getHealth",
            },
        )
        if rpc_ok and keypair is not None:
            rpc_ok, rpc_payload = await _post_json(
                rpc_url,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "getBalance",
                    "params": [str(keypair.pubkey())],
                },
            )

        quote_url = "https://api.jup.ag/swap/v1/quote?inputMint=So11111111111111111111111111111111111111112&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000&slippageBps=50"
        jupiter_quote_ok, quote_payload = await _get_json(quote_url)
        if jupiter_quote_ok and keypair is not None:
            swap_url = "https://api.jup.ag/swap/v1/swap"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        swap_url,
                        json={"quoteResponse": quote_payload, "userPublicKey": str(keypair.pubkey()), "dynamicComputeUnitLimit": True, "prioritizationFeeLamports": "auto"},
                        timeout=8,
                    ) as resp:
                        jupiter_swap_ok = resp.status == 200
                        if jupiter_swap_ok:
                            try:
                                swap_payload = await resp.json()
                            except Exception:
                                swap_payload = {}
                        else:
                            swap_payload = {"status_code": resp.status}
            except Exception as exc:
                jupiter_swap_ok = False
                swap_payload = {"error": str(exc)}
    else:
        rpc_payload = {"reason": "missing_env"}

    diagnosis = "FAIL:PHANTOM_RUNTIME_ERROR"
    if not enabled or not rpc_url or not private_key:
        diagnosis = "OK:PHANTOM_LOCKED_MISSING_ENV"
    elif not signing_ok:
        diagnosis = "BLOCKED_BY_PHANTOM_SIGNING"
    elif not rpc_ok:
        diagnosis = "BLOCKED_BY_RPC"
    elif not jupiter_quote_ok:
        diagnosis = "BLOCKED_BY_JUPITER"
    elif not jupiter_swap_ok:
        diagnosis = "BLOCKED_BY_JUPITER"
    elif not wallet_ok:
        diagnosis = "BLOCKED_BY_WALLET_RECONCILIATION"
    else:
        diagnosis = "OK:PHANTOM_LIVE_READY"

    print(f"phantom_enabled={enabled}")
    print(f"rpc_present={'yes' if bool(rpc_url) else 'no'}")
    print(f"rpc_url={_mask_url(rpc_url) if rpc_url else 'SECRET_REDACTED'}")
    print(f"private_key_present={'yes' if bool(private_key) else 'no'}")
    print(f"public_key_present={'yes' if wallet_ok else 'no'}")
    print(f"rpc_health={'yes' if rpc_ok else 'no'}")
    print(f"jupiter_quote_health={'yes' if jupiter_quote_ok else 'no'}")
    print(f"jupiter_swap_build_health={'yes' if jupiter_swap_ok else 'no'}")
    print(f"signing_dependency={'yes' if signing_ok else 'no'}")
    print(f"wallet_reconciliation_path={'yes' if isinstance(phantom_truth, dict) else 'no'}")
    print(f"live_truth_phantom_status={str(phantom_truth.get('status') or 'UNKNOWN')}")
    print(diagnosis)
    return 0 if diagnosis.startswith("OK:") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
