#!/usr/bin/env bash
set -euo pipefail

# KiBot Sovereign Backup
# Backs up the canonical runtime state, env, and service config.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${KIBOT_BACKUP_DIR:-/home/ubuntu/KiBot_Backups}"
TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
ARCHIVE_PATH="${BACKUP_DIR}/kibot_backup_${TIMESTAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

echo "[BACKUP] Starting sovereign backup at ${TIMESTAMP}..."

tar -czf "${ARCHIVE_PATH}" \
  -C "${ROOT_DIR}" \
  state \
  .env \
  config/systemd \
  Core/Intelligence/SERVER_INVENTORY.md

# Keep only last 7 days of backups.
find "${BACKUP_DIR}" -name "kibot_backup_*.tar.gz" -mtime +7 -delete

echo "[BACKUP] Backup completed: ${ARCHIVE_PATH}"
