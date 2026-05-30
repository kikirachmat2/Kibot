from __future__ import annotations

from pathlib import Path


def test_phantom_gateway_file_exists():
    assert Path("Core/Exchange/jupiter_gateway.py").exists()

