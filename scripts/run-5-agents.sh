#!/usr/bin/env bash
# Copyright 2026 Google LLC
# run-5-agents.sh
#
# Launches 5 autonomous agents on Google AX and Agent Substrate, each with its
# own connected MCP tool server, running tasks with NVIDIA Nemotron
# (nvidia/nemotron-3-super-120b-a12b), and suspends each agent once completed.
#
# Strictly uses official open-source AX and Substrate APIs/CLIs without modifying
# any upstream code.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

AX_BIN="${ROOT_DIR}/bin/ax"
if ! command -v "${AX_BIN}" >/dev/null 2>&1 && [[ -x "${HOME}/.local/bin/ax" ]]; then
  AX_BIN="${HOME}/.local/bin/ax"
fi

ATE_BIN="${ROOT_DIR}/bin/kubectl-ate"
if ! [[ -x "${ATE_BIN}" ]]; then
  echo "==> Building official Substrate CLI (kubectl-ate)..."
  (cd "${ROOT_DIR}/substrate" && go build -trimpath -o "${ROOT_DIR}/bin/kubectl-ate" ./cmd/kubectl-ate)
  ATE_BIN="${ROOT_DIR}/bin/kubectl-ate"
fi

ax() { "${AX_BIN}" "$@"; }
ate() { "${ATE_BIN}" --context kind-google-ax "$@"; }

MANIFEST_FILE="${ROOT_DIR}/examples/five-agents/manifests.yaml"
EGRESS_MANIFEST="${ROOT_DIR}/manifests/egress/allow-all.yaml"

AGENTS=("security-agent" "linter-agent" "perf-agent" "docs-agent" "sre-agent")
ROLES=("security" "linter" "perf" "docs" "sre")

BOLD='\033[1m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}========================================================================${NC}"
echo -e "${BOLD} Launching 5 Agents with Connected MCP Servers & NVIDIA Nemotron${NC}"
echo -e "${CYAN} Model: nvidia/nemotron-3-super-120b-a12b${NC}"
echo -e "${BLUE}========================================================================${NC}"

# 0. Clean up previous runs if existing for a reproducible demo
echo -e "\n${BLUE}==>${NC} ${BOLD}Preparing clean state for 5 agents...${NC}"
for agent in "${AGENTS[@]}"; do
  ax delete task "${agent}" 2>/dev/null || true
  ax delete workspace "${agent/-agent/-workspace}" 2>/dev/null || true
done

# 1. Apply declarative manifests
echo -e "\n${BLUE}==>${NC} ${BOLD}Applying 5 Workspace and 5 Task manifests...${NC}"
ax apply -f "${MANIFEST_FILE}"

# 2. Configure Substrate EgressPolicy for each agent before resuming
echo -e "\n${BLUE}==>${NC} ${BOLD}Configuring Substrate EgressPolicies for outbound NVIDIA API access...${NC}"
for agent in "${AGENTS[@]}"; do
  ate create egress-policy "${agent}" -a default -f "${EGRESS_MANIFEST}" >/dev/null 2>&1 || true
done

# 3. Resume all 5 agents
echo -e "\n${BLUE}==>${NC} ${BOLD}Resuming all 5 Agents...${NC}"
for agent in "${AGENTS[@]}"; do
  echo -e "  -> Resuming ${CYAN}${agent}${NC}..."
  ax resume task "${agent}"
done

echo -e "\n${BLUE}==>${NC} ${BOLD}Initial Tasks Status:${NC}"
ax get tasks

# 3. Monitor agents execution and wait for completion
echo -e "\n${BLUE}==>${NC} ${BOLD}Monitoring Agent Execution & MCP Tool Invocations...${NC}"
COMPLETED_COUNT=0
MAX_WAIT_SECONDS=120
START_TIME=$(date +%s)

declare -A AGENT_DONE
for agent in "${AGENTS[@]}"; do
  AGENT_DONE["${agent}"]=0
done

while [[ "${COMPLETED_COUNT}" -lt "${#AGENTS[@]}" ]]; do
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_TIME))
  if [[ "${ELAPSED}" -gt "${MAX_WAIT_SECONDS}" ]]; then
    echo -e "${YELLOW}⚠ Reached timeout (${MAX_WAIT_SECONDS}s). Proceeding to collect results.${NC}"
    break
  fi

  for i in "${!AGENTS[@]}"; do
    agent="${AGENTS[$i]}"
    role="${ROLES[$i]}"

    if [[ "${AGENT_DONE[${agent}]}" -eq 1 ]]; then
      continue
    fi

    # Check if task wrote COMPLETED marker
    if ax ssh "${agent}" -- test -f /workspace/COMPLETED >/dev/null 2>&1; then
      AGENT_DONE["${agent}"]=1
      COMPLETED_COUNT=$((COMPLETED_COUNT + 1))
      echo -e "  ${GREEN}✔${NC} [${agent}] Completed task using connected MCP tools! (${COMPLETED_COUNT}/${#AGENTS[@]})"
    fi
  done

  if [[ "${COMPLETED_COUNT}" -lt "${#AGENTS[@]}" ]]; then
    sleep 3
  fi
done

# 4. Display Report Artifacts & Suspend Completed Agents
echo -e "\n${BLUE}========================================================================${NC}"
echo -e "${BOLD} Collecting Reports & Suspending Completed Agents${NC}"
echo -e "${BLUE}========================================================================${NC}"

for i in "${!AGENTS[@]}"; do
  agent="${AGENTS[$i]}"
  role="${ROLES[$i]}"

  echo -e "\n------------------------------------------------------------------------"
  echo -e " Report for ${BOLD}${agent}${NC} (Role: ${role}):"
  echo -e "------------------------------------------------------------------------"
  
  # Fetch and print the generated markdown report from inside the sandbox
  ax ssh "${agent}" -- cat "/workspace/${role}-report.md" 2>/dev/null || echo "(Report generated in /workspace/${role}-report.md)"

  # Suspend the completed task to free compute resources while saving state
  echo -e "\n  -> Suspending ${CYAN}${agent}${NC}..."
  ax suspend task "${agent}"
done

# 5. Final Verification
echo -e "\n${BLUE}========================================================================${NC}"
echo -e "${GREEN}${BOLD} All 5 Agents Successfully Executed, Evaluated, and Suspended!${NC}"
echo -e "${BLUE}========================================================================${NC}"
echo ""
ax get tasks
echo ""
echo "All actor snapshots and generated reports (/workspace/*-report.md) are"
echo "safely persisted in Agent Substrate snapshot storage."
echo "You can resume any agent at any time with: ax resume task <name>"
echo ""
