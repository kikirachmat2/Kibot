#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.growth_audit import build_critical_operator_questions
from Core.Support.money_movement_audit import load_state_bundle


def main() -> None:
    result = build_critical_operator_questions(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:CRITICAL_OPERATOR_QUESTIONS_WRITTEN")


if __name__ == "__main__":
    main()
