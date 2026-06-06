from Core.Decision.engine_independence import write_engine_independence


def test_engine_independence_off():
    state = write_engine_independence({})
    assert state["bridge"] == "OFF"
    assert state["withdrawal"] == "OFF"
    assert state["global_mode"] == "INDODAX_ONLY_LIVE"
    assert state["phantom_engine"]["status"] == "REMOVED_BY_OPERATOR"
