from Core.Decision.indodax_live_brain import write_indodax_live_brain


def test_indodax_live_brain_has_next_action():
    state = write_indodax_live_brain({})
    assert state["engine"] == "indodax"
    assert state["next_action"]
