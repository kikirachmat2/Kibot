#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INDODAX_HOST="${INDODAX_HOST:-213.35.118.26}"
BINANCE_HOST="${BINANCE_HOST:-152.69.218.198}"
BATAM_HOST="${BATAM_HOST:-168.110.201.228}"
INDODAX_KEY="${INDODAX_KEY:-${ROOT_DIR}/SSH_SINGAPORE/SSH_EXECUTOR/ssh-key-2026-03-22.key}"
BINANCE_KEY="${BINANCE_KEY:-${ROOT_DIR}/SSH_SINGAPORE/SSH_SCANNER/ssh-key-2026-03-27.key}"
BATAM_KEY="${BATAM_KEY:-${ROOT_DIR}/SSH_BATAM/ssh-key-batam-active.pem}"

if [[ ! -f "$INDODAX_KEY" && -f "${ROOT_DIR}/SSH_INDODAX/ssh-key-2026-03-22.key" ]]; then
  INDODAX_KEY="${ROOT_DIR}/SSH_INDODAX/ssh-key-2026-03-22.key"
fi

if [[ ! -f "$BINANCE_KEY" && -f "${ROOT_DIR}/SSH_BINANCE/ssh-key-2026-03-27.key" ]]; then
  BINANCE_KEY="${ROOT_DIR}/SSH_BINANCE/ssh-key-2026-03-27.key"
fi

ssh_run() {
  local host="$1"
  local key="$2"
  shift 2
  ssh -i "$key" \
    -o BatchMode=yes \
    -o ConnectTimeout=8 \
    -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=2 \
    -o StrictHostKeyChecking=accept-new \
    "ubuntu@${host}" "$@"
}

echo "=== Indodax /api/state ==="
ssh_run "$INDODAX_HOST" "$INDODAX_KEY" 'payload="$(curl -sf --max-time 3 http://localhost:8787/api/state || true)"; if [ -z "$payload" ]; then echo "ERROR: empty response"; else PAYLOAD="$payload" python3 - <<'"'"'PY'"'"'
import json
import os
import sys

payload = os.environ.get("PAYLOAD", "").strip()
try:
    data = json.loads(payload)
except Exception as error:
    print(f"ERROR: invalid json ({error})")
    print(payload[:500])
    raise SystemExit(1)

for key in ["effectiveState","tradingAllowed","marketRegime","targetPursuitLabel","aiProviderSummary","statusMessage","degradedReason","healthDecision","nodeStatus"]:
    print(key + ": " + str(data.get(key, "N/A")))
PY
fi'

echo
echo "=== KiBot Manager /api/state ==="
ssh_run "$BATAM_HOST" "$BATAM_KEY" 'payload="$(curl -sf --max-time 3 http://localhost:9998/api/state || true)"; if [ -z "$payload" ]; then echo "ERROR: empty response"; else PAYLOAD="$payload" python3 - <<'"'"'PY'"'"' | head -30
import json
import os

payload = os.environ.get("PAYLOAD", "").strip()
print(json.dumps(json.loads(payload), indent=2, ensure_ascii=False))
PY
fi'

echo
echo "=== Node connectivity ==="
ssh_run "$INDODAX_HOST" "$INDODAX_KEY" 'journalctl -u kibot-executor-indodax --since "5 minutes ago" --no-pager | grep -iE "heartbeat|KiBot|node|connected|udp|signal" || true'

echo
echo "=== Service status ==="
ssh_run "$INDODAX_HOST" "$INDODAX_KEY" 'systemctl is-active kibot-executor-indodax || true; printf "legacy_kibot_recovery=%s\n" "$(systemctl is-active kibot-recovery.service 2>/dev/null || echo inactive)"; printf "legacy_kibot_engine_recovery_timer=%s\n" "$(systemctl is-active kibot-engine-recovery.timer 2>/dev/null || echo inactive)"'

echo
echo "=== Binance side ==="
ssh_run "$BINANCE_HOST" "$BINANCE_KEY" 'systemctl is-active kibot-executor-indodax ki-global-scanner-mesh || true; printf "legacy_kibot_recovery=%s\n" "$(systemctl is-active kibot-recovery.service 2>/dev/null || echo inactive)"; printf "legacy_kibot_local_scanner=%s\n" "$(systemctl is-active kibot-local-scanner.service 2>/dev/null || echo inactive)"; printf "legacy_kibot_coordinator=%s\n" "$(systemctl is-active kibot-coordinator.service 2>/dev/null || echo inactive)"; printf "legacy_KiBot_engine_recovery_timer=%s\n" "$(systemctl is-active kibot-executor-indodax-recovery.timer 2>/dev/null || echo inactive)"'
ssh_run "$BINANCE_HOST" "$BINANCE_KEY" 'payload="$(curl -sf --max-time 3 http://localhost:8788/api/state || true)"; if [ -z "$payload" ]; then echo "ERROR: empty response"; else PAYLOAD="$payload" python3 - <<'"'"'PY'"'"'
import json
import os

data = json.loads(os.environ.get("PAYLOAD", "{}"))
for key in ["effectiveState","signalCount","lastSignalAgeMs"]:
    print(key + ": " + str(data.get(key, "N/A")))
PY
fi'

echo
echo "=== Learning hooks ==="
ssh_run "$INDODAX_HOST" "$INDODAX_KEY" 'test -f /home/ubuntu/KiBot/state/pair_memory.json && echo "pair_memory: EXISTS" || echo "pair_memory: NOT FOUND"'
ssh_run "$INDODAX_HOST" "$INDODAX_KEY" 'for f in /home/ubuntu/KiBot/state/learning_review.json /home/ubuntu/KiBot/state/daily_report.json /home/ubuntu/KiBot/state/daily_cycle_state.json; do if [ -f "$f" ]; then echo "$(basename "$f"): EXISTS"; else echo "$(basename "$f"): NOT FOUND"; fi; done'
ssh_run "$BATAM_HOST" "$BATAM_KEY" 'journalctl -u kibot-manager --since "1 hour ago" --no-pager | grep -iE "WHATIF|pair_memory|LEARNING|AI REVIEW|batch_review" || true'
