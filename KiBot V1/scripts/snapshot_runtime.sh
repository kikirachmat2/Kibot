#!/usr/bin/env bash
# ==============================================================================
# KiBot Sovereign System Runtime Snapshooter
# ==============================================================================
# Captures system load, processes, systemd service status, state files completeness,
# and recent telehealth logs. Multi-platform (Linux/macOS) compatible.
# ==============================================================================

set -euo pipefail

# Configuration
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/state"
LOG_DIR="${ROOT_DIR}/logs"
SNAPSHOT_FILE="${ROOT_DIR}/docs/audits/runtime_snapshot.txt"

# ANSI Colors
C_GREEN="\033[92m"
C_RED="\033[91m"
C_YELLOW="\033[93m"
C_CYAN="\033[96m"
C_BOLD="\033[1m"
C_RESET="\033[0m"

# Header
echo -e "${C_BOLD}${C_CYAN}📸 Creating KiBot Sovereign Runtime Telemetry Snapshot...${C_RESET}"

# Create audit directory if not exists
mkdir -p "$(dirname "${SNAPSHOT_FILE}")"

{
  echo "=============================================================================="
  echo "         KIBOT SOVEREIGN RUNTIME TELEMETRY DIAGNOSTIC SNAPSHOT"
  echo "=============================================================================="
  echo "Timestamp: $(date -u '+%Y-%m-%dT%H:%M:%SZ') (UTC)"
  echo "Host: $(hostname)"
  echo "Platform: $(uname -s -r -m)"
  echo "Workspace: ${ROOT_DIR}"
  echo "=============================================================================="
  echo ""

  echo "------------------------------------------------------------------------------"
  echo "1. SYSTEM RESOURCE METRICS"
  echo "------------------------------------------------------------------------------"
  if command -v uptime >/dev/null 2>&1; then
    echo "Uptime & Load Average:"
    uptime
  fi
  
  if command -v free >/dev/null 2>&1; then
    echo -e "\nMemory Allocation (Linux):"
    free -h
  elif command -v vm_stat >/dev/null 2>&1; then
    echo -e "\nMemory Page Allocation (macOS):"
    vm_stat | head -n 10
  fi

  echo -e "\nDisk Partition Health (/):"
  df -h /

  echo ""
  echo "------------------------------------------------------------------------------"
  echo "2. STATE FILES INTEGRITY CHECK"
  echo "------------------------------------------------------------------------------"
  CRITICAL_STATES=(
    "scanner_runtime.json"
    "leadlag_alpha.json"
    "market_rotation.json"
    "signal_quality.json"
    "expected_value.json"
    "strategy_scorecard.json"
    "punishment_state.json"
    "autonomous_director.json"
    "canary_daily_stats.json"
    "telemetry_snapshot.json"
    "active_trades.json"
  )

  printf "%-32s | %-10s | %-12s | %s\n" "State File Name" "Status" "Size (Bytes)" "Last Modified (UTC)"
  printf "%-32s | %-10s | %-12s | %s\n" "--------------------------------" "----------" "------------" "-------------------"

  for f in "${CRITICAL_STATES[@]}"; do
    FILE_PATH="${STATE_DIR}/${f}"
    if [ -f "${FILE_PATH}" ]; then
      SZ=$(wc -c < "${FILE_PATH}" | xargs)
      # Cross-platform stat formatting for last modification date
      if [ "$(uname -s)" = "Darwin" ]; then
        MOD=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "${FILE_PATH}")
      else
        MOD=$(stat -c "%y" "${FILE_PATH}" | cut -d. -f1)
      fi
      printf "%-32s | %-10s | %-12s | %s\n" "$f" "PRESENT" "$SZ" "$MOD"
    else
      printf "%-32s | %-10s | %-12s | %s\n" "$f" "MISSING" "0" "N/A"
    fi
  done

  echo ""
  echo "------------------------------------------------------------------------------"
  echo "3. RUNTIME ACTIVE SERVICES STATE"
  echo "------------------------------------------------------------------------------"
  if command -v systemctl >/dev/null 2>&1; then
    echo "systemd status (Batam Node):"
    SERVICES=(
      "redis-server"
      "ollama"
      "kibot-master"
      "kibot-scanner"
      "kibot-executor"
      "kibot-ai-scout"
      "kibot-janitor"
      "kibot-dashboard"
    )
    for svc in "${SERVICES[@]}"; do
      status="$(systemctl is-active "$svc" 2>/dev/null || echo "inactive")"
      printf "  %-30s : %s\n" "$svc" "$status"
    done
  else
    echo "No systemd detected. Local Process Analysis:"
    printf "  %-25s | %-8s | %s\n" "Process Match" "PID" "Command Snippet"
    printf "  %-25s | %-8s | %s\n" "-------------------------" "--------" "---------------"
    
    # Simple process check
    PROCESS_PATTERNS=(
      "kibot_dashboard"
      "kibot_master"
      "redis-server"
      "ollama"
    )
    for pat in "${PROCESS_PATTERNS[@]}"; do
      # Find PIDs
      PIDS=$(pgrep -f "$pat" || echo "")
      if [ -n "$PIDS" ]; then
        for pid in $PIDS; do
          cmd_info=$(ps -p "$pid" -o command= | head -c 50)
          printf "  %-25s | %-8s | %s...\n" "$pat" "$pid" "$cmd_info"
        done
      else
        printf "  %-25s | %-8s | %s\n" "$pat" "INACTIVE" "None"
      fi
    done
  fi

  echo ""
  echo "------------------------------------------------------------------------------"
  echo "4. RECENT TELEHEALTH LOG ERROR DIGEST (Last 25 lines)"
  echo "------------------------------------------------------------------------------"
  SOVEREIGN_LOG="${LOG_DIR}/kibot_sovereign.log"
  if [ -f "${SOVEREIGN_LOG}" ]; then
    tail -n 25 "${SOVEREIGN_LOG}"
  else
    echo "No sovereign logs found at ${SOVEREIGN_LOG}"
  fi

} > "${SNAPSHOT_FILE}"

# Print results to console too
cat "${SNAPSHOT_FILE}"

echo -e "\n${C_BOLD}${C_GREEN}✅ Telemetry Snapshot saved to: ${C_RESET}${SNAPSHOT_FILE}"
