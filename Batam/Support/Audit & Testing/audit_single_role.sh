#!/bin/bash

# KiBot Trinity: Single-Role Audit & Verification
# Verify each node has ONLY its designated role services
# Usage: bash scripts/audit_single_role.sh

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_TIMEOUT=10

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
  echo -e "${GREEN}[INFO]${NC} $*"
}

log_warn() {
  echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $*"
}

log_header() {
  echo -e "${BLUE}========== $* ==========${NC}"
}

# Audit a single node
audit_node() {
  local node_id=$1
  local host=$2
  local user=$3
  local key=$4

  log_header "Auditing $node_id ($host)"

  # Query enabled services
  local services=$(ssh \
    -i "$REPO_ROOT/$key" \
    -o StrictHostKeyChecking=no \
    -o ConnectTimeout=$SSH_TIMEOUT \
    -o UserKnownHostsFile=/dev/null \
    "$user@$host" \
    "systemctl list-units --type=service --state=enabled --no-pager 2>/dev/null | grep -E 'kibot|KiBot|KiBot|ki-|kicryp' | awk '{print \$1}' | sort" \
    2>/dev/null || echo "ERROR")

  if [ "$services" == "ERROR" ]; then
    log_error "Could not connect to $node_id"
    return 1
  fi

  # Define expected services per role
  local expected=""
  local unexpected=""

  case "$node_id" in
    batam-manager)
      expected="kibot-manager kibot-analyst kibot-auditor kibot-notifier kibot-orchestrator kibot-security kibot-guardian kibot-ollama-gateway ki-telegram-monitor indodax-dashboard-proxy lazarus-ampere"
      unexpected="kibot-executor-indodax kibot-polymarket ki-global-scanner-mesh kibot-scanner kibot-executor-indodax kicryp-engine kicryp-manager"
      ;;
    EXECUTOR-executor-cluster)
      expected="kibot-executor-indodax kibot-polymarket"
      unexpected="kibot-manager kibot-analyst kibot-auditor kibot-notifier kibot-orchestrator kibot-security kibot-guardian kibot-ollama-gateway ki-telegram-monitor indodax-dashboard-proxy lazarus-ampere ki-global-scanner-mesh kibot-scanner kibot-executor-indodax kicryp-engine kicryp-manager"
      ;;
    SCANNER-scanner-cluster)
      expected="ki-global-scanner-mesh kibot-scanner"
      unexpected="kibot-executor-indodax kibot-polymarket kibot-manager kibot-analyst kibot-auditor kibot-notifier kibot-orchestrator kibot-security kibot-guardian kibot-ollama-gateway ki-telegram-monitor indodax-dashboard-proxy lazarus-ampere kibot-executor-indodax kicryp-engine kicryp-manager"
      ;;
    *)
      log_error "Unknown node: $node_id"
      return 1
      ;;
  esac

  echo "Expected services for $node_id role:"
  for svc in $expected; do
    echo "  ✓ $svc.service"
  done

  echo ""
  echo "Currently enabled on $node_id:"
  if [ -z "$services" ]; then
    log_warn "No matching services found (may be ok if templated or not deployed)"
  else
    echo "$services" | while read -r svc; do
      echo "  $svc"
    done
  fi

  echo ""
  echo "Checking for violations (unexpected services)..."
  local violations=0
  for unexpected_svc in $unexpected; do
    if echo "$services" | grep -q "^$unexpected_svc"; then
      log_error "VIOLATION: $unexpected_svc.service should NOT be on $node_id"
      ((violations++))
    fi
  done

  if [ $violations -eq 0 ]; then
    log_info "✓ $node_id role purity verified (no violations)"
    return 0
  else
    log_error "✗ $node_id has $violations violations"
    return 1
  fi
}

# Main execution
main() {
  log_header "KiBot Trinity Single-Role Audit"
  echo ""
  log_info "Authority: ROLE_MANIFEST.md"
  log_info "Checking live cluster for role purity..."
  echo ""

  if [ ! -f "$REPO_ROOT/ops/SERVERS.json" ]; then
    log_error "ops/SERVERS.json not found"
    return 1
  fi

  # Parse inventory and audit each node
  local passed=0
  local failed=0

  # Batam
  if audit_node "batam-manager" "100.103.77.10" "ubuntu" "SSH_BATAM/ssh-key-batam-active.pem"; then
    ((passed++))
  else
    ((failed++))
  fi
  echo ""

  # EXECUTOR
  if audit_node "EXECUTOR-executor-cluster" "100.122.1.109" "ubuntu" "SSH_SINGAPORE/SSH_EXECUTOR/ssh-key-2026-03-22.key"; then
    ((passed++))
  else
    ((failed++))
  fi
  echo ""

  # SCANNER
  if audit_node "SCANNER-scanner-cluster" "100.105.139.21" "ubuntu" "SSH_SINGAPORE/SSH_SCANNER/ssh-key-2026-03-27.key"; then
    ((passed++))
  else
    ((failed++))
  fi
  echo ""

  log_header "Audit Results"
  log_info "Passed: $passed/3 nodes"
  if [ $failed -gt 0 ]; then
    log_error "Failed: $failed/3 nodes"
    log_warn "Run: bash scripts/deploy_single_role_enforcement.sh"
    return 1
  fi

  log_info "All nodes pass role purity verification ✓"
}

main "$@"
