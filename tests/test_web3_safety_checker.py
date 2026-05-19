from Core.Web3.web3_safety_checker import Web3SafetyChecker


def test_web3_safety_checker_rejects_unsafe_token():
    checker = Web3SafetyChecker()
    res = checker.evaluate({
        'liquidity': 100000,
        'volume': 50000,
        'spread_pct': 0.5,
        'slippage_pct': 0.5,
        'contract_age_days': 30,
        'holder_concentration_pct': 10,
        'honeypot': True,
        'token_type': 'evm',
        'ev': 10,
    })
    assert not res['passed']
    assert res['max_trade_idr'] == 0


def test_web3_safety_checker_rejects_negative_ev():
    checker = Web3SafetyChecker()
    res = checker.evaluate({
        'liquidity': 100000,
        'volume': 50000,
        'spread_pct': 0.5,
        'slippage_pct': 0.5,
        'contract_age_days': 30,
        'holder_concentration_pct': 10,
        'token_type': 'solana',
        'ev': -1,
    })
    assert not res['passed']
    assert 'negative_ev' in res['reason']
