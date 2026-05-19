#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.request


def main() -> int:
    try:
        payload = json.loads(urllib.request.urlopen("http://127.0.0.1:8787/api/control-plane", timeout=10).read().decode())
    except Exception as exc:
        print(f"control_plane_unreachable:{exc}")
        return 1
    if "server_telemetry" not in payload or "indodax_top_targets" not in payload or "phantom_top_targets" not in payload:
        print("missing_freshness_wrappers")
        return 1
    for key in ("server_telemetry", "indodax_top_targets", "phantom_top_targets"):
        node = payload.get(key, {})
        if not isinstance(node, dict) or "age_s" not in node or "fresh" not in node:
            print(f"missing_freshness_fields:{key}")
            return 1
    print("ASSERT_DASHBOARD_REALTIME_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
