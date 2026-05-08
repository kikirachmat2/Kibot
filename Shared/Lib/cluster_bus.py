from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Tuple

CLUSTER_HOSTS = {
    "BATAM": os.getenv("KIBOT_BATAM_HOST", "168.110.201.228").strip(),
    "EXECUTOR": os.getenv("KIBOT_EXECUTOR_HOST", "213.35.118.26").strip(),
    "SCANNER": os.getenv("KIBOT_SCANNER_HOST", "152.69.218.198").strip(),
}


def resolve_host(role: str, fallback: str = "") -> str:
    role_key = str(role or "").strip().upper()
    env_key = f"KIBOT_{role_key}_HOST"
    return (os.getenv(env_key) or CLUSTER_HOSTS.get(role_key) or fallback).strip()


def resolve_manager_endpoint() -> Tuple[str, int]:
    host = (
        os.getenv("KIBOT_MANAGER_HOST")
        or os.getenv("KIBOT_MANAGER_UDP_HOST")
        or CLUSTER_HOSTS["BATAM"]
    ).strip()
    port = int(
        os.getenv(
            "KIBOT_MANAGER_UDP_PORT",
            os.getenv("KIBOT_MANAGER_PORT", os.getenv("KIBOT_MANAGER_UDP_TARGET_PORT", os.getenv("KIBOT_MANAGER_UDP_BIND_PORT", "9999"))),
        )
    )
    return host, port


def sign_udp_payload(payload: Dict[str, Any], secret: str | None = None) -> Dict[str, Any]:
    message = dict(payload)
    message.setdefault("sentAtEpochMs", int(time.time() * 1000))
    message.setdefault("timestamp", int(time.time()))
    key = (secret or os.getenv("KIBOT_SIGNAL_KEY", "SOVEREIGN_DEFAULT_SIGNAL_SECRET")).encode("utf-8")
    canonical = json.dumps(message, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    signature = base64.b64encode(hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
    message["signature"] = signature
    return message


def verify_udp_payload(payload: Dict[str, Any], signature: str, secret: str | None = None) -> bool:
    key = (secret or os.getenv("KIBOT_SIGNAL_KEY", "SOVEREIGN_DEFAULT_SIGNAL_SECRET")).encode("utf-8")
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    expected = base64.b64encode(hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")
    return hmac.compare_digest(signature or "", expected)
