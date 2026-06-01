#!/usr/bin/env python3
from __future__ import annotations

import json

from Core.Support.money_movement_audit import candidate_pipeline_audit, load_state_bundle


def main() -> None:
    result = candidate_pipeline_audit(load_state_bundle())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("status_marker=OK:CANDIDATE_PIPELINE_AUDITED")


if __name__ == "__main__":
    main()
