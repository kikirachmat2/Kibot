#!/usr/bin/env bash
# Batam Bootstrap Script
set -euo pipefail

echo "[BOOTSTRAP] Starting Batam Bootstrap sequence..."

# Kill stale UDP 9999
echo "[BOOTSTRAP] Cleaning up port 9999/udp..."
sudo fuser -k 9999/udp || true

if [ -f "SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh" ]; then
    echo "[BOOTSTRAP] Delegating to autonomous baseline installer..."
    sudo bash SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh
else
    # Fallback for minimal environments: sync core systemd units only.
    echo "[BOOTSTRAP] Syncing systemd units..."
    if [ -d "SERVER_BATAM/Infrastructure/Infra/systemd" ]; then
        sudo cp SERVER_BATAM/Infrastructure/Infra/systemd/*.service /etc/systemd/system/
    fi
    echo "[BOOTSTRAP] Restarting Kibot baseline..."
    sudo systemctl daemon-reload
    sudo systemctl disable kibot-manager.service || true
    sudo systemctl enable kibot-trinity.service kibot-healer.service kibot-notifier.service kibot-orchestrator.service kibot-guardian.service kibot-analyst.service kibot-command-center.service lazarus-ampere.service || true
    sudo systemctl restart kibot-trinity.service kibot-healer.service kibot-notifier.service kibot-orchestrator.service kibot-guardian.service kibot-analyst.service kibot-command-center.service lazarus-ampere.service || true
fi

echo "[BOOTSTRAP] Checking service status..."
sudo systemctl status kibot-trinity.service --no-pager

echo "[BOOTSTRAP] Tail logs..."
journalctl -u kibot-trinity.service -n 50 --no-pager

echo "[BOOTSTRAP] Done."
