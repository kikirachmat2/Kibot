#!/usr/bin/env bash

set -euo pipefail

RUNTIME_ROOT="${KIBOT_RUNTIME_ROOT:-/home/ubuntu/KiBot}"
SERVICE_SRC="${RUNTIME_ROOT}/SERVER_BATAM/Infrastructure"
EXECUTOR_SERVICE="/etc/systemd/system/executor-healer.service"
EXECUTOR_TIMER="/etc/systemd/system/executor-healer.timer"
EXECUTOR_SCRIPT="/usr/local/bin/executor_memory_watchdog.py"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if [[ ! -f "${SERVICE_SRC}/executor-healer.service" || ! -f "${SERVICE_SRC}/executor-healer.timer" || ! -f "${SERVICE_SRC}/executor_memory_watchdog.py" ]]; then
  echo "Executor watchdog assets are missing from ${SERVICE_SRC}." >&2
  exit 1
fi

install -m 0644 "${SERVICE_SRC}/executor-healer.service" "${EXECUTOR_SERVICE}"
install -m 0644 "${SERVICE_SRC}/executor-healer.timer" "${EXECUTOR_TIMER}"
install -m 0755 "${SERVICE_SRC}/executor_memory_watchdog.py" "${EXECUTOR_SCRIPT}"

systemctl daemon-reload
systemctl enable --now executor-healer.timer

echo "Executor autonomous baseline installed."
