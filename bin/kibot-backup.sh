#!/bin/bash
# KiBot Backup Automation Script (G-005)
# Performs state backups before deployment or on schedule.

set -e
umask 077

BACKUP_DIR="${HOME}/lazarus/backups"
KIBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="$BACKUP_DIR/kibot_state_$TIMESTAMP.tar.gz"

echo "[KiBot Backup] Starting backup of state and critical configurations..."

# Create a protected tarball of state and non-secret runtime config.
cd "$KIBOT_DIR"
if [ -d "state" ]; then
    echo "[KiBot Backup] Archiving state directory and non-secret runtime config..."
    BACKUP_ITEMS=(state/ Core/Intelligence/strategy/ Core/Intelligence/SERVER_INVENTORY.md)
    if [ "${KIBOT_BACKUP_INCLUDE_SECRETS:-0}" = "1" ] && [ -f ".env" ]; then
        echo "[KiBot Backup] Including .env because KIBOT_BACKUP_INCLUDE_SECRETS=1"
        BACKUP_ITEMS+=(.env)
    else
        echo "[KiBot Backup] Secrets are not included. Keep .env/vault material protected separately."
    fi
    tar -czf "$BACKUP_FILE" "${BACKUP_ITEMS[@]}"
    chmod 600 "$BACKUP_FILE"
    echo "[KiBot Backup] Backup saved to: $BACKUP_FILE"
else
    echo "[KiBot Backup] WARNING: 'state' directory not found. Nothing to backup."
    exit 1
fi

# Rotate old backups (keep last 10)
echo "[KiBot Backup] Cleaning up old backups..."
OLD_BACKUPS=$(ls -1t "$BACKUP_DIR"/kibot_state_*.tar.gz 2>/dev/null | tail -n +11 || true)
if [ -n "$OLD_BACKUPS" ]; then
    echo "$OLD_BACKUPS" | xargs rm -f 2>/dev/null || true
fi

# Write backup metadata
cat > "$BACKUP_DIR/latest_backup_status.json" <<EOF
{
  "last_backup": "$TIMESTAMP",
  "status": "SUCCESS",
  "file": "$BACKUP_FILE"
}
EOF

echo "[KiBot Backup] Complete!"
