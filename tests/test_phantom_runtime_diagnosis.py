from pathlib import Path
import json

from scripts.diagnose_phantom_runtime import _mask_url


def test_mask_url_hides_path_query():
    assert _mask_url("https://example.com/path?secret=1") == "https://example.com"


def test_live_truth_phantom_status_can_be_locked():
    path = Path("state/live_truth.json")
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    phantom = data.get("phantom", {})
    assert "status" in phantom
