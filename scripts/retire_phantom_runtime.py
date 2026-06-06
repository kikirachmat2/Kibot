#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
ENV_FILE = ROOT / ".env"

SECRET_KEYS_TO_REMOVE = {
    "PHANTOM_PRIVATE_KEY",
    "KIBOT_PHANTOM_PRIVATE_KEY",
    "SOLANA_PRIVATE_KEY",
    "KIBOT_SOLANA_PRIVATE_KEY",
    "POLYMARKET_PRIVATE_KEY",
    "POLYMARKET_WALLET_ADDRESS",
    "SOLANA_RPC_URL",
    "KIBOT_SOLANA_RPC_URL",
}

FLAGS_TO_FORCE = {
    "KIBOT_RUNTIME_MODE": "LIVE_ONLY",
    "KIBOT_LIVE_TRADING_ENABLED": "true",
    "KIBOT_INDODAX_ONLY": "true",
    "KIBOT_PHANTOM_ENABLED": "false",
    "KIBOT_ENABLE_REAL_SWAP": "false",
    "KIBOT_ENABLE_REAL_BRIDGE": "false",
    "KIBOT_ENABLE_REAL_WITHDRAWAL": "false",
    "KIBOT_WITHDRAWAL_ENABLED": "false",
    "KIBOT_ENABLE_POLYMARKET_LIVE": "false",
    "KIBOT_SCANNER_ENABLE_WEB3": "false",
    "KIBOT_SCANNER_ENABLE_POLYMARKET": "false",
    "KIBOT_SCANNER_ENABLE_UNIVERSAL": "false",
}

STATE_PREFIXES = (
    "phantom",
    "web3",
    "pumpfun",
    "base_",
    "future_web3",
    "solana_",
    "polymarket",
)


def _rewrite_env() -> dict[str, int]:
    if not ENV_FILE.exists():
        return {"env_present": 0, "secrets_removed": 0, "flags_written": 0}

    removed = 0
    seen: set[str] = set()
    output: list[str] = []
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            output.append(raw)
            continue
        key = raw.split("=", 1)[0].strip()
        if key in SECRET_KEYS_TO_REMOVE:
            removed += 1
            continue
        if key in FLAGS_TO_FORCE:
            output.append(f"{key}={FLAGS_TO_FORCE[key]}")
            seen.add(key)
            continue
        output.append(raw)

    flags_written = 0
    for key, value in FLAGS_TO_FORCE.items():
        if key not in seen:
            output.append(f"{key}={value}")
            flags_written += 1

    ENV_FILE.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    return {"env_present": 1, "secrets_removed": removed, "flags_written": flags_written}


def _archive_runtime_state() -> dict[str, int]:
    if not STATE.exists():
        return {"archived_state_files": 0}
    archive = STATE / "archive" / "retired_phantom_web3"
    archive.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in STATE.iterdir():
        if not path.is_file():
            continue
        name = path.name.lower()
        if not name.endswith(".json") and not name.endswith(".jsonl"):
            continue
        if not any(name.startswith(prefix) for prefix in STATE_PREFIXES):
            continue
        target = archive / path.name
        if target.exists():
            target = archive / f"{path.stem}.{int(datetime.now(tz=timezone.utc).timestamp())}{path.suffix}"
        shutil.move(str(path), str(target))
        count += 1
    return {"archived_state_files": count}


def main() -> int:
    parser = argparse.ArgumentParser(description="Retire Phantom/Web3 runtime and enforce Indodax-only mode.")
    parser.add_argument("--archive-state", action="store_true", help="Move stale Phantom/Web3 state files into state/archive.")
    args = parser.parse_args()

    STATE.mkdir(parents=True, exist_ok=True)
    env_result = _rewrite_env()
    archive_result = _archive_runtime_state() if args.archive_state else {"archived_state_files": 0}
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "INDODAX_ONLY_ACTIVE",
        "phantom": "REMOVED_BY_OPERATOR",
        "reason": "operator_removed_compromised_wallet_use_indodax_only",
        **env_result,
        **archive_result,
    }
    (STATE / "phantom_retirement.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        "OK:PHANTOM_RETIRED "
        f"secrets_removed={env_result['secrets_removed']} "
        f"flags_written={env_result['flags_written']} "
        f"archived_state_files={archive_result['archived_state_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
