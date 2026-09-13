from __future__ import annotations

import json
from pathlib import Path


def test_scanner_executor_contract_written():
    path = Path("state/scanner_executor_contract.json")
    if not path.exists():
        from Core.Scanner.scanner_executor_contract import ScannerExecutorContract
        ScannerExecutorContract().write_contract_state()
    assert path.exists()
    payload = json.loads(path.read_text())
    assert payload.get("routes")
    assert all(isinstance(route.get("scanner_state_file"), str) for route in payload["routes"])
