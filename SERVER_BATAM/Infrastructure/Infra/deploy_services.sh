#!/bin/bash
sudo cp SERVER_BATAM/Infrastructure/Infra/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
services=(kibot-manager kibot-analyst kibot-orchestrator kibot-security kibot-guardian ki-telegram-monitor)
for s in "${services[@]}"; do
    sudo systemctl restart "$s"
    echo "Restarted $s"
done
