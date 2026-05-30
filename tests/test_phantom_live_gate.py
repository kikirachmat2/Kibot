from pathlib import Path


def test_phantom_diagnosis_script_exists():
    assert Path("scripts/diagnose_phantom_runtime.py").exists()
    assert Path("scripts/assert_phantom_live_ready.py").exists()


def test_jupiter_gateway_exists():
    assert Path("Core/Exchange/jupiter_gateway.py").exists()
