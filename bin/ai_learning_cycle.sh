#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
API_BASE="${KIBOT_API_BASE:-http://127.0.0.1:8787}"
OUT_BASE="${KIBOT_AI_AUDIT_DIR:-${ROOT_DIR}/.tmp/ai-audits}"
TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="${OUT_BASE}/${TS}"
INPUT_JSON="${RUN_DIR}/rolling_30m_input.json"
PROVIDER_STATE_FILE="${OUT_BASE}/provider_state.json"

mkdir -p "${RUN_DIR}"

STATE_JSON="$(curl -fsS --max-time 8 "${API_BASE}/api/state" || echo '{}')"
LOGS_JSON="$(curl -fsS --max-time 8 "${API_BASE}/api/logs" || echo '[]')"

cat > "${INPUT_JSON}" <<JSON
{
  "window": "rolling_30m",
  "generated_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "state": ${STATE_JSON},
  "logs": ${LOGS_JSON}
}
JSON

python3 "${ROOT_DIR}/scripts/audit_trading_30m_ai.py" \
  --input "${INPUT_JSON}" \
  --all-providers \
  --provider-state-file "${PROVIDER_STATE_FILE}" \
  --output-dir "${RUN_DIR}" > "${RUN_DIR}/result.json" || true

ln -sfn "${RUN_DIR}" "${OUT_BASE}/latest"
