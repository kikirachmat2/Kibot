from Core.Web3.pumpfun_native_executor import PumpfunNativeExecutor


def test_pumpfun_native_executor_blocks_without_signer(tmp_path, monkeypatch):
    monkeypatch.setenv("PUMPFUN_NATIVE_EXECUTOR_ENABLED", "true")
    monkeypatch.delenv("PUMPFUN_NATIVE_SIGNER_PATH", raising=False)
    monkeypatch.delenv("PUMPFUN_USE_SERVER_SOLANA_SIGNER", raising=False)
    monkeypatch.delenv("PHANTOM_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PUMPFUN_NATIVE_PROGRAM_ID", raising=False)
    monkeypatch.setattr("Core.Web3.pumpfun_native_executor.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.pumpfun_native_executor.NATIVE_STATE_FILE", tmp_path / "pumpfun_native_executor_state.json")
    ex = PumpfunNativeExecutor()
    status = ex.get_status()
    assert status["status"] == "BLOCKED_WITH_REASON"
    assert status["reason"] == "signer_missing"


def test_pumpfun_native_executor_blocks_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PUMPFUN_NATIVE_EXECUTOR_ENABLED", "false")
    monkeypatch.setattr("Core.Web3.pumpfun_native_executor.STATE_DIR", tmp_path)
    monkeypatch.setattr("Core.Web3.pumpfun_native_executor.NATIVE_STATE_FILE", tmp_path / "pumpfun_native_executor_state.json")
    ex = PumpfunNativeExecutor()
    status = ex.get_status()
    assert status["status"] == "BLOCKED_WITH_REASON"
    assert status["reason"] == "native_executor_not_enabled"
