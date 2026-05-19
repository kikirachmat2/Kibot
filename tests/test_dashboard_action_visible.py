from Core.Decision.autonomous_trading_brain import write_autonomous_trading_brain
from Core.Decision.indodax_live_brain import write_indodax_live_brain
from Core.Decision.phantom_live_brain import write_phantom_live_brain


def test_dashboard_action_states_exist():
    assert write_autonomous_trading_brain({})["next_action"]
    assert write_indodax_live_brain({})["next_action"]
    assert write_phantom_live_brain({})["next_action"]
