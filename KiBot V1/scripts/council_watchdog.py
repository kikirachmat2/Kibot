#!/usr/bin/env python3
"""
Council Watchdog for KiBot Sovereign Master Node.
Monitors kibot-master.service and UDP port 9991.
Sends throttled Telegram alerts if downtime exceeds 3 minutes.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Ensure .env is loaded if not already in os.environ
env_file = ROOT / ".env"
if env_file.exists() and "KIBOT_SECRET" not in os.environ:
    try:
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    except Exception:
        pass

from Core.sovereign_notifier import SovereignNotifier

STATE_FILE = ROOT / "state" / "council_watchdog.json"
DOWNTIME_THRESHOLD_SEC = 180  # 3 minutes


def is_service_active(service_name: str = "kibot-master.service") -> bool:
    try:
        res = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True, timeout=5)
        return res.stdout.strip() == "active"
    except Exception:
        return False


def is_udp_port_open(port: int = 9991) -> bool:
    try:
        res = subprocess.run(["ss", "-uln", f"sport = :{port}"], capture_output=True, text=True, timeout=5)
        return str(port) in res.stdout
    except Exception:
        return False


def get_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"status": "ok", "down_since": None, "alert_sent": False}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[Watchdog] Warning: failed to save state: {e}", file=sys.stderr)


async def main() -> None:
    service_ok = is_service_active()
    udp_ok = is_udp_port_open()
    is_healthy = service_ok and udp_ok
    now = time.time()
    state = get_state()

    notifier = SovereignNotifier()

    if not is_healthy:
        if not state.get("down_since"):
            state["down_since"] = now
            state["status"] = "down"
            save_state(state)
            print(f"[Watchdog] MasterNode unhealthy (service={service_ok}, udp={udp_ok}). Tracking downtime...")
            return

        down_duration = now - float(state["down_since"])
        print(f"[Watchdog] MasterNode down for {int(down_duration)}s (threshold: {DOWNTIME_THRESHOLD_SEC}s).")
        if down_duration >= DOWNTIME_THRESHOLD_SEC and not state.get("alert_sent"):
            msg = (
                f"🚨 *[KiBot Sovereign Alert]* `kibot-master` is *DOWN* on SG1 for {int(down_duration // 60)}m {int(down_duration % 60)}s!\n\n"
                f"• Systemd Service: `{'ACTIVE' if service_ok else 'INACTIVE'}`\n"
                f"• UDP Port 9991: `{'LISTENING' if udp_ok else 'NOT LISTENING'}`\n"
                f"• Host: SG1 (`152.69.218.198`)"
            )
            print(f"[Watchdog] Sending Telegram downtime alert...")
            await notifier.send_message(msg, incident_key="COUNCIL_DOWNTIME", incident_cooldown_sec=1800)
            state["alert_sent"] = True
            save_state(state)
    else:
        if state.get("status") == "down" and state.get("alert_sent"):
            down_total = int(now - float(state.get("down_since") or now))
            msg = (
                f"✅ *[KiBot Sovereign Alert]* `kibot-master` has *RECOVERED* on SG1!\n\n"
                f"• Downtime duration: {down_total}s\n"
                f"• Systemd Service: ACTIVE\n"
                f"• UDP Port 9991: LISTENING\n"
                f"• Host: SG1 (`152.69.218.198`)"
            )
            print(f"[Watchdog] Sending Telegram recovery alert...")
            await notifier.send_message(msg, incident_key="COUNCIL_RECOVERED", min_interval_sec=10)

        state = {"status": "ok", "down_since": None, "alert_sent": False, "last_check": now}
        save_state(state)
        print("[Watchdog] MasterNode is healthy (service=active, udp=listening).")


if __name__ == "__main__":
    asyncio.run(main())
