#!/bin/bash
set -e

echo "Deploying updates to Batam Server (168.110.201.228)..."

KEY="SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem"
USER="ubuntu"
HOST="168.110.201.228"
DEST="/home/ubuntu/KiBot"

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    SERVER_BATAM/Core_Logic/kibot_manager.py \
    $USER@$HOST:$DEST/SERVER_BATAM/Core_Logic/kibot_manager.py

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    SERVER_BATAM/AI_Orchestration/kibot_ai_scout.py \
    $USER@$HOST:$DEST/SERVER_BATAM/AI_Orchestration/kibot_ai_scout.py

echo "Restarting kibot-manager.service..."
ssh -i $KEY $USER@$HOST "sudo systemctl restart kibot-manager.service"

echo "Checking kibot-manager.service status..."
ssh -i $KEY $USER@$HOST "systemctl status kibot-manager.service --no-pager"

echo "Deployment complete."
