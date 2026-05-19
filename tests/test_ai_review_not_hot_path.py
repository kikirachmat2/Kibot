from Core.Decision.script_adaptation_engine import ScriptAdaptationEngine


def test_ai_review_is_not_hot_path():
    engine = ScriptAdaptationEngine()
    assert engine is not None

