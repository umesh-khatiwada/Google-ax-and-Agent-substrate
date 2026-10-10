#!/usr/bin/env bash
# Copyright 2026 Google LLC
# setup-fresh-cluster.sh
#
# Complete, end-to-end automation script to provision a brand-new Kind cluster
# with Google AX and Agent Substrate from scratch.
#
# Usage:
#   ./scripts/setup-fresh-cluster.sh [OPTIONS]
#
# Options:
#   --skip-example      Deploy cluster, substrate, and AX, but do not run the demo task
#   --no-clean          Do not delete existing cluster if already present (attempt upgrade/apply)
#   --cluster-name NAME Set Kind cluster name (default: google-ax)
#   --registry-port N   Set local Docker registry port (default: 5001)
#   -h, --help          Show this help message

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Configuration
KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-google-ax}"
KIND_REGISTRY_PORT="${KIND_REGISTRY_PORT:-5001}"
RUN_EXAMPLE=1
CLEAN_FIRST=1

# Color formatting
BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
  echo -e "${BLUE}${BOLD}==>${NC} ${BOLD}$*${NC}"
}

log_success() {
  echo -e "${GREEN}${BOLD}✔${NC} $*"
}

log_warn() {
  echo -e "${YELLOW}${BOLD}⚠${NC} $*"
}

log_error() {
  echo -e "${RED}${BOLD}✖${NC} $*"
}

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Provisions a fresh Kind cluster configured with Google AX and Agent Substrate.

Options:
  --skip-example        Skip running the demo task verification at the end
  --no-clean            Do not delete existing cluster first (attempt in-place deploy)
  --cluster-name NAME   Set custom cluster name (default: google-ax)
  --registry-port PORT  Set custom local Docker registry port (default: 5001)
  -h, --help            Show this help message

Example:
  $0                    # Full fresh teardown, build, deploy, and example verification
  $0 --skip-example     # Full fresh setup without running example task
EOF
  exit 0
}

# Parse command line flags
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-example)
      RUN_EXAMPLE=0
      shift
      ;;
    --no-clean)
      CLEAN_FIRST=0
      shift
      ;;
    --cluster-name)
      KIND_CLUSTER_NAME="$2"
      shift 2
      ;;
    --registry-port)
      KIND_REGISTRY_PORT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Unknown flag: $1"
      usage
      ;;
  esac
done

export KIND_CLUSTER_NAME
export KIND_REGISTRY_PORT
KUBECTL_CONTEXT="kind-${KIND_CLUSTER_NAME}"

echo -e "${BLUE}========================================================================${NC}"
echo -e "${BOLD} Google AX & Agent Substrate: Fresh Cluster Provisioner${NC}"
echo -e "${BLUE} Target Cluster: ${GREEN}${KIND_CLUSTER_NAME}${NC}"
echo -e "${BLUE} Local Registry: ${GREEN}localhost:${KIND_REGISTRY_PORT}${NC}"
echo -e "${BLUE}========================================================================${NC}"

# ---------------------------------------------------------------------------
# Pre-flight Check: Required CLI Tools
# ---------------------------------------------------------------------------
log_info "Running pre-flight checks..."
REQUIRED_TOOLS=("docker" "kind" "kubectl" "go" "ko" "git")
MISSING_TOOLS=()
for tool in "${REQUIRED_TOOLS[@]}"; do
  if ! command -v "${tool}" >/dev/null 2>&1; then
    MISSING_TOOLS+=("${tool}")
  fi
done

if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
  log_error "Missing required CLI tool(s): ${MISSING_TOOLS[*]}"
  echo "Please install the missing tools and re-run this script."
  exit 1
fi

# Ensure docker daemon is responsive
if ! docker info >/dev/null 2>&1; then
  log_error "Docker daemon is not running or current user lacks permissions."
  exit 1
fi

log_success "All pre-flight tool requirements met."

# ---------------------------------------------------------------------------
# Step 0: Clean Up Existing Cluster & Tunnels (if requested)
# ---------------------------------------------------------------------------
if [[ "${CLEAN_FIRST}" -eq 1 ]]; then
  log_info "Tearing down existing tunnels and cluster for a clean slate..."
  
  # Stop ax tunnel if active
  if [[ -x "${ROOT_DIR}/bin/ax" ]]; then
    "${ROOT_DIR}/bin/ax" tunnel stop "${KUBECTL_CONTEXT}" 2>/dev/null || true
  elif command -v ax >/dev/null 2>&1; then
    ax tunnel stop "${KUBECTL_CONTEXT}" 2>/dev/null || true
  fi

  # Delete kind cluster if exists
  if kind get clusters 2>/dev/null | grep -q "^${KIND_CLUSTER_NAME}$"; then
    echo "  Deleting existing Kind cluster '${KIND_CLUSTER_NAME}'..."
    kind delete cluster --name "${KIND_CLUSTER_NAME}"
  fi
fi

# ---------------------------------------------------------------------------
# Step 1: Create Kind Cluster with Feature Gates & Local Registry
# ---------------------------------------------------------------------------
log_info "[Step 1/4] Provisioning Kind cluster with v1.35.0, certificates API, and registry..."
"${ROOT_DIR}/scripts/setup-kind-cluster.sh"
log_success "Kind cluster '${KIND_CLUSTER_NAME}' is ready."

# ---------------------------------------------------------------------------
# Step 2: Deploy Agent Substrate Control Plane & WorkerPool
# ---------------------------------------------------------------------------
log_info "[Step 2/4] Deploying Agent Substrate control plane & gVisor WorkerPool..."
"${ROOT_DIR}/scripts/deploy-substrate.sh"
log_success "Agent Substrate is healthy in namespace 'ate-system'."

# ---------------------------------------------------------------------------
# Step 3: Deploy Google AX Control Plane & CLI
# ---------------------------------------------------------------------------
log_info "[Step 3/4] Deploying Google AX (Redis, Runner image, ax-server, CLI)..."
"${ROOT_DIR}/scripts/deploy-ax.sh"
log_success "Google AX control plane is operational in namespace 'ax-system'."

# ---------------------------------------------------------------------------
# Step 4: Run Example Lifecycle Verification
# ---------------------------------------------------------------------------
if [[ "${RUN_EXAMPLE}" -eq 1 ]]; then
  log_info "[Step 4/4] Running end-to-end Task & Workspace lifecycle verification..."
  "${ROOT_DIR}/scripts/run-example.sh"
  log_success "Example Task & Workspace verified end-to-end!"
else
  log_info "[Step 4/4] Skipping demo task as requested (--skip-example)."
fi

# ---------------------------------------------------------------------------
# Completion Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}========================================================================${NC}"
echo -e "${GREEN}${BOLD} Fresh Cluster Setup Completed Successfully!${NC}"
echo -e "${GREEN}========================================================================${NC}"
echo ""
echo "Cluster Details:"
echo "  Context:       ${KUBECTL_CONTEXT}"
echo "  Local Registry: localhost:${KIND_REGISTRY_PORT}"
echo "  AX CLI:        ${ROOT_DIR}/bin/ax (also symlinked in ~/.local/bin/ax)"
echo ""
echo "Useful Commands:"
echo "  ax ctx                                # Show cluster context and connection"
echo "  ax get tasks                          # List running tasks"
echo "  ax ssh demo-task -- uptime            # SSH into agent sandbox"
echo "  make example                          # Run/re-run demo task lifecycle"
echo "  make status                           # View all cluster pods and services"
echo "  make clean                            # Delete cluster and registry"
echo ""
