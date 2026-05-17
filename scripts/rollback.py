#!/usr/bin/env python3
import json
import time
import sys
from pathlib import Path

def trigger_rollback(reason: str = "Manual Trigger"):
    project_root = Path(__file__).resolve().parent.parent
    
    # 1. Ensure state directory exists
    state_dir = project_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Write KILL_SWITCH file
    kill_switch_path = state_dir / "KILL_SWITCH"
    payload = {
        "status": "triggered",
        "triggered_at": time.strftime("%Y-%m-%d %H:%M:%S WIB", time.localtime()),
        "reason": reason
    }
    
    with open(kill_switch_path, "w") as f:
        json.dump(payload, f, indent=4)
        
    print(f"🚨 KILL_SWITCH TRIGGERED: Created {kill_switch_path}")
    print(f"Reason: {reason}")
    
    # 3. Securely override .env flags
    def set_env(name: str, value: str):
        env_path = project_root / ".env"
        if not env_path.exists():
            return
        content = env_path.read_text()
        lines = content.splitlines()
        found = False
        for i, line in enumerate(lines):
            striped = line.strip()
            if striped.startswith(f"{name}=") or striped.startswith(f"#{name}=") or striped == name or striped == f"#{name}":
                lines[i] = f"{name}={value}"
                found = True
                break
        if not found:
            lines.append(f"{name}={value}")
        env_path.write_text("\n".join(lines) + "\n")
        print(f"Disabled {name}={value} in .env")

    set_env("KIBOT_CANARY_LIVE_ENABLED", "false")
    set_env("KIBOT_LIVE_TRADING_ENABLED", "false")
    
    # 4. Trigger Telegram alert if possible
    # We add sys.path so we can import Core modules if run from other dirs
    sys.path.insert(0, str(project_root))
    try:
        from Core.Support.sovereign_notifier import telegram_send
        telegram_send(f"🚨 *EMERGENCY ROLLBACK TRIGGERED* 🚨\nReason: `{reason}`\nLive trading has been completely disabled and state/KILL_SWITCH has been activated.")
    except Exception as e:
        print(f"Could not send Telegram notification: {e}")

if __name__ == "__main__":
    reason = sys.argv[1] if len(sys.argv) > 1 else "CLI Rollback Command"
    trigger_rollback(reason)
