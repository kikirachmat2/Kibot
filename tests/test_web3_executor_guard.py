import json
import Core.Web3.web3_executor_guard as guard_module
from Core.Web3.web3_executor_guard import Web3ExecutorGuard


def test_web3_executor_guard_rejects_missing_stoploss(tmp_path, monkeypatch):
    guard = Web3ExecutorGuard()
    treasury = {'status': 'OK', 'reconciliation': {'matches_user_wallet': True}}
    route = {'allowed': True, 'network': 'solana'}
    safety = {'passed': True, 'score': 90, 'reason': 'ok', 'max_trade_idr': 25000}
    quote = {'quote_ok': True, 'gas_idr': 10000}
    res = guard.approve(treasury=treasury, route=route, safety=safety, quote=quote, budget_idr=20000, stop_loss_pct=0, take_profit_pct=2.0)
    assert not res['allowed']
    assert 'missing_stop_or_take_profit' in res['reason']


def test_web3_executor_guard_rejects_future_web3():
    guard = Web3ExecutorGuard()
    treasury = {'status': 'OK', 'reconciliation': {'matches_user_wallet': True}}
    route = {'allowed': False, 'reason': 'future_web3_scout_only', 'network': 'future_web3'}
    safety = {'passed': True, 'score': 90, 'reason': 'ok', 'max_trade_idr': 25000}
    quote = {'quote_ok': True, 'gas_idr': 10000}
    res = guard.approve(treasury=treasury, route=route, safety=safety, quote=quote, budget_idr=20000, stop_loss_pct=1.5, take_profit_pct=2.0)
    assert not res['allowed']
    assert 'future_web3_scout_only' in res['reason']


def test_web3_executor_guard_rejects_gas_unaffordable():
    guard = Web3ExecutorGuard()
    treasury = {
        'status': 'OK',
        'reconciliation': {'matches_user_wallet': True},
        'sol_balance': 0.0001,
    }
    route = {'allowed': True, 'network': 'solana', 'route_type': 'JUPITER_ROUTABLE'}
    safety = {'passed': True, 'score': 90, 'reason': 'ok', 'max_trade_idr': 25000, 'trade_size_idr': 25000}
    quote = {
        'quote_ok': True,
        'gas_idr': 1000000,
        'gas_floor_idr': 1000000,
        'gas_mode': 'blocked',
        'gas_affordable': False,
        'gas_reason': 'gasless_surcharge_exceeds_10pct_cap',
        'fee_intelligence': {'gas_affordable': False, 'gas_reason': 'gasless_surcharge_exceeds_10pct_cap'}
    }
    res = guard.approve(
        treasury=treasury,
        route=route,
        safety=safety,
        quote=quote,
        budget_idr=20000,
        stop_loss_pct=1.5,
        take_profit_pct=2.0,
        trade_size_idr=25000,
    )
    assert not res['allowed']
    assert 'gasless_surcharge_exceeds_10pct_cap' in res['reason'] or 'gas' in res['reason']


def test_web3_executor_guard_rejects_global_hard_stop(monkeypatch, tmp_path):
    monkeypatch.setattr(guard_module, "STATE_DIR", tmp_path)
    (tmp_path / "capital_governor.json").write_text(json.dumps({
        "allow_new_orders": False,
        "status": "BLOCKED_WITH_REASON",
        "allow_new_orders_reason": "global_daily_loss_cap_breached (-6000.00 <= -5000.00)",
        "daily_pnl_idr": -6000.0,
        "max_daily_loss_idr": 5000.0,
    }), encoding="utf-8")
    guard = Web3ExecutorGuard()
    treasury = {'status': 'OK', 'reconciliation': {'matches_user_wallet': True}}
    route = {'allowed': True, 'network': 'solana', 'route_type': 'JUPITER_ROUTABLE'}
    safety = {'passed': True, 'score': 90, 'reason': 'ok', 'max_trade_idr': 25000}
    quote = {'quote_ok': True, 'gas_idr': 10000}
    res = guard.approve(treasury=treasury, route=route, safety=safety, quote=quote, budget_idr=20000, stop_loss_pct=1.5, take_profit_pct=2.0)
    assert not res['allowed']
    assert 'global_daily_loss_cap_breached' in res['reason']
