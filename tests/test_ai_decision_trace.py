import json
from pathlib import Path


def test_ai_decision_trace_file_shape():
    path = Path("state/ai_decision_trace.json")
    if not path.exists():
        path.write_text(json.dumps({
            "updated_at": "2026-05-19T00:00:00Z",
            "objective": "maximize_risk_adjusted_profit_for_boss",
            "market_summary": "",
            "best_action": "WAIT",
            "venue": "indodax",
            "reason": "bootstrap",
            "confidence": 0.0,
            "risk_status": "UNKNOWN",
            "next_check_seconds": 60,
        }, indent=2))
    data = json.loads(path.read_text())
    assert "best_action" in data
    assert "confidence" in data

