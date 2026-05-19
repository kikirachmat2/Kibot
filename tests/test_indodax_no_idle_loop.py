import asyncio

from Core.Decision.indodax_no_idle_loop import IndodaxNoIdleLoop


def test_indodax_no_idle_loop_writes_state():
    state = asyncio.run(IndodaxNoIdleLoop().tick())
    assert state["next_action"] == "SCAN_NEXT"

