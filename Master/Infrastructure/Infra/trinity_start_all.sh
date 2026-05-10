#!/bin/bash
# ==============================================================================
# KiBot Trinity: MASTER STARTUP SCRIPT
# Philosophy: "Sedikit Demi Sedikit, Lama-Lama Jadi Bukit"
# ==============================================================================

echo "🛡️ Initiating KiBot Trinity Sovereign Mesh..."

# 1. Start Batam (Command Plane & AI)
echo "[1/4] Starting Batam Strategic Command..."
sudo systemctl restart kibot-manager
sudo systemctl restart ki-telegram-monitor
sudo systemctl restart kibot-guardian

# 2. Start Scanner (Tokyo)
echo "[2/4] Orchestrating Scanner Node (Tokyo)..."
ssh -i /home/ubuntu/KiBot/SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem -o StrictHostKeyChecking=no ubuntu@100.105.139.21 "sudo systemctl restart kibot-scanner-mesh"

# 3. Start Executor (Singapore)
echo "[3/4] Powering up Executor Engine (Singapore)..."
ssh -i /home/ubuntu/KiBot/SERVER_BATAM/Infrastructure/SSH/ssh-key-executor.pem -o StrictHostKeyChecking=no ubuntu@100.122.1.109 "sudo systemctl restart kibot-commander && sudo systemctl restart kibot-executor-engine"

# 4. Verification
echo "[4/4] Verifying Mesh Status..."
sleep 5
python3 /home/ubuntu/KiBot/SERVER_BATAM/Interface/trinity_status.py

echo "🚀 TRINITY MESH IS LIVE. Sovereignty Through Autonomy."
