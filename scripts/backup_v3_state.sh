#!/usr/bin/env bash
# ==============================================================================
# KiBot V3 — Offsite SQLite Database Backup & Sync Script
# Runs on Server 2 (via cron or cluster/watchdog.py)
#
# Safe WAL Mode Backup:
# Uses sqlite3 online backup (.backup) or rsync to pull database from SG1
# without locking trading transactions or risking partial writes.
# ==============================================================================
set -euo pipefail

SG1_HOST="${SG1_HOST:-100.105.139.21}"
SG1_USER="${SG1_USER:-ubuntu}"
REMOTE_DB_PATH="${REMOTE_DB_PATH:-/home/ubuntu/kibot_v3_data/kibot_v3.db}"
LOCAL_BACKUP_DIR="${LOCAL_BACKUP_DIR:-/home/ubuntu/kibot_v3_backup}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DEST_FILE="${LOCAL_BACKUP_DIR}/kibot_v3_${TIMESTAMP}.db"
LATEST_LINK="${LOCAL_BACKUP_DIR}/kibot_v3.db"

mkdir -p "${LOCAL_BACKUP_DIR}"

echo "[$(date -u +"%Y-%m-%d %H:%M:%SZ")] Starting KiBot V3 database backup from ${SG1_HOST}..."

# 1. Trigger remote atomic sqlite backup to avoid dirty reads during WAL mode
ssh -i "${SSH_KEY}" -o ConnectTimeout=10 -o BatchMode=yes "${SG1_USER}@${SG1_HOST}" \
    "sqlite3 ${REMOTE_DB_PATH} '.backup /tmp/kibot_v3_atomic.db'"

# 2. Securely pull the consistent snapshot to Server 2
scp -i "${SSH_KEY}" -o ConnectTimeout=10 -B \
    "${SG1_USER}@${SG1_HOST}:/tmp/kibot_v3_atomic.db" "${DEST_FILE}"

# 3. Clean up temporary snapshot on SG1
ssh -i "${SSH_KEY}" -o ConnectTimeout=10 -o BatchMode=yes "${SG1_USER}@${SG1_HOST}" \
    "rm -f /tmp/kibot_v3_atomic.db"

# 4. Verify integrity of the received backup on Server 2
INTEGRITY_CHECK=$(sqlite3 "${DEST_FILE}" "PRAGMA integrity_check;" || echo "FAILED")
if [ "${INTEGRITY_CHECK}" != "ok" ]; then
    echo "❌ Backup integrity check failed: ${INTEGRITY_CHECK}"
    rm -f "${DEST_FILE}"
    exit 1
fi

# 5. Update latest symlink
ln -sf "${DEST_FILE}" "${LATEST_LINK}"

echo "✅ Backup successfully created and verified: ${DEST_FILE}"

# 6. Retention policy: Keep last 30 days of snapshots
find "${LOCAL_BACKUP_DIR}" -name "kibot_v3_*.db" -type f -mtime +30 -delete
echo "🧹 Old backups pruned (retention: 30 days)."
