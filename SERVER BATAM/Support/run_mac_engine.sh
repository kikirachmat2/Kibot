#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRADLEW="${ROOT_DIR}/gradlew"
MAC_PORT="${MAC_ENGINE_PORT:-8787}"

if [[ ! -x "${GRADLEW}" ]]; then
  echo "gradlew tidak ditemukan atau tidak executable di ${GRADLEW}"
  exit 1
fi

cd "${ROOT_DIR}"

if lsof -nP -iTCP:"${MAC_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Mac engine sudah berjalan atau port ${MAC_PORT} sedang dipakai."
  echo "Coba buka: http://127.0.0.1:${MAC_PORT}"
  exit 0
fi

if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  echo "Peringatan: ${ROOT_DIR}/.env belum ada."
fi

if [[ ! -f "${ROOT_DIR}/apps/mac-engine/.env" ]]; then
  echo "Peringatan: ${ROOT_DIR}/apps/mac-engine/.env belum ada."
fi

echo "Menjalankan Mac engine di http://127.0.0.1:${MAC_PORT}"
exec "${GRADLEW}" :apps:mac-engine:run --no-daemon
