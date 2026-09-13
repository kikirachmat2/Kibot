from __future__ import annotations

import json

from Core.Support.telegram_throttle import telegram_send


def test_telegram_outbox_records_sanitized_disabled_send(tmp_path, monkeypatch):
    outbox = tmp_path / "telegram_outbox.jsonl"
    monkeypatch.setenv("KIBOT_TELEGRAM_OUTBOX_FILE", str(outbox))
    monkeypatch.delenv("KIBOT_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("KIBOT_TELEGRAM_CHAT_ID", raising=False)

    ok = telegram_send(
        "Telegram audit api_key=SHOULD_NOT_LEAK token=ALSO_SECRET",
        channel="unit",
        incident_key="UNIT_INCIDENT",
    )

    assert ok is False
    rows = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["status"] == "disabled"
    assert rows[-1]["channel"] == "unit"
    assert rows[-1]["incident_key"] == "UNIT_INCIDENT"
    assert rows[-1]["message_hash"]
    assert "SHOULD_NOT_LEAK" not in rows[-1]["message_preview"]
    assert "ALSO_SECRET" not in rows[-1]["message_preview"]
    assert "SECRET_FOUND_REDACTED" in rows[-1]["message_preview"]
