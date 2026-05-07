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
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Core_Logic/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Core_Logic/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/AI_Orchestration/ \
    $USER@$HOST:$DEST/SERVER_BATAM/AI_Orchestration/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Indicators_Math/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Indicators_Math/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Infrastructure/Automation/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Infrastructure/Automation/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Infrastructure/Infra/systemd/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Infrastructure/Infra/systemd/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Security/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Security/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Support/Web/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Support/Web/

rsync -avz -e "ssh -i $KEY -o StrictHostKeyChecking=no" \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'state/' \
    --exclude 'logs/' \
    --exclude 'scratch/' \
    SERVER_BATAM/Support/ \
    $USER@$HOST:$DEST/SERVER_BATAM/Support/

echo "Reinstalling Batam baseline on remote..."
ssh -i $KEY -o StrictHostKeyChecking=no $USER@$HOST "cd $DEST && sudo bash SERVER_BATAM/Infrastructure/Infra/setup_batam_autonomous.sh"

echo "Deployment complete."
