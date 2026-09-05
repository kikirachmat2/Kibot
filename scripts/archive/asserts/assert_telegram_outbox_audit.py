#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Core.Support.telegram_throttle import telegram_send


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        outbox = Path(tmp) / "telegram_outbox.jsonl"
        os.environ["KIBOT_TELEGRAM_OUTBOX_FILE"] = str(outbox)
        os.environ.pop("KIBOT_TELEGRAM_TOKEN", None)
        os.environ.pop("KIBOT_TELEGRAM_CHAT_ID", None)

        sent = telegram_send(
            "test token=SECRET_SHOULD_NOT_LEAK private_key=SUPERSECRET123",
            channel="assertion",
            incident_key="ASSERT_TELEGRAM_OUTBOX",
        )
        if sent:
            print("FAIL:send_should_be_disabled_without_credentials")
            return 1
        if not outbox.exists():
            print("FAIL:telegram_outbox_missing")
            return 1

        lines = [line for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            print("FAIL:telegram_outbox_empty")
            return 1
        row = json.loads(lines[-1])
        if row.get("status") != "disabled":
            print(f"FAIL:unexpected_status={row.get('status')}")
            return 1
        preview = str(row.get("message_preview") or "")
        if "SUPERSECRET123" in preview or "SECRET_SHOULD_NOT_LEAK" in preview:
            print("FAIL:secret_leaked_in_preview")
            return 1
        required = {"ts", "status", "channel", "incident_key", "message_hash", "message_preview", "reason"}
        missing = sorted(required - set(row))
        if missing:
            print(f"FAIL:missing_keys={missing}")
            return 1

    print("OK:TELEGRAM_OUTBOX_AUDIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
