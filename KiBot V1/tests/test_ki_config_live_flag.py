from __future__ import annotations

import os
import subprocess
import sys


def _probe_live_flag(env_overrides: dict[str, str]) -> str:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": ".",
    }
    env.update(env_overrides)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from Core.Support.ki_config import KiConfig; print(KiConfig.LIVE_TRADING_ENABLED)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout.strip()


def test_explicit_live_false_is_not_overridden_by_live_mode():
    assert _probe_live_flag(
        {
            "KIBOT_TRADING_MODE": "controlled-live",
            "KIBOT_LIVE_TRADING_ENABLED": "false",
        }
    ) == "False"


def test_explicit_live_true_enables_live_mode():
    assert _probe_live_flag(
        {
            "KIBOT_TRADING_MODE": "controlled-live",
            "KIBOT_LIVE_TRADING_ENABLED": "true",
        }
    ) == "True"
