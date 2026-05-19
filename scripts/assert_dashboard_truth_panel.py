#!/usr/bin/env python3
from __future__ import annotations

import urllib.request


def main() -> int:
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:8787/api/control-plane", timeout=10).read().decode()
    except Exception as exc:
        print(f"control_plane_unreachable:{exc}")
        return 1
    for needle in ("indodax_top_targets", "phantom_top_targets", "system_truth", "server_telemetry"):
        if needle not in raw:
            print(f"dashboard_panel_missing:{needle}")
            return 1
    print("ASSERT_DASHBOARD_TRUTH_PANEL_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
