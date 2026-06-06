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

    for key in ("KIBOT_WITHDRAWAL_ENABLED",):
        if str(_flag(key, "false")).lower() in {"1", "true", "yes", "on"}:
            failures.append(f"{key}_must_be_false")

    live_truth = _read_json(STATE / "live_truth.json", {})
    if live_truth:
        if live_truth.get("platform_mode") != "INDODAX_ONLY":
            failures.append(f"live_truth_platform={live_truth.get('platform_mode')}")
        if live_truth.get("retired_venues") not in (None, {}, []):
            failures.append("live_truth_has_retired_venues_key")

    governor = _read_json(STATE / "capital_governor.json", {})
    venues = governor.get("venues", {}) if isinstance(governor, dict) else {}
    if isinstance(venues, dict) and len(set(venues.keys()) - {"indodax"}) > 0:
        failures.append("capital_governor_has_removed_venue")

    dispatcher = _read_json(STATE / "live_order_dispatcher.json", {})
    if dispatcher and dispatcher.get("retired_venues"):
        failures.append("dispatcher_has_retired_venues_key")
    if failures:
        print("FAIL:INDODAX_ONLY_RUNTIME " + ",".join(failures))
        return 1
    print("OK:INDODAX_ONLY_RUNTIME")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
