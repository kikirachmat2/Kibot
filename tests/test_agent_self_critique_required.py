from __future__ import annotations

from pathlib import Path


def test_agent_self_critique_writer_exists() -> None:
    assert Path("scripts/write_agent_self_critique.py").exists()

