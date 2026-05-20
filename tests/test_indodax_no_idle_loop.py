import asyncio
import json
from unittest.mock import AsyncMock, patch

from Core.Decision import indodax_no_idle_loop as loop_module
from Core.Decision.indodax_no_idle_loop import IndodaxNoIdleLoop


def test_indodax_no_idle_loop_writes_state(tmp_path, monkeypatch):
    monkeypatch.setattr(loop_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(loop_module, "STATE_FILE", tmp_path / "indodax_no_idle.json")
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "allow_new_orders": True,
        "status": "RECONCILED",
        "allow_new_orders_reason": "venue-scoped allowances active: indodax",
        "daily_pnl_idr": 0.0,
        "max_daily_loss_idr": 5000.0,
        "venues": {
            "indodax": {"allow_orders": True, "reason": "", "daily_loss_cap_idr": 5000.0, "daily_pnl_idr": 0.0}
        },
    }), encoding="utf-8")
    with patch.object(loop_module.IndodaxMarketScanner, "scan", AsyncMock(return_value={
        "source_status": "OK",
        "candidates": [],
        "best_candidate": {},
        "daily_pnl_pct": 0.0,
        "daily_pnl_idr": 0.0,
        "no_data_reason": "",
        "approved_candidates": [],
        "rejected_candidates": [],
        "pairs_checked": 0,
    })):
        state = asyncio.run(IndodaxNoIdleLoop().tick())
    assert state["next_action"] == "SCAN_NEXT"
