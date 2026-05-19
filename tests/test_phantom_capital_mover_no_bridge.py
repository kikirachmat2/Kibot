from Core.Treasury.phantom_capital_mover import write_phantom_capital_mover


def test_phantom_capital_mover_bridge_on():
    state = write_phantom_capital_mover({})
    assert state["bridge"] == "ON"
    assert state["withdrawal"] == "ON"
