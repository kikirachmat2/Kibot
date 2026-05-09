#!/bin/bash
set -e

echo "Deploying updates to Batam Server (168.110.201.228)..."

KEY="SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem"
USER="ubuntu"
HOST="168.110.201.228"
DEST="/home/ubuntu/KiBot"

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'Data/State/' \
    --exclude 'Logs/' \
    --exclude 'scratch/' \
    --exclude '__pycache__/' \
    SERVER_BATAM/ \
    $USER@$HOST:$DEST/SERVER_BATAM/

echo "Reinstalling Batam baseline on remote..."
ssh -i $KEY -o StrictHostKeyChecking=no $USER@$HOST "cd $DEST && sudo bash SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh"

echo "Deployment complete."
