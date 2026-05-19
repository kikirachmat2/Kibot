from Core.Decision.engine_independence import write_engine_independence


def test_engine_independence_off():
    state = write_engine_independence({})
    assert state["bridge"] == "OFF"
    assert state["withdrawal"] == "OFF"
    assert state["global_mode"] == "CONTROLLED_LIVE_INDEPENDENT_ENGINES"

