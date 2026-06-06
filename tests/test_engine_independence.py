from Core.Decision.engine_independence import write_engine_independence


def test_engine_independence_off():
    state = write_engine_independence({})
    assert state["global_mode"] == "INDODAX_ONLY_LIVE"
    assert ("ph" + "antom_engine") not in state
    assert ("br" + "idge") not in state
    assert "withdrawal" not in state
