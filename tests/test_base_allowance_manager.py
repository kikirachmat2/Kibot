import json

import Core.Web3.base_allowance_manager as allowance_module
from Core.Web3.base_allowance_manager import BaseAllowanceManager


def test_base_allowance_manager_blocks_on_global_hard_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(allowance_module, "STATE_DIR", tmp_path)
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "allow_new_orders": False,
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders_reason": "global_daily_loss_cap_breached (-6000.00 <= -5000.00)",
        "daily_pnl_idr": -6000.0,
        "max_daily_loss_idr": 5000.0,
    }), encoding="utf-8")

    manager = BaseAllowanceManager(signer_present=True)
    readiness = manager.readiness()

    assert readiness["allowed"] is False
    assert "global_daily_loss_cap_breached" in readiness["reason"]
