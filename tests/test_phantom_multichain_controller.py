from Core.Treasury.phantom_multichain_controller import PhantomMultichainController


def test_controller_base_scouting_and_future_web3():
    c = PhantomMultichainController()
    reg = c.refresh()
    assert reg['base']['status'] in {'LIVE_READY', 'BLOCKED_WITH_REASON'}
    assert reg['future_web3']['status'] in {'LIVE_READY', 'BLOCKED_WITH_REASON'}
