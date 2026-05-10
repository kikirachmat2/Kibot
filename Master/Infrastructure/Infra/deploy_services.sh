#!/bin/bash
set -euo pipefail

if [ -f "SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh" ]; then
    sudo bash SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh
else
    sudo cp SERVER_BATAM/Infrastructure/Infra/systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload
    services=(
        kibot-trinity
        kibot-manager
        kibot-healer
        kibot-notifier
        kibot-orchestrator
        kibot-security
        kibot-guardian
        kibot-analyst
        kibot-command-center
        ki-telegram-monitor
        kibot-ollama-gateway
        kibot-polymarket
        lazarus-ampere
    )
    for s in "${services[@]}"; do
        sudo systemctl restart "$s" || true
        echo "Restarted $s"
    done
fi
