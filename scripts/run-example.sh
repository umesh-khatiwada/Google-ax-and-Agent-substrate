#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Demonstrates running an agentic task and workspace on Google AX in Kind.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

AX_BIN="${ROOT_DIR}/bin/ax"
if ! command -v "${AX_BIN}" >/dev/null 2>&1 && [[ -x "${HOME}/.local/bin/ax" ]]; then
  AX_BIN="${HOME}/.local/bin/ax"
fi

ax() { "${AX_BIN}" "$@"; }

TASK_NAME="demo-task"
WORKSPACE_NAME="demo-workspace"
ATESPACE="default"

echo "=========================================================="
echo " Running Google AX Example Setup (Task + Workspace Lifecycle)"
echo "=========================================================="

echo "==> Cleaning up any previous demo task..."
ax delete task "${TASK_NAME}" -a "${ATESPACE}" 2>/dev/null || true
ax delete workspace "${WORKSPACE_NAME}" -a "${ATESPACE}" 2>/dev/null || true

echo "==> Applying example Task and Workspace manifests..."
ax apply -f "${ROOT_DIR}/examples/example-task.yaml"

echo "==> Checking task state (initial state: Suspended)..."
ax get tasks -a "${ATESPACE}"

echo "==> Resuming task (allocates sandbox actor and clones workspace)..."
ax resume task "${TASK_NAME}" -a "${ATESPACE}"

echo "==> Task details:"
ax describe task "${TASK_NAME}" -a "${ATESPACE}"

echo "==> Testing ax ssh into the agent sandbox:"
echo "--- ls -la /workspace ---"
ax ssh "${TASK_NAME}" -a "${ATESPACE}" -- ls -la /workspace

echo "--- Check environment inside sandbox ---"
ax ssh "${TASK_NAME}" -a "${ATESPACE}" -- sh -c 'echo "DEMO_ENV=$DEMO_ENV"; echo "AX_METADATA_URL=$AX_METADATA_URL"'

echo "--- Query task metadata server ---"
ax ssh "${TASK_NAME}" -a "${ATESPACE}" -- sh -c 'curl -s "$AX_METADATA_URL/metadata/v1alpha1/ax/task" | head -n 15'

echo "==> Suspending task (checkpoints state and terminates compute)..."
ax suspend task "${TASK_NAME}" -a "${ATESPACE}"
ax get tasks -a "${ATESPACE}"

echo "==> Resuming task back to Running..."
ax resume task "${TASK_NAME}" -a "${ATESPACE}"
ax get tasks -a "${ATESPACE}"

echo "✔ Example setup demonstrated successfully!"
