#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def _load_dotenv_flags() -> dict[str, str]:
    env_file = ROOT / ".env"
    flags: dict[str, str] = {}
    if not env_file.exists():
        return flags
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        key, value = raw.split("=", 1)
        flags[key.strip()] = value.strip().strip("\"'")
    return flags


def _flag(name: str, default: str = "") -> str:
    return os.getenv(name) or _load_dotenv_flags().get(name, default)


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def main() -> int:
    failures: list[str] = []
    if str(_flag("KIBOT_INDODAX_ONLY", "true")).lower() not in {"1", "true", "yes", "on"}:
        failures.append("KIBOT_INDODAX_ONLY_not_true")

    for key in (
        "KIBOT_PHANTOM_ENABLED",
        "KIBOT_ENABLE_REAL_SWAP",
        "KIBOT_ENABLE_REAL_BRIDGE",
        "KIBOT_ENABLE_REAL_WITHDRAWAL",
        "KIBOT_WITHDRAWAL_ENABLED",
        "KIBOT_ENABLE_POLYMARKET_LIVE",
        "KIBOT_SCANNER_ENABLE_WEB3",
        "KIBOT_SCANNER_ENABLE_POLYMARKET",
    ):
        if str(_flag(key, "false")).lower() in {"1", "true", "yes", "on"}:
            failures.append(f"{key}_must_be_false")

    live_truth = _read_json(STATE / "live_truth.json", {})
    if live_truth:
        if live_truth.get("platform_mode") != "INDODAX_ONLY":
            failures.append(f"live_truth_platform={live_truth.get('platform_mode')}")
        if live_truth.get("phantom") not in (None, {}, []):
            failures.append("live_truth_has_active_phantom_key")
        retired = live_truth.get("retired_venues", {}) if isinstance(live_truth.get("retired_venues"), dict) else {}
        phantom = retired.get("phantom", {}) if isinstance(retired.get("phantom"), dict) else {}
        if phantom and phantom.get("status") != "REMOVED_BY_OPERATOR":
            failures.append(f"live_truth_phantom_not_removed:{phantom.get('status')}")

    governor = _read_json(STATE / "capital_governor.json", {})
    venues = governor.get("venues", {}) if isinstance(governor, dict) else {}
    phantom_venue = venues.get("phantom") if isinstance(venues, dict) else None
    if isinstance(phantom_venue, dict) and phantom_venue.get("allow_orders"):
        failures.append("capital_governor_allows_phantom")
    if governor and governor.get("allow_phantom_orders"):
        failures.append("capital_governor_allow_phantom_orders_true")

    dispatcher = _read_json(STATE / "live_order_dispatcher.json", {})
    if dispatcher and isinstance(dispatcher.get("phantom"), dict):
        failures.append("dispatcher_has_active_phantom_key")
    if failures:
        print("FAIL:INDODAX_ONLY_RUNTIME " + ",".join(failures))
        return 1
    print("OK:INDODAX_ONLY_RUNTIME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
