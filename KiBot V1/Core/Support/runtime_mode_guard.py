from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable


LIVE_ONLY = "LIVE_ONLY"
MAINTENANCE = "MAINTENANCE"
EMERGENCY_STOP = "EMERGENCY_STOP"

LEGACY_MODES = {
    "paper",
    "mock",
    "canary",
    "shadow",
    "dry-run",
    "simulation",
    "sim",
    "view-only",
    "controlled-live",
    "live",
    "real",
    "production",
}


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on", "live", "production"}


def normalize_runtime_mode(raw_mode: str | None) -> str:
    mode = str(raw_mode or "").strip().lower()
    if mode in {"", LIVE_ONLY.lower()}:
        return LIVE_ONLY
    if mode in {"maintenance"}:
        return MAINTENANCE
    if mode in {"emergency_stop", "emergency-stop", "emergency"}:
        return EMERGENCY_STOP
    if mode in LEGACY_MODES:
        return LIVE_ONLY
    return LIVE_ONLY if _flag("KIBOT_LIVE_TRADING_ENABLED", "true") else MAINTENANCE


def is_live_only_mode(raw_mode: str | None = None) -> bool:
    return normalize_runtime_mode(raw_mode) == LIVE_ONLY


def assert_runtime_live_only(raw_mode: str | None = None) -> None:
    mode = normalize_runtime_mode(raw_mode)
    if mode != LIVE_ONLY:
        raise RuntimeError(f"INVALID_RUNTIME_MODE:{mode}")


@dataclass(frozen=True)
class RuntimeGuardStatus:
    runtime_mode: str
    live_trading_enabled: bool
    withdrawal_enabled: bool


def read_runtime_guard_status() -> RuntimeGuardStatus:
    mode = normalize_runtime_mode(os.getenv("KIBOT_RUNTIME_MODE", os.getenv("KIBOT_TRADING_MODE", "")))
    live_trading = _flag("KIBOT_LIVE_TRADING_ENABLED", "true" if mode == LIVE_ONLY else "false")
    withdrawal = _flag("KIBOT_WITHDRAWAL_ENABLED", "false")
    return RuntimeGuardStatus(
        runtime_mode=mode,
        live_trading_enabled=live_trading,
        withdrawal_enabled=withdrawal,
    )
