from Core.Decision.autonomous_trading_brain import write_autonomous_trading_brain


def test_autonomous_brain_has_next_action():
    state = write_autonomous_trading_brain({})
    assert state["mode"] == "LIVE_AUTONOMOUS_TRADING"
    assert state["next_action"]
