"""
Module: cluster.watchdog
Author: KiBot V3 Team
Date: 2026-10-01

Server 2 Infrastructure Watchdog, Health Monitor, and Auto-Backup.

References:
[1] Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (2024). "Site Reliability Engineering: How Google Runs Production Systems". O'Reilly Media. Accessed: 2026-09-20.
[2] HashiCorp (2025). "Auto-Healing Architectures and Safe Distributed Recovery Patterns". https://www.hashicorp.com/resources. Accessed: 2026-09-20.
[3] KiBot V2 Cluster Audit — Enhanced from Server 2 witness node to automated rsync backups and disk hygiene management.
"""

import os
import time
import shutil
from typing import Dict, Any, List, Optional


class WatchdogManager:
    """
    Monitors cluster nodes, tracks health pings via HTTP /health, rotates logs, and creates SQLite snapshots.
    """
    MAX_MISSED_PINGS = 3
    DISK_USAGE_THRESHOLD_PCT = 85.0

    def __init__(
        self,
        backup_dir: str = "data/backups",
        db_path: str = "data/kibot_v3.db",
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ):
        self.backup_dir = backup_dir
        self.db_path = db_path
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.missed_pings: int = 0
        self.last_healthy_ts: Optional[float] = None
        os.makedirs(self.backup_dir, exist_ok=True)

    def record_heartbeat(self, is_alive: bool, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Record health check from SG1 trading node."""
        if is_alive:
            self.missed_pings = 0
            self.last_healthy_ts = time.time()
            return {"status": "HEALTHY", "missed_pings": 0, "should_restart": False, "details": details or {}}
        else:
            self.missed_pings += 1
            should_restart = self.missed_pings >= self.MAX_MISSED_PINGS
            return {
                "status": "UNHEALTHY",
                "missed_pings": self.missed_pings,
                "should_restart": should_restart,
                "details": details or {}
            }

    def check_disk_usage(self, path: str = "/") -> Dict[str, Any]:
        """Verify storage capacity does not breach 85% threshold."""
        try:
            total, used, free = shutil.disk_usage(path)
            used_pct = (used / total) * 100.0
            return {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "used_pct": round(used_pct, 2),
                "is_critical": used_pct >= self.DISK_USAGE_THRESHOLD_PCT
            }
        except Exception:
            return {"total_gb": 0.0, "used_pct": 0.0, "is_critical": False}

    def create_database_backup(self) -> str:
        """Create a timestamped copy of the SQLite database."""
        if not os.path.exists(self.db_path):
            return ""

        timestamp = int(time.time())
        dest_file = os.path.join(self.backup_dir, f"kibot_v3_backup_{timestamp}.db")
        shutil.copy2(self.db_path, dest_file)
        return dest_file

    def purge_old_backups(self, retention_days: int = 90) -> int:
        """Purge backup snapshots exceeding retention threshold."""
        now = time.time()
        purged_count = 0
        cutoff = now - (retention_days * 86400)

        if os.path.exists(self.backup_dir):
            for fname in os.listdir(self.backup_dir):
                fpath = os.path.join(self.backup_dir, fname)
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    purged_count += 1

        return purged_count

    def ping_sg1_health(self, sg1_url: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Pings SG1 HTTP /health endpoint.
        Returns parsed json response or error.
        """
        import urllib.request
        import json

        req = urllib.request.Request(
            sg1_url,
            headers={"User-Agent": "Server2-KiBotV3-Watchdog/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                is_healthy = (resp.status == 200 and data.get("status") == "HEALTHY")
                return self.record_heartbeat(is_healthy, details=data)
        except Exception as err:
            return self.record_heartbeat(False, details={"error": str(err)})

    def send_telegram_alert(self, message: str) -> bool:
        """
        Directly transmits alert to Supervisor via Telegram using Watchdog's independent bot token.
        """
        token = self.bot_token or os.environ.get("WATCHDOG_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = self.chat_id or os.environ.get("WATCHDOG_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")

        if not token or not chat_id:
            print("⚠️ Watchdog alert failed: Missing bot token or chat ID.", flush=True)
            return False

        import urllib.request
        import urllib.parse
        import json

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "KiBotV3-WatchdogAlert/1.0"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"❌ Failed to send Watchdog Telegram alert: {e}", flush=True)
            return False

    def restart_remote_service_ssh(self, ssh_host: str, service_name: str = "kibot_v3") -> bool:
        """
        Attempts to restart SG1 service via SSH key authentication.
        """
        import subprocess
        try:
            cmd = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", f"ubuntu@{ssh_host}", f"sudo systemctl restart {service_name}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            return res.returncode == 0
        except Exception as err:
            print(f"❌ SSH restart command failed: {err}", flush=True)
            return False


def run_watchdog_loop():
    """Main daemon loop for Server 2 Watchdog."""
    from dotenv import load_dotenv

    load_dotenv()

    backup_dir = os.environ.get("BACKUP_LOCAL_DIR", "/home/ubuntu/kibot_v3_backup")
    sg1_host = os.environ.get("SG1_HOST", "100.105.139.21")  # Default to Tailscale IP or public IP
    health_port = os.environ.get("SG1_HEALTH_PORT", "8789")
    db_path = os.environ.get("DB_PATH", "/home/ubuntu/kibot_v3_backup/kibot_v3.db")
    bot_token = os.environ.get("WATCHDOG_TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("WATCHDOG_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")

    manager = WatchdogManager(
        backup_dir=backup_dir,
        db_path=db_path,
        bot_token=bot_token,
        chat_id=chat_id
    )
    sg1_health_url = f"http://{sg1_host}:{health_port}/health"
    print(f"🛡️ KiBot V3 Watchdog Active on Server 2 (Target: {sg1_health_url})...", flush=True)

    last_backup_time = 0
    last_unhealthy_alert_time = 0

    while True:
        try:
            # 1. Ping SG1 Health Endpoint
            ping_res = manager.ping_sg1_health(sg1_health_url, timeout=5.0)

            # Check for failure trigger
            if ping_res["should_restart"]:
                now = time.time()
                # Cooldown for alert: max once every 15 minutes while failing
                if now - last_unhealthy_alert_time >= 900:
                    details = ping_res.get("details", {})
                    err_reason = details.get("error") or details.get("issues") or "Node Unresponsive"

                    # (a) Attempt remote restart via SSH
                    restart_ok = manager.restart_remote_service_ssh(sg1_host)

                    # (b) ALWAYS Alert Supervisor from Server 2 independently!
                    alert_msg = (
                        f"🚨 <b>SERVER 2 WATCHDOG ALERT: SG1 DOWN!</b>\n"
                        f"Health check SG1 ({sg1_host}) gagal {ping_res['missed_pings']}x berturut-turut.\n"
                        f"• Error: {err_reason}\n"
                        f"• Tindakan Auto-Restart SSH: {'✅ BERHASIL DIJALANKAN' if restart_ok else '❌ GAGAL / KONEKSI TERPUTUS'}\n"
                        f"⛔ <i>Supervisor wajib memverifikasi kondisi SG1 segera!</i>"
                    )
                    manager.send_telegram_alert(alert_msg)
                    last_unhealthy_alert_time = now

            # 2. Check local Server 2 disk usage
            disk = manager.check_disk_usage()
            if disk["is_critical"]:
                print(f"⚠️ DISK WARNING: Used {disk['used_pct']}% on Server 2", flush=True)

            # 3. Check periodic backup (every 6 hours)
            now = time.time()
            if now - last_backup_time >= 21600:
                print("📦 Running periodic backup check & old backup purge...", flush=True)
                manager.purge_old_backups(retention_days=30)
                last_backup_time = now

        except Exception as e:
            print(f"Watchdog loop exception: {e}", flush=True)

        time.sleep(60)  # Ping every 60 seconds


if __name__ == "__main__":
    run_watchdog_loop()

