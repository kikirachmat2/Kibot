#!/usr/bin/env python3
"""
KiBot V2 Witness Sentinel — SG2 Independent Dead-Man Monitor.
Monitors KiBot V2 on SG1 (Tailscale: 100.105.139.21:8789) every 60 seconds.
Dispatches critical Telegram alert if SG1 is unresponsive for >3 minutes (>=3 consecutive failures).
Operates with near-zero resource consumption using standard library only.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

log_file = Path(__file__).parent / "v2_witness.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [V2Witness] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("V2Witness")

# Load .env manually if present
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                if k not in os.environ:
                    os.environ[k] = v

SG1_HEALTH_URL = os.getenv("KIBOT_V2_HEALTH_URL", "http://100.105.139.21:8789/health")
POLL_INTERVAL_S = int(os.getenv("V2_WATCHDOG_POLL_INTERVAL_S", "60"))
DOWN_THRESHOLD_S = int(os.getenv("V2_WATCHDOG_DOWN_THRESHOLD_S", "180"))
REPEAT_ALERT_INTERVAL_S = 900  # 15 mins

TELEGRAM_TOKEN = os.getenv("KIBOT_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("KIBOT_TELEGRAM_CHAT_ID", "")


def send_telegram(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured. Skipping notification.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False


def check_sg1_health() -> tuple[bool, str, dict]:
    try:
        req = urllib.request.Request(SG1_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                if data.get("status") == "HEALTHY":
                    return True, "OK", data
                else:
                    return False, f"Unhealthy status: {data.get('status')}", data
            return False, f"HTTP status code {resp.status}", {}
    except Exception as e:
        return False, str(e), {}


def main() -> None:
    logger.info("Starting KiBot V2 Witness Sentinel on SG2.")
    logger.info(f"Target URL: {SG1_HEALTH_URL} | Poll: {POLL_INTERVAL_S}s | Threshold: {DOWN_THRESHOLD_S}s")

    consecutive_failures = 0
    first_failure_time: float | None = None
    last_alert_time: float | None = None
    is_down_alerted = False

    while True:
        loop_start = time.time()
        healthy, reason, data = check_sg1_health()

        if healthy:
            if is_down_alerted:
                # Recovery notification
                uptime = data.get("uptime_s", 0)
                equity = data.get("total_equity_idr", 0)
                pos = data.get("open_positions", 0)
                logger.info(f"SG1 recovered! Uptime: {uptime:.1f}s, Equity: {equity:,.0f} IDR")
                msg = (
                    "<b>[SG2 WITNESS] KiBot V2 RECOVERED</b>\n\n"
                    "SG1 primary service is back online and HEALTHY.\n"
                    f"• Uptime: {uptime:.1f}s\n"
                    f"• Equity: Rp {equity:,.0f}\n"
                    f"• Open Positions: {pos}\n"
                    f"• Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )
                send_telegram(msg)
                is_down_alerted = False
                last_alert_time = None

            consecutive_failures = 0
            first_failure_time = None
            logger.info(f"SG1 Health: OK (Uptime: {data.get('uptime_s', 0):.1f}s, Positions: {data.get('open_positions', 0)})")
        else:
            consecutive_failures += 1
            if first_failure_time is None:
                first_failure_time = time.time()

            downtime_s = time.time() - first_failure_time
            logger.warning(f"SG1 Health check FAILED ({consecutive_failures}x, {downtime_s:.1f}s): {reason}")

            if downtime_s >= DOWN_THRESHOLD_S:
                now = time.time()
                should_alert = not is_down_alerted or (last_alert_time and (now - last_alert_time) >= REPEAT_ALERT_INTERVAL_S)
                if should_alert:
                    logger.critical(f"SG1 DEAD-MAN THRESHOLD BREACHED ({downtime_s:.1f}s). Dispatching alert...")
                    msg = (
                        "<b>[SG2 WITNESS] CRITICAL ALERT</b>\n\n"
                        "<b>KiBot V2 on SG1 is UNRESPONSIVE!</b>\n"
                        f"• Failed consecutive checks: {consecutive_failures}\n"
                        f"• Down duration: >{int(downtime_s)}s\n"
                        f"• Target: {SG1_HEALTH_URL}\n"
                        f"• Last Error: <code>{reason}</code>\n"
                        f"• Witness: SG2 (213.35.118.26)\n"
                        f"• Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                        "<i>SG1 primary service may have crashed or node lost connectivity. Immediate operator inspection required.</i>"
                    )
                    send_telegram(msg)
                    is_down_alerted = True
                    last_alert_time = now

        elapsed = time.time() - loop_start
        sleep_dur = max(1.0, POLL_INTERVAL_S - elapsed)
        time.sleep(sleep_dur)


if __name__ == "__main__":
    main()
