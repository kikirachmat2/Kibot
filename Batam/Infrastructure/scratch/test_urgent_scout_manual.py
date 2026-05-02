import json
import time
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
STATE_DIR = ROOT_DIR / "state"
URGENT_FILE = STATE_DIR / "urgent_scout.json"

def trigger_test():
    pair = "BTC_IDR"
    data = {"at": time.time(), "pair": pair}
    STATE_DIR.mkdir(exist_ok=True)
    URGENT_FILE.write_text(json.dumps(data), encoding="utf-8")
    print(f"Triggered urgent scout for {pair}")

if __name__ == "__main__":
    trigger_test()
