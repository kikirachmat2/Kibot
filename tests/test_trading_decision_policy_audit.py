from __future__ import annotations

from tests._script_loader import load_script_module


def test_trading_decision_policy_audit_tightens(monkeypatch):
    mod = load_script_module("scripts/audit_trading_decision_policy.py", "audit_trading_decision_policy")
    monkeypatch.setattr(mod, "load_state_bundle", lambda: {
        "capital_governor": {"allow_new_orders": False, "max_daily_loss_idr": 4200.0, "daily_loss_breached": True, "allow_new_orders_reason": "global_daily_loss_cap_breached"},
        "no_trade_forensics": {"classification": "BROKEN_WAIT"},
    })
    monkeypatch.setattr(mod, "build_recovery_reset_plan", lambda bundle=None: {"after_reset_mode": "CONSERVATIVE_RECOVERY", "policy": {"allow_scale_up": False, "allow_micro_probe": False, "allow_exit_management": True}})
    monkeypatch.setattr(mod, "evaluate_churn_guard", lambda bundle=None: {"active": True, "reason": "flat churn"})
    monkeypatch.setattr(mod, "audit_net_growth", lambda bundle=None: {"status": "FLAT_CHURN", "profit_factor": 0.56})
    monkeypatch.setattr(mod, "audit_fill_quality", lambda bundle=None: {"status": "INCOMPLETE_ACCOUNTING"})
    monkeypatch.setattr(mod, "audit_daily_controls", lambda bundle=None: {"recommendation": "TIGHTEN"})
    monkeypatch.setattr(mod, "_read_json", lambda path, default: {"disabled_pairs": []})
    payload = mod.build_trading_decision_policy_audit()
    assert payload["status"] == "TIGHTEN"
    assert payload["decision"]["daily_loss_lock"] is True
    assert payload["decision"]["no_scale_up"] is True

