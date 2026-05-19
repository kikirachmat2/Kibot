from Core.Decision.phantom_live_brain import write_phantom_live_brain


def test_phantom_live_brain_has_next_action():
    state = write_phantom_live_brain({})
    assert state["engine"] == "phantom"
    assert state["next_action"]
