#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "state"


def _read_json(name: str) -> dict[str, Any]:
    path = STATE / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _age_s(name: str) -> float:
    path = STATE / name
    try:
        return round(time.time() - path.stat().st_mtime, 1)
    except Exception:
        return -1.0


def _count_targets(data: dict[str, Any]) -> int:
    targets = data.get("top_targets")
    return len(targets) if isinstance(targets, list) else 0


def _env_or_dotenv(name: str) -> str:
    val = os.getenv(name, "").strip()
    if val:
        return val
    env_file = ROOT / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            key, raw = line.split("=", 1)
            if key.strip() == name:
                return raw.strip().strip("\"'")
    except Exception:
        pass
    return ""


def main() -> int:
    blockers: list[str] = []
    warnings: list[str] = []

    governor = _read_json("capital_governor.json")
    dispatcher = _read_json("live_order_dispatcher.json")
    indodax_targets = _read_json("indodax_top_targets.json")
    indodax_scanner = _read_json("indodax_scanner_state.json")
    ai_patrol = _read_json("ai_patrol.json")

    if not governor:
        blockers.append("capital_governor_missing")
    if not dispatcher:
        warnings.append("live_order_dispatcher_missing")

    allow_orders = bool(governor.get("allow_new_orders", False))
    reason = str(governor.get("allow_new_orders_reason") or "").strip()
    if not allow_orders:
        blockers.append(f"orders_blocked:{reason or 'capital_governor_orders_disabled'}")

    if bool(governor.get("global_hard_stop", False)):
        blockers.append(
            "global_hard_stop:"
            + str(governor.get("global_hard_stop_reason") or reason or "unknown")
        )

    if bool(governor.get("daily_reset_pending", False)):
        blockers.append(
            "daily_reset_pending:"
            + str(governor.get("daily_reset_reason") or reason or "unknown")
        )

    if str(dispatcher.get("status") or "").upper().startswith("BLOCKED"):
        dispatcher_reason = str(dispatcher.get("reason") or "").strip()
        if not dispatcher_reason:
            child_reasons = []
            for key in ("indodax",):
                child = dispatcher.get(key)
                if isinstance(child, dict) and child.get("reason"):
                    child_reasons.append(f"{key}:{child.get('reason')}")
            dispatcher_reason = "; ".join(child_reasons)
        blockers.append("dispatcher_blocked:" + (dispatcher_reason or "unknown"))

    target_count = _count_targets(indodax_targets)
    if target_count > 0 and not allow_orders:
        blockers.append(f"{target_count}_targets_visible_but_orders_blocked")

    scanner_status = str(indodax_scanner.get("source_status") or "").upper()
    pairs_checked = int(float(indodax_scanner.get("pairs_checked", 0) or 0))
    if scanner_status in {"NO_DATA", "SOURCE_FAILED"} and pairs_checked > 0:
        blockers.append(f"indodax_scanner_status_inconsistent:{scanner_status}_pairs_{pairs_checked}")

    telegram_token = bool(_env_or_dotenv("KIBOT_TELEGRAM_TOKEN") or _env_or_dotenv("TELEGRAM_BOT_TOKEN"))
    telegram_chat = bool(_env_or_dotenv("KIBOT_TELEGRAM_CHAT_ID") or _env_or_dotenv("TELEGRAM_CHAT_ID"))
    if not telegram_token or not telegram_chat:
        warnings.append("telegram_env_missing")

    if ai_patrol:
        runtime_semantics = ai_patrol.get("runtime_semantics")
        telegram = ai_patrol.get("telegram")
        if not isinstance(runtime_semantics, dict):
            blockers.append("ai_patrol_missing_runtime_semantics")
        if not isinstance(telegram, dict):
            blockers.append("ai_patrol_missing_telegram_status")
    else:
        warnings.append("ai_patrol_missing")

    stale = []
    for name in (
        "capital_governor.json",
        "indodax_top_targets.json",
        "ai_patrol.json",
    ):
        age = _age_s(name)
        if age < 0:
            stale.append(f"{name}:missing")
        elif age > 600:
            stale.append(f"{name}:stale_{int(age)}s")
    if stale:
        warnings.extend(stale)

    if blockers:
        print("ASSERT_RUNTIME_SEMANTICS_BLOCKED", "; ".join(blockers))
        if warnings:
            print("ASSERT_RUNTIME_SEMANTICS_WARN", "; ".join(warnings))
        return 1

    print("ASSERT_RUNTIME_SEMANTICS_OK", "warnings=" + ",".join(warnings) if warnings else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
