#!/bin/bash
# KiBot Backup Automation Script (G-005)
# Performs state backups before deployment or on schedule.

set -e

BACKUP_DIR="${HOME}/lazarus/backups"
KIBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/kibot_state_$TIMESTAMP.tar.gz"

echo "[KiBot Backup] Starting backup of state and critical configurations..."

# Create a tarball of the state directory and .env
cd "$KIBOT_DIR"
if [ -d "state" ]; then
    echo "[KiBot Backup] Archiving state directory and environment config..."
    tar -czf "$BACKUP_FILE" state/ .env 2>/dev/null || tar -czf "$BACKUP_FILE" state/
    echo "[KiBot Backup] Backup saved to: $BACKUP_FILE"
else
    echo "[KiBot Backup] WARNING: 'state' directory not found. Nothing to backup."
    exit 1
fi

# Rotate old backups (keep last 10)
echo "[KiBot Backup] Cleaning up old backups..."
ls -1tr "$BACKUP_DIR"/kibot_state_*.tar.gz | head -n -10 | xargs rm -f 2>/dev/null || true

# Write backup metadata
cat > "$BACKUP_DIR/latest_backup_status.json" <<EOF
{
  "last_backup": "$TIMESTAMP",
  "status": "SUCCESS",
  "file": "$BACKUP_FILE"
}
EOF

echo "[KiBot Backup] Complete!"
