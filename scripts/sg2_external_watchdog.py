#!/usr/bin/env python3
"""
KiBot Sentinel — SG2 External Watchdog & Off-Server State Mirror.
Monitors SG1 Master Node independently from SG2.
Maintains state backups of SG1 and sends Telegram alerts upon sustained downtime.
Operates with strict resource boundaries to preserve host priority for client workloads.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [SG2Sentinel] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("SG2Sentinel")

DEFAULT_SG1_HOST = "152.69.218.198"
DEFAULT_SSH_KEY = str(Path.home() / ".ssh" / "batam.pem")
DEFAULT_STATE_DIR = Path("./state")
DEFAULT_BACKUP_DIR = Path("./backups/sg1_mirror")
DEFAULT_POLL_INTERVAL_S = 30
DEFAULT_DOWN_THRESHOLD_S = 180
DEFAULT_BACKUP_INTERVAL_S = 7200


def send_telegram_alert(
    token: str,
    chat_id: str,
    message: str,
    timeout: float = 10.0,
) -> bool:
    """Send alert to Telegram channel via official Bot API."""
    if not token or not chat_id:
        logger.warning("Telegram credentials not configured. Skipping notification.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status == 200
    except Exception as exc:
        logger.error(f"Failed to send Telegram alert: {exc}")
        return False


def probe_sg1_status(
    host: str = DEFAULT_SG1_HOST,
    ssh_key: str = DEFAULT_SSH_KEY,
    user: str = "ubuntu",
    timeout: float = 10.0,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Perform remote health probe of SG1 via SSH.
    Checks:
    1. SSH connectivity
    2. kibot-master.service state
    3. UDP port 9991 listener state
    """
    cmd = [
        "ssh",
        "-i",
        ssh_key,
        "-o",
        f"ConnectTimeout={int(timeout)}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        f"{user}@{host}",
        "echo -n 'SVC:' && systemctl is-active kibot-master.service 2>/dev/null || echo 'inactive'; "
        "echo -n 'UDP:' && (ss -uln sport = :9991 2>/dev/null | grep -q 9991 && echo 'listening' || echo 'down')",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5.0,
        )
        output = proc.stdout.strip()
        svc_active = "SVC:active" in output
        udp_listening = "UDP:listening" in output
        is_healthy = svc_active and udp_listening
        return is_healthy, {
            "reachable": True,
            "svc_active": svc_active,
            "udp_listening": udp_listening,
            "raw": output,
        }
    except subprocess.TimeoutExpired:
        return False, {
            "reachable": False,
            "svc_active": False,
            "udp_listening": False,
            "error": "SSH probe timed out",
        }
    except Exception as exc:
        return False, {
            "reachable": False,
            "svc_active": False,
            "udp_listening": False,
            "error": str(exc),
        }


def execute_backup_mirror(
    host: str = DEFAULT_SG1_HOST,
    ssh_key: str = DEFAULT_SSH_KEY,
    user: str = "ubuntu",
    target_dir: Path = DEFAULT_BACKUP_DIR,
    timeout: float = 60.0,
) -> Tuple[bool, str]:
    """
    Pulls critical state snapshot from SG1 to local backup mirror directory.
    Synchronizes decision_journal, capital_governor, and paper_trade files.
    """
    target_state = target_dir / "state"
    target_state.mkdir(parents=True, exist_ok=True)

    cmd = [
        "rsync",
        "-avz",
        "--delete",
        "-e",
        f"ssh -i {ssh_key} -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o BatchMode=yes",
        f"{user}@{host}:/home/{user}/KiBot/state/",
        str(target_state) + "/",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return True, f"Synced to {target_state}"
        return False, f"Rsync failed (exit {proc.returncode}): {proc.stderr.strip()}"
    except Exception as exc:
        return False, f"Backup error: {exc}"


class ExternalWatchdogSentinel:
    """Stateful watchdog agent managing failure detection, alerts, and backups."""

    def __init__(
        self,
        sg1_host: str = DEFAULT_SG1_HOST,
        ssh_key: str = DEFAULT_SSH_KEY,
        state_dir: Path = DEFAULT_STATE_DIR,
        backup_dir: Path = DEFAULT_BACKUP_DIR,
        down_threshold_sec: float = DEFAULT_DOWN_THRESHOLD_S,
        backup_interval_sec: float = DEFAULT_BACKUP_INTERVAL_S,
        telegram_token: str = "",
        telegram_chat_id: str = "",
    ) -> None:
        self.sg1_host = sg1_host
        self.ssh_key = ssh_key
        self.state_dir = state_dir
        self.backup_dir = backup_dir
        self.down_threshold_sec = down_threshold_sec
        self.backup_interval_sec = backup_interval_sec
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id

        self.state_file = self.state_dir / "sentinel_state.json"
        self._load_state()

    def _load_state(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                    return
            except Exception as exc:
                logger.warning(f"Could not load state file: {exc}")
        self.state = {
            "status": "ok",
            "down_since": None,
            "alert_sent": False,
            "last_backup_ts": 0.0,
            "last_check_ts": 0.0,
        }

    def _save_state(self) -> None:
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save state: {exc}")

    def evaluate_cycle(self, now: Optional[float] = None) -> Dict[str, Any]:
        """Runs a single evaluation step. Returns action summary."""
        now = time.time() if now is None else now
        is_healthy, details = probe_sg1_status(self.sg1_host, self.ssh_key)
        self.state["last_check_ts"] = now

        result: Dict[str, Any] = {
            "is_healthy": is_healthy,
            "details": details,
            "alert_sent": False,
            "recovery_sent": False,
            "backup_performed": False,
        }

        if not is_healthy:
            if not self.state.get("down_since"):
                self.state["down_since"] = now
                self.state["status"] = "down"
                logger.warning(f"SG1 probe failed: {details}. Tracking downtime...")
            else:
                down_duration = now - float(self.state["down_since"])
                logger.info(
                    f"SG1 down for {int(down_duration)}s (threshold: {int(self.down_threshold_sec)}s)"
                )
                if down_duration >= self.down_threshold_sec and not self.state.get("alert_sent"):
                    msg = (
                        f"🚨 *[KiBot Sentinel — SG2 External Watchdog]*\n\n"
                        f"SG1 Master Node (`{self.sg1_host}`) is *UNREACHABLE / DOWN* "
                        f"for {int(down_duration // 60)}m {int(down_duration % 60)}s!\n\n"
                        f"• Probe Details: {details.get('raw') or details.get('error')}\n"
                        f"• Sentinel Host: SG2 (`213.35.118.26`)\n"
                        f"• Threshold: {int(self.down_threshold_sec)}s"
                    )
                    sent = send_telegram_alert(self.telegram_token, self.telegram_chat_id, msg)
                    self.state["alert_sent"] = True
                    result["alert_sent"] = sent
                    logger.warning(f"Sent downtime alert to Telegram: {sent}")
        else:
            if self.state.get("status") == "down" and self.state.get("alert_sent"):
                down_total = int(now - float(self.state.get("down_since") or now))
                msg = (
                    f"✅ *[KiBot Sentinel — SG2 External Watchdog]*\n\n"
                    f"SG1 Master Node (`{self.sg1_host}`) has *RECOVERED*!\n\n"
                    f"• Total Downtime: {down_total}s\n"
                    f"• MasterNode Service: ACTIVE\n"
                    f"• UDP Port 9991: LISTENING\n"
                    f"• Sentinel Host: SG2 (`213.35.118.26`)"
                )
                sent = send_telegram_alert(self.telegram_token, self.telegram_chat_id, msg)
                result["recovery_sent"] = sent
                logger.info(f"Sent recovery notification to Telegram: {sent}")

            self.state["status"] = "ok"
            self.state["down_since"] = None
            self.state["alert_sent"] = False

            # Periodic state backup mirror
            last_backup = float(self.state.get("last_backup_ts") or 0.0)
            if last_backup == 0.0 or (now - last_backup) >= self.backup_interval_sec:
                logger.info("Triggering off-server backup mirror from SG1...")
                ok, msg = execute_backup_mirror(self.sg1_host, self.ssh_key, target_dir=self.backup_dir)
                if ok:
                    self.state["last_backup_ts"] = now
                    result["backup_performed"] = True
                    logger.info(f"Backup mirror completed: {msg}")
                else:
                    logger.error(f"Backup mirror failed: {msg}")

        self._save_state()
        return result

    def run_forever(self, poll_interval_sec: float = DEFAULT_POLL_INTERVAL_S) -> None:
        """Main daemon loop."""
        logger.info(
            f"Starting SG2 Sentinel daemon targeting SG1 ({self.sg1_host}) | Poll: {poll_interval_sec}s"
        )
        while True:
            try:
                self.evaluate_cycle()
            except Exception as exc:
                logger.error(f"Unexpected error in evaluation cycle: {exc}", exc_info=True)
            time.sleep(poll_interval_sec)


def main() -> None:
    sg1_host = os.environ.get("KIBOT_SG1_HOST", DEFAULT_SG1_HOST)
    ssh_key = os.environ.get("KIBOT_SSH_KEY", DEFAULT_SSH_KEY)
    state_dir = Path(os.environ.get("KIBOT_STATE_DIR", "./state"))
    backup_dir = Path(os.environ.get("KIBOT_BACKUP_DIR", "./backups/sg1_mirror"))
    poll_interval = float(os.environ.get("WATCHDOG_POLL_INTERVAL_S", str(DEFAULT_POLL_INTERVAL_S)))
    down_threshold = float(os.environ.get("WATCHDOG_DOWN_THRESHOLD_S", str(DEFAULT_DOWN_THRESHOLD_S)))
    backup_interval = float(os.environ.get("WATCHDOG_BACKUP_INTERVAL_S", str(DEFAULT_BACKUP_INTERVAL_S)))
    token = os.environ.get("KIBOT_TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("KIBOT_TELEGRAM_CHAT_ID", "")

    sentinel = ExternalWatchdogSentinel(
        sg1_host=sg1_host,
        ssh_key=ssh_key,
        state_dir=state_dir,
        backup_dir=backup_dir,
        down_threshold_sec=down_threshold,
        backup_interval_sec=backup_interval,
        telegram_token=token,
        telegram_chat_id=chat_id,
    )
    sentinel.run_forever(poll_interval_sec=poll_interval)


if __name__ == "__main__":
    main()
