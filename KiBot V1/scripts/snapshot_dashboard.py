#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

URL = "http://127.0.0.1:8787/"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        print("SKIP:PLAYWRIGHT_NOT_INSTALLED")
        return 0

    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "dashboard-v6.png"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1200}, locale="id-ID")
            page.goto(URL, wait_until="networkidle", timeout=15000)
            page.screenshot(path=str(out_path), full_page=True)
            text = page.locator("body").inner_text()
            for needle in ("LIVE_ONLY", "AI System", "Indodax"):
                if needle not in text:
                    print(f"FAIL:missing_text:{needle}")
                    return 1
            for needle in ("Controlled Live", "Indodax Shadow", "VIEW ONLY", "Live trading OFF"):
                if needle in text:
                    print(f"FAIL:legacy_visible:{needle}")
                    return 1
            browser.close()
    except Exception as exc:
        print(f"FAIL:snapshot_error:{exc}")
        return 1

    print(f"OK:SNAPSHOT_WRITTEN {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
