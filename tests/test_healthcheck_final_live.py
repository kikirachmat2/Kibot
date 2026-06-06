from scripts.healthcheck import check_json_states


def test_healthcheck_accepts_indodax_only_state_schema(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "leadlag_alpha.json").write_text('{"qualified_signals":[{"symbol":"btc_idr"}],"opportunities":[{"symbol":"btc_idr"}],"last_run_timestamp":0}')
    (state_dir / "scanner_runtime.json").write_text('{"current_interval":2.0,"mode":"NORMAL","telemetry":{"cpu_percent":0.0}}')
    (state_dir / "market_rotation.json").write_text('{"market_regime":"NEUTRAL","regime_index":0.0}')
    (state_dir / "punishment_state.json").write_text('{"schema_version":1,"status":"idle","records":{},"quarantined":[]}')
    (state_dir / "expected_value.json").write_text('{"schema_version":1,"status":"idle","strategies":{}}')
    (state_dir / "ai_decision_trace.json").write_text('{"updated_at":"2026-05-19T00:00:00Z","objective":"maximize_risk_adjusted_profit_for_boss","market_summary":"","best_action":"WAIT","venue":"indodax","reason":"bootstrap","confidence":0.0,"risk_status":"UNKNOWN","next_check_seconds":60}')
    monkeypatch.setenv("KIBOT_ENV", "test")
    monkeypatch.setenv("KIBOT_HEALTHCHECK_ALLOW_BOOTSTRAP", "true")
    check_json_states(state_dir)
