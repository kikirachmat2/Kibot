#!/usr/bin/env bash

set -euo pipefail

RUNTIME_ROOT="${KIBOT_RUNTIME_ROOT:-/home/ubuntu/KiBot}"
SERVICE_ROOT="${RUNTIME_ROOT}/SERVER_BATAM/Infrastructure/Infra/systemd"
APP_ROOT="${RUNTIME_ROOT}/SERVER_BATAM"
LOGROTATE_CONF="/etc/logrotate.d/kibot-batam"
WATCHDOG_SCRIPT="/usr/local/bin/kibot-batam-watchdog.sh"
WATCHDOG_SERVICE="/etc/systemd/system/kibot-batam-watchdog.service"
WATCHDOG_TIMER="/etc/systemd/system/kibot-batam-watchdog.timer"
HEALTH_SCRIPT="/usr/local/bin/kibot-batam-health-report.sh"
HEALTH_SERVICE="/etc/systemd/system/kibot-batam-health-report.service"
HEALTH_TIMER="/etc/systemd/system/kibot-batam-health-report.timer"
HEALER_SERVICE="/etc/systemd/system/kibot-healer.service"
NOTIFIER_SERVICE="/etc/systemd/system/kibot-notifier.service"
ORCHESTRATOR_SERVICE="/etc/systemd/system/kibot-orchestrator.service"
SECURITY_SERVICE="/etc/systemd/system/kibot-security.service"
GUARDIAN_SERVICE="/etc/systemd/system/kibot-guardian.service"
ANALYST_SERVICE="/etc/systemd/system/kibot-analyst.service"
MANAGER_SERVICE="/etc/systemd/system/kibot-manager.service"
TRINITY_SERVICE="/etc/systemd/system/kibot-trinity.service"
OLLAMA_GATEWAY_SERVICE="/etc/systemd/system/kibot-ollama-gateway.service"
POLYMARKET_SERVICE="/etc/systemd/system/kibot-polymarket.service"
CRASHLOOP_GUARD_SCRIPT="/usr/local/bin/kibot-crashloop-guard.sh"
CRASHLOOP_GUARD_SERVICE="/etc/systemd/system/kibot-crashloop-guard.service"
CRASHLOOP_GUARD_TIMER="/etc/systemd/system/kibot-crashloop-guard.timer"
SANITY_SERVICE="/etc/systemd/system/kibot-config-sanity.service"
SANITY_TIMER="/etc/systemd/system/kibot-config-sanity.timer"
COMMAND_CENTER_SERVICE="/etc/systemd/system/kibot-command-center.service"
LAZARUS_SERVICE="/etc/systemd/system/lazarus-ampere.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

install -d -o ubuntu -g ubuntu /home/ubuntu/logs
install -d -o ubuntu -g ubuntu /home/ubuntu/ampere-hunt/state

cat > "${LOGROTATE_CONF}" <<'EOF'
/home/ubuntu/logs/*.log /home/ubuntu/logs/*.out /home/ubuntu/ampere-hunt/*.log /home/ubuntu/ampere-hunt/state/*.log {
    daily
    size 20M
    rotate 5
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ubuntu ubuntu
    dateext
    dateformat -%Y%m%d
    sharedscripts
}
EOF
chmod 644 "${LOGROTATE_CONF}"

cat > "${WATCHDOG_SCRIPT}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

check_unit() {
  local unit="$1"
  if ! systemctl is-active --quiet "${unit}"; then
    systemctl restart "${unit}"
  fi
}

check_unit unified-monitoring-agent.service
check_unit snap.oracle-cloud-agent.oracle-cloud-agent.service
check_unit ollama.service
check_unit kibot-ollama-gateway.service
check_unit kibot-polymarket.service
check_unit lazarus-ampere.service
EOF
chmod 755 "${WATCHDOG_SCRIPT}"

cat > "${HEALTH_SCRIPT}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="/home/ubuntu/logs/kibot-batam-health.log"
{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] HOST=$(hostname)"
  echo "services:"
  for unit in unified-monitoring-agent.service snap.oracle-cloud-agent.oracle-cloud-agent.service ollama.service kibot-ollama-gateway.service kibot-polymarket.service lazarus-ampere.service; do
    printf '  %s=%s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
  done
  echo "mem:"
  free -h | sed 's/^/  /'
  echo "disk:"
  df -h /home / | sed 's/^/  /'
  echo "load:"
  uptime | sed 's/^/  /'
  echo
} >> "$LOG_FILE"
EOF
chmod 755 "${HEALTH_SCRIPT}"

install_service() {
  local src="$1"
  local dst="$2"
  install -m 0644 "$src" "$dst"
}

install_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    install -m 0644 "$src" "$dst"
  fi
}

install_script_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -f "$src" ]]; then
    install -m 755 "$src" "$dst"
  fi
}

install_service "${SERVICE_ROOT}/kibot-notifier.service" "${NOTIFIER_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-healer.service" "${HEALER_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-orchestrator.service" "${ORCHESTRATOR_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-security.service" "${SECURITY_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-guardian.service" "${GUARDIAN_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-analyst.service" "${ANALYST_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-manager.service" "${MANAGER_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-trinity.service" "${TRINITY_SERVICE}"
install_if_exists "${SERVICE_ROOT}/kibot-ollama-gateway.service" "${OLLAMA_GATEWAY_SERVICE}"
install_if_exists "${SERVICE_ROOT}/kibot-polymarket.service" "${POLYMARKET_SERVICE}"
install_service "${SERVICE_ROOT}/kibot-command-center.service" "${COMMAND_CENTER_SERVICE}"
install_service "${SERVICE_ROOT}/lazarus-ampere.service" "${LAZARUS_SERVICE}"
install_script_if_exists "${APP_ROOT}/tools/kibot_crashloop_guard.sh" "${CRASHLOOP_GUARD_SCRIPT}"
install_script_if_exists "${APP_ROOT}/tools/kibot_config_sanity.py" "/usr/local/bin/kibot-config-sanity.py"
install_script_if_exists "${APP_ROOT}/tools/kibot_replay_viewer.py" "/usr/local/bin/kibot-replay-viewer.py"

if ! command -v netdata >/dev/null 2>&1; then
  if command -v curl >/dev/null 2>&1; then
    export DISABLE_TELEMETRY=1
    curl -Ss https://get.netdata.cloud/kickstart.sh | bash -s -- --non-interactive --no-updates --release-channel stable
  fi
fi

NETDATA_CONF=""
for candidate in /etc/netdata/netdata.conf /opt/netdata/etc/netdata/netdata.conf; do
  if [[ -f "${candidate}" ]]; then
    NETDATA_CONF="${candidate}"
    break
  fi
done
if [[ -n "${NETDATA_CONF}" ]] && ! grep -q "KiBot Batam local-only dashboard" "${NETDATA_CONF}"; then
  cat >> "${NETDATA_CONF}" <<'EOF'

# KiBot Batam local-only dashboard
[web]
    bind to = 127.0.0.1
    allow connections from = localhost
    allow dashboard from = localhost
    allow management from = localhost
    allow netdata.conf from = localhost
EOF
fi

cat > "${CRASHLOOP_GUARD_SERVICE}" <<'EOF'
[Unit]
Description=KiBot Batam crashloop guard

[Service]
Type=oneshot
ExecStart=/usr/local/bin/kibot-crashloop-guard.sh
EOF

cat > "${CRASHLOOP_GUARD_TIMER}" <<'EOF'
[Unit]
Description=KiBot Batam crashloop guard timer

[Timer]
OnBootSec=90s
OnUnitActiveSec=5m
AccuracySec=30s
Persistent=true
Unit=kibot-crashloop-guard.service

[Install]
WantedBy=timers.target
EOF

cat > "${SANITY_SERVICE}" <<'EOF'
[Unit]
Description=KiBot config sanity check

[Service]
Type=oneshot
WorkingDirectory=/home/ubuntu/KiBot
ExecStart=/usr/bin/python3 /usr/local/bin/kibot-config-sanity.py
EOF

cat > "${SANITY_TIMER}" <<'EOF'
[Unit]
Description=KiBot config sanity timer

[Timer]
OnBootSec=2m
OnUnitActiveSec=15m
AccuracySec=1m
Persistent=true
Unit=kibot-config-sanity.service

[Install]
WantedBy=timers.target
EOF

cat > "${WATCHDOG_SERVICE}" <<'EOF'
[Unit]
Description=KiBot Batam watchdog

[Service]
Type=oneshot
ExecStart=/usr/local/bin/kibot-batam-watchdog.sh
EOF

cat > "${WATCHDOG_TIMER}" <<'EOF'
[Unit]
Description=KiBot Batam watchdog timer

[Timer]
OnBootSec=45s
OnUnitActiveSec=60s
AccuracySec=10s
Persistent=true
Unit=kibot-batam-watchdog.service

[Install]
WantedBy=timers.target
EOF

cat > "${HEALTH_SERVICE}" <<'EOF'
[Unit]
Description=KiBot Batam health report

[Service]
Type=oneshot
ExecStart=/usr/local/bin/kibot-batam-health-report.sh
EOF

cat > "${HEALTH_TIMER}" <<'EOF'
[Unit]
Description=KiBot Batam health report timer

[Timer]
OnBootSec=60s
OnUnitActiveSec=10m
AccuracySec=15s
Persistent=true
Unit=kibot-batam-health-report.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now kibot-trinity.service
systemctl enable --now kibot-healer.service
systemctl enable --now kibot-notifier.service
systemctl enable --now kibot-orchestrator.service
systemctl enable --now kibot-security.service
systemctl enable --now kibot-guardian.service
systemctl enable --now kibot-analyst.service
systemctl disable --now kibot-manager.service || true
systemctl enable --now kibot-ollama-gateway.service
systemctl enable --now kibot-polymarket.service
systemctl enable --now kibot-crashloop-guard.timer
systemctl enable --now kibot-config-sanity.timer
systemctl enable --now kibot-command-center.service
systemctl enable --now kibot-batam-watchdog.timer
systemctl enable --now kibot-batam-health-report.timer
systemctl disable --now indodax-dashboard-proxy.service || true
systemctl mask indodax-dashboard-proxy.service || true
if systemctl list-unit-files | grep -q '^netdata\.service'; then
  systemctl daemon-reload
  systemctl enable --now netdata.service
fi

if [[ -f "${RUNTIME_ROOT}/core/kibot_ollama_gateway.py" ]]; then
  install -d -o ubuntu -g ubuntu /home/ubuntu/KiBot/state
fi

echo "Batam autonomous baseline installed."
