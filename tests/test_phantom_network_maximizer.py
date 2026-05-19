from Core.Treasury.phantom_network_maximizer import write_phantom_network_maximizer


def test_phantom_network_maximizer_has_action():
    state = write_phantom_network_maximizer({"recommended_action": "SCAN_NEXT"})
    assert state["recommended_action"] == "SCAN_NEXT"

