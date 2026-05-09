#!/bin/bash

# KiBot Trinity Mesh Deployment Script (V3 - Full Env Sync)
# 🚀 "Total Parity, Total Sovereignty"

# --- CONFIGURATION ---
USER="ubuntu"
BATAM_IP="168.110.201.228"
SCANNER_IP="152.69.218.198"
EXECUTOR_IP="213.35.118.26"

REMOTE_ROOT="/home/ubuntu/KiBot"

# SSH Keys
KEY_BATAM="SERVER_BATAM/Infrastructure/SSH/ssh-key-batam-active.pem"
KEY_SCANNER="SERVER_BATAM/Infrastructure/SSH/ssh-key-scanner.pem"
KEY_EXECUTOR="SERVER_BATAM/Infrastructure/SSH/ssh-key-executor.pem"

# --- PERMISSION HARDENING ---
chmod 600 "$KEY_BATAM" "$KEY_SCANNER" "$KEY_EXECUTOR"

# --- DEPLOYMENT FUNCTIONS ---

deploy_node() {
    local node_name=$1
    local ip=$2
    local key=$3
    local folder=$4
    
    echo "📦 Deploying $node_name..."
    rsync -avz --exclude '.git' --exclude '__pycache__' --exclude 'venv' \
        -e "ssh -i $key -o StrictHostKeyChecking=no" \
        "$folder/" "$USER@$ip:$REMOTE_ROOT/$folder/"
}

sync_env() {
    local ip=$1
    local key=$2
    echo "🔐 Syncing Environment and Vault to $ip..."
    # Ensure structure exists
    ssh -i "$key" -o StrictHostKeyChecking=no "$USER@$ip" "mkdir -p $REMOTE_ROOT/SERVER_BATAM/state"
    
    # Sync standard .env
    rsync -avz -e "ssh -i $key -o StrictHostKeyChecking=no" \
        "SERVER_BATAM/.env" "$USER@$ip:$REMOTE_ROOT/.env"
    
    # Sync vaulted .env.kiv
    rsync -avz -e "ssh -i $key -o StrictHostKeyChecking=no" \
        "SERVER_BATAM/.env.kiv" "$USER@$ip:$REMOTE_ROOT/.env.kiv"
        
    # Sync salt
    rsync -avz -e "ssh -i $key -o StrictHostKeyChecking=no" \
        "SERVER_BATAM/state/.vault_salt" "$USER@$ip:$REMOTE_ROOT/SERVER_BATAM/state/"
}

# --- EXECUTION ---

echo "--- STARTING TRINITY DEPLOYMENT ---"

deploy_node "BATAM" "$BATAM_IP" "$KEY_BATAM" "SERVER_BATAM"
deploy_node "SCANNER" "$SCANNER_IP" "$KEY_SCANNER" "SERVER_SCANNER"
deploy_node "EXECUTOR" "$EXECUTOR_IP" "$KEY_EXECUTOR" "SERVER_EXECUTOR"

sync_env "$SCANNER_IP" "$KEY_SCANNER"
sync_env "$EXECUTOR_IP" "$KEY_EXECUTOR"

echo "✅ Environment parity established."

# --- POST-DEPLOYMENT: REFRESH ---
echo "🛠️  Hard-restarting Executor services..."
ssh -i "$KEY_EXECUTOR" -o StrictHostKeyChecking=no "$USER@$EXECUTOR_IP" << EOF
    sudo killall -9 python3 || true
    sudo systemctl daemon-reload
    sudo systemctl restart kibot-indodax kibot-polymarket kibot-node-agent
EOF

echo "🏰 Refreshing Batam Master..."
ssh -i "$KEY_BATAM" -o StrictHostKeyChecking=no "$USER@$BATAM_IP" << EOF
    # Update high command service if changed
    sudo cp $REMOTE_ROOT/SERVER_BATAM/Infrastructure/Infra/systemd/kibot-high-command.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl restart kibot-high-command
EOF

echo "🚀 TRINITY IS FULLY OPERATIONAL!"
