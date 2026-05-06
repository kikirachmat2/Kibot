#!/usr/bin/env bash
# KiBot Batam - System Management Setup
# This script installs crontab entries for resource monitoring and cleanup.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_SCRIPT="${SCRIPT_DIR}/monitor_resources.py"
CLEANUP_SCRIPT="${SCRIPT_DIR}/cleanup_ollama.py"

echo "[INFO] Setting up KiBot System Management..."

# Ensure scripts are executable
chmod +x "$MONITOR_SCRIPT"
chmod +x "$CLEANUP_SCRIPT"

# Define Cron jobs
# Monitor resources every 5 minutes
CRON_MONITOR="*/5 * * * * /usr/bin/python3 ${MONITOR_SCRIPT} >> /home/ubuntu/logs/monitor_resources.log 2>&1"
# Cleanup Ollama every hour
CRON_CLEANUP="0 * * * * /usr/bin/python3 ${CLEANUP_SCRIPT} >> /home/ubuntu/logs/cleanup_ollama.log 2>&1"

# Add to crontab
(
echo "# KiBot Batam System Management"
crontab -l 2>/dev/null | { grep -v "${MONITOR_SCRIPT}" | grep -v "${CLEANUP_SCRIPT}" | grep -v "# KiBot Batam System Management" || true; }
echo "${CRON_MONITOR}"
echo "${CRON_CLEANUP}"
) | crontab -

echo "[INFO] Current Crontab:"
crontab -l
