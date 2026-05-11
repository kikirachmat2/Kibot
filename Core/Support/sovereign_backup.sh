#!/bin/bash
# KiBot Sovereign Backup
# Backs up the state directory and .env to a secure location

BACKUP_DIR="/home/ubuntu/KiBot_Backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
SOURCE_DIR="/home/ubuntu/KiBot"

mkdir -p "$BACKUP_DIR"

echo "[BACKUP] Starting sovereign backup at $TIMESTAMP..."

# Create a compressed archive of state and config
tar -czf "$BACKUP_DIR/kibot_backup_$TIMESTAMP.tar.gz" \
    -C "$SOURCE_DIR" Core/state .env

# Keep only last 7 days of backups
find "$BACKUP_DIR" -name "kibot_backup_*.tar.gz" -mtime +7 -delete

echo "[BACKUP] Backup completed: $BACKUP_DIR/kibot_backup_$TIMESTAMP.tar.gz"
