from Core.Web3.web3_executor_guard import Web3ExecutorGuard


def test_meme_guard_requires_exit_plan():
    guard = Web3ExecutorGuard()
    treasury = {"status": "OK", "reconciliation": {"matches_user_wallet": True}}
    route = {"allowed": True, "network": "solana"}
    safety = {"passed": True, "score": 90, "reason": "ok", "max_trade_idr": 5000}
    quote = {"quote_ok": True, "gas_idr": 1000}
    res = guard.approve(
        treasury=treasury,
        route=route,
        safety=safety,
        quote=quote,
        budget_idr=5000,
        stop_loss_pct=3,
        take_profit_pct=7,
        exit_plan=False,
    )
    assert not res["allowed"]
    assert "exit_plan_missing" in res["reason"]

