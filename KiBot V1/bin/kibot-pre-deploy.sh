#!/bin/bash
# KiBot Pre-Deploy Guard (G-006)
# Checks system state and tests code before allowing a deploy/restart

set -e

KIBOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$KIBOT_DIR"

echo "=== KiBot Pre-Deploy Guard ==="

# 1. State Backup
echo "[1/5] Running pre-deploy backup..."
./bin/kibot-backup.sh

# 2. Syntax Check (Smoke Test)
echo "[2/5] Running Python syntax checks..."
find Core MasterNode.py -name "*.py" -exec python3 -m py_compile {} +
echo "✅ All Python files compiled successfully."

# 3. Check for unstaged/uncommitted changes
echo "[3/5] Checking git status..."
if [ -d ".git" ]; then
    git status -s
else
    echo "⚠️ Not a git repository, skipping git checks."
fi

# 4. Service Restart Plan
echo "[4/5] Generating restart plan..."
echo "Services that will be restarted:"
echo "- kibot-master (Master Node)"
echo "- kibot-dashboard (Observability Layer)"
echo "- kibot-janitor (Optional System Janitor)"

# 5. Rollback Hints
echo "[5/5] Rollback Plan:"
if [ -f "$HOME/lazarus/backups/latest_backup_status.json" ]; then
    LATEST_BACKUP=$(grep -o '"file": "[^"]*' "$HOME/lazarus/backups/latest_backup_status.json" | cut -d'"' -f4)
    echo "If the deployment fails, restore state from:"
    echo "$LATEST_BACKUP"
    echo "Command: tar -xzf $LATEST_BACKUP -C $KIBOT_DIR"
else
    echo "No latest backup metadata found. Check $HOME/lazarus/backups"
fi

echo "==============================="
echo "✅ Pre-deploy checks passed. Safe to proceed with deployment."
