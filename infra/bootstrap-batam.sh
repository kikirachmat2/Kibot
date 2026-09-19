#!/usr/bin/env bash
# KiBot V2 — Sovereign Batam Research Node Cloud-Init Bootstrap
# Automatically executed on first boot of newly provisioned A1.Flex ARM instance.
set -Eeuo pipefail

LOG_FILE="/var/log/kibot_bootstrap.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "============================================================"
echo "🚀 KIBOT V2 — BATAM RESEARCH NODE AUTO-BOOTSTRAP STARTING"
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"

# 1. Update system packages
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get upgrade -y
apt-get install -y python3-pip python3-venv git curl ufw jq

# 2. Setup Tailscale Zero-Trust Mesh Network (MANDATORY)
if [ -z "${TS_AUTHKEY:-}" ]; then
    echo "[Bootstrap] ❌ CRITICAL: TS_AUTHKEY is missing! Tailscale cannot join mesh. Aborting bootstrap."
    if [ -n "${KIBOT_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${KIBOT_TELEGRAM_CHAT_ID:-}" ]; then
        curl -s -X POST "https://api.telegram.org/bot${KIBOT_TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${KIBOT_TELEGRAM_CHAT_ID}&text=❌+<b>KIBOT+BATAM+BOOTSTRAP+FAILED</b>%0ATS_AUTHKEY+missing.+Aborted+Tailscale+mesh+join.&parse_mode=HTML" >/dev/null || true
    fi
    exit 1
fi

echo "[Bootstrap] Installing and joining Tailscale network..."
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey="${TS_AUTHKEY}" --hostname="kibot-batam" --accept-routes
echo "[Bootstrap] ✅ Tailscale joined successfully. IP: $(tailscale ip -4 2>/dev/null || echo 'pending')"

# 3. Clone KiBot Codebase
TARGET_DIR="/home/ubuntu/KiBotV2"
if [ ! -d "${TARGET_DIR}" ]; then
    echo "[Bootstrap] Cloning KiBot repository to ${TARGET_DIR}..."
    git clone https://github.com/kikirachmat2/Kibot.git "${TARGET_DIR}"
    chown -R ubuntu:ubuntu "${TARGET_DIR}"
fi

# 4. Setup Python Virtual Environment
echo "[Bootstrap] Setting up Python virtual environment..."
su - ubuntu -c "python3 -m venv ${TARGET_DIR}/venv"
su - ubuntu -c "${TARGET_DIR}/venv/bin/pip install --upgrade pip"
if [ -f "${TARGET_DIR}/requirements.txt" ]; then
    su - ubuntu -c "${TARGET_DIR}/venv/bin/pip install -r ${TARGET_DIR}/requirements.txt"
fi
su - ubuntu -c "${TARGET_DIR}/venv/bin/pip install fastapi uvicorn httpx aiohttp"

# 5. Configure Batam Cluster Service (Port 5001)
SERVICE_FILE="/etc/systemd/system/kibot-batam-cluster.service"
cat << 'EOF' > "${SERVICE_FILE}"
[Unit]
Description=KiBot V2 Batam Research Cluster Service
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/KiBotV2/KiBot V2
Environment="PYTHONPATH=/home/ubuntu/KiBotV2/KiBot V2"
ExecStart=/home/ubuntu/KiBotV2/venv/bin/python3 -m uvicorn cluster.server_batam:app --host 0.0.0.0 --port 5001
Restart=always
RestartSec=5
MemoryMax=2G

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now kibot-batam-cluster.service

# 6. Notify Telegram on Completion
if [ -n "${KIBOT_TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${KIBOT_TELEGRAM_CHAT_ID:-}" ]; then
    PUBLIC_IP=$(curl -s -m 5 https://api.ipify.org || echo "N/A")
    TS_IP=$(tailscale ip -4 2>/dev/null || echo "N/A")
    MSG="🎉 <b>KIBOT V2 — BATAM RESEARCH NODE ONLINE!</b>%0A• Public IP: <code>${PUBLIC_IP}</code>%0A• Tailscale IP: <code>${TS_IP}</code>%0A• Cluster Port: <code>5001</code>%0A• Status: Bootstrap Complete"
    curl -s -X POST "https://api.telegram.org/bot${KIBOT_TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${KIBOT_TELEGRAM_CHAT_ID}&text=${MSG}&parse_mode=HTML" >/dev/null || true
fi

echo "============================================================"
echo "✅ KIBOT V2 — BATAM BOOTSTRAP COMPLETE"
echo "============================================================"
