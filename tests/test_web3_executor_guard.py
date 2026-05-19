import json
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
