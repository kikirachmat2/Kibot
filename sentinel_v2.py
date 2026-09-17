#!/usr/bin/env python3
"""
sentinel_v2.py — KiBot V2 Dead-Man's Witness
Runs on SG2 (213.35.118.26). Polls SG1 health endpoint every 60s.
Fires CRITICAL Telegram alert if SG1 is silent for >= 3 consecutive checks.

Config via env vars (read from /home/ubuntu/KiBot/.env on SG2 if present):
  TELEGRAM_BOT_TOKEN   — bot token
  TELEGRAM_CHAT_ID     — target chat id
  SG1_HEALTH_URL       — default: http://100.105.139.21:8789/health (Tailscale)
  SENTINEL_POLL_SEC    — poll interval in seconds (default: 60)
  SENTINEL_MAX_FAILS   — consecutive failures before alert (default: 3)
"""

import os
import sys
import time
import signal
import logging
import urllib.request
import urllib.error
import json
from pathlib import Path

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SENTINEL] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/home/ubuntu/sentinel_v2.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("sentinel_v2")


# ──────────────────────────────────────────────
# Load .env file (best-effort, no third-party deps)
# ──────────────────────────────────────────────
def _load_dotenv(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


# Try loading from SG1 .env copied/shared to SG2 (if operator set it up)
_load_dotenv("/home/ubuntu/KiBot/.env")
_load_dotenv("/home/ubuntu/.env")


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
HEALTH_URL: str = os.environ.get(
    "SG1_HEALTH_URL", "http://100.105.139.21:8789/health"
)
POLL_SEC: int = int(os.environ.get("SENTINEL_POLL_SEC", "60"))
MAX_FAILS: int = int(os.environ.get("SENTINEL_MAX_FAILS", "3"))
REQUEST_TIMEOUT: int = 5  # seconds


def _validate_config() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        log.warning(
            "Telegram credentials not set (%s). "
            "Sentinel will still poll but CANNOT send alerts. "
            "Set env vars and restart.",
            ", ".join(missing),
        )
    else:
        log.info("Telegram credentials OK. Alert target: chat_id=%s", CHAT_ID)
    log.info("Polling %s every %ds, alert after %d consecutive failures.",
             HEALTH_URL, POLL_SEC, MAX_FAILS)


# ──────────────────────────────────────────────
# Telegram send (stdlib only, no requests dep)
# ──────────────────────────────────────────────
def _send_telegram(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        log.error("Cannot send Telegram alert — credentials missing.")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            if ok:
                log.info("Telegram alert sent.")
            else:
                log.warning("Telegram returned HTTP %d", resp.status)
            return ok
    except Exception as exc:  # noqa: BLE001
        log.error("Telegram send failed: %s", exc)
        return False


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────
def _check_health() -> tuple[bool, str]:
    """Return (is_healthy, detail_str)."""
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            if resp.status == 200:
                raw = resp.read().decode(errors="replace")
                try:
                    data = json.loads(raw)
                    detail = (
                        f"status={data.get('status')} "
                        f"mode={data.get('mode')} "
                        f"uptime={data.get('uptime_s', '?')}s "
                        f"equity={data.get('total_equity_idr', '?')} "
                        f"halted={data.get('is_halted', '?')}"
                    )
                except json.JSONDecodeError:
                    detail = raw[:120]
                return True, detail
            return False, f"HTTP {resp.status}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ──────────────────────────────────────────────
# Main loop
# ──────────────────────────────────────────────
_shutdown = False


def _handle_signal(sig, _frame):
    global _shutdown
    log.info("Received signal %d, shutting down.", sig)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def main() -> None:
    log.info("=== KiBot V2 Sentinel starting (SG2 → SG1) ===")
    _validate_config()

    consecutive_failures = 0
    alert_sent = False  # Don't spam: send once per outage episode

    while not _shutdown:
        healthy, detail = _check_health()

        if healthy:
            if consecutive_failures > 0:
                log.info("SG1 recovered after %d failure(s). Detail: %s",
                         consecutive_failures, detail)
                if alert_sent:
                    _send_telegram(
                        "✅ <b>KiBot V2 SG1 — RECOVERED</b>\n"
                        f"Endpoint back online after {consecutive_failures} "
                        f"missed checks (~{consecutive_failures * POLL_SEC}s down).\n"
                        f"<code>{detail}</code>"
                    )
                alert_sent = False
            else:
                log.info("SG1 OK. %s", detail)
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            log.warning(
                "SG1 health check FAILED (%d/%d). Reason: %s",
                consecutive_failures, MAX_FAILS, detail,
            )

            if consecutive_failures >= MAX_FAILS and not alert_sent:
                down_sec = consecutive_failures * POLL_SEC
                msg = (
                    "🚨 <b>CRITICAL — KiBot V2 SG1 DOWN</b>\n"
                    f"Endpoint unreachable for ~{down_sec}s "
                    f"({consecutive_failures} consecutive failures).\n"
                    f"URL: <code>{HEALTH_URL}</code>\n"
                    f"Last error: <code>{detail[:200]}</code>\n\n"
                    "Manual intervention required. "
                    "Check SG1 systemd service: "
                    "<code>systemctl status kibot-v2-paper.service</code>"
                )
                log.critical("ALERT: %s", msg.replace("\n", " "))
                _send_telegram(msg)
                alert_sent = True

        # Sleep in small increments so SIGTERM is responsive
        for _ in range(POLL_SEC):
            if _shutdown:
                break
            time.sleep(1)

    log.info("=== Sentinel exiting cleanly. ===")


if __name__ == "__main__":
    main()
