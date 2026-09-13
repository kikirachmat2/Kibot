#!/usr/bin/env python3
"""
KiBot Sovereign Control Plane Exporter.
Exports the complete /api/control-plane snapshot to a static JSON file.
Enables lightweight serving via Nginx without running a heavy Uvicorn server in SG1.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Core.Intelligence.kibot_dashboard import _build_control_plane_payload

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [ExportControlPlane] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ExportControlPlane")

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "state" / "control_plane.json"


def export_control_plane_snapshot(output_path: Path = DEFAULT_OUTPUT_PATH) -> bool:
    """Export current control plane payload atomically to output_path."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _build_control_plane_payload()
        tmp_file = output_path.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp_file.replace(output_path)
        logger.info(f"Successfully exported control plane snapshot to {output_path} ({output_path.stat().st_size} bytes)")
        return True
    except Exception as exc:
        logger.error(f"Failed to export control plane snapshot: {exc}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Export KiBot Control Plane snapshot to static JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"Target output JSON file path (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously in a loop instead of single execution.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Refresh interval in seconds when running in daemon mode (default: 60s).",
    )
    args = parser.parse_args()

    if args.daemon:
        logger.info(f"Starting continuous export loop (interval: {args.interval}s, output: {args.output})...")
        while True:
            export_control_plane_snapshot(args.output)
            time.sleep(max(10, args.interval))
    else:
        success = export_control_plane_snapshot(args.output)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
