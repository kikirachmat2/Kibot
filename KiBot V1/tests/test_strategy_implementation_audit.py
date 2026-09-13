from pathlib import Path


def test_strategy_audit_exists():
    path = Path("docs/audits/STRATEGY_IMPLEMENTATION_AUDIT.md")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Strategy Implementation Audit" in text
    assert "Indodax executor" in text
