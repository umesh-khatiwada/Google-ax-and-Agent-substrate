#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Builds and deploys Google AX control plane, task runner, and CLI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-google-ax}"
KUBECTL_CONTEXT="kind-${KIND_CLUSTER_NAME}"
REG_PORT="${KIND_REGISTRY_PORT:-5001}"
AX_REGISTRY="localhost:${REG_PORT}/ax"

echo "=========================================================="
echo " Deploying Google AX on cluster: ${KIND_CLUSTER_NAME}"
echo "=========================================================="

# 1. Deploy Redis for AX state management
echo "==> Deploying AX Redis in ax-system namespace..."
kubectl --context="${KUBECTL_CONTEXT}" apply -f "${ROOT_DIR}/manifests/ax/redis.yaml"
kubectl --context="${KUBECTL_CONTEXT}" rollout status deployment/ax-redis -n ax-system --timeout=60s

# 2. Build local ax CLI binary
echo "==> Building ax CLI binary..."
mkdir -p "${ROOT_DIR}/bin" "${HOME}/.local/bin"
cd "${ROOT_DIR}/ax"
go build -trimpath -ldflags="-s -w" -o "${ROOT_DIR}/bin/ax" ./cmd/ax
cp "${ROOT_DIR}/bin/ax" "${HOME}/.local/bin/ax"

# 3. Build and push ax-task-runner container image
echo "==> Building and pushing ax-task-runner container..."
mkdir -p "${ROOT_DIR}/ax/bin/linux_amd64"
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o "${ROOT_DIR}/ax/bin/linux_amd64/ax-task-runner" ./cmd/ax-task-runner
docker build -t "${AX_REGISTRY}/ax-task-runner:latest" -f Dockerfile.task-runner .
docker push "${AX_REGISTRY}/ax-task-runner:latest"

RUNNER_DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "${AX_REGISTRY}/ax-task-runner:latest" 2>/dev/null || echo "${AX_REGISTRY}/ax-task-runner:latest")
echo "    Task Runner Image: ${RUNNER_DIGEST}"

# 4. Deploy ax-server using ko
echo "==> Building and deploying ax-server using ko..."
KO_DOCKER_REPO="${AX_REGISTRY}" ko apply -f "${ROOT_DIR}/manifests/ax/ax-server.yaml"
kubectl --context="${KUBECTL_CONTEXT}" rollout status deployment/ax-server -n ax-system --timeout=60s

echo "==> Verifying AX deployment..."
"${ROOT_DIR}/bin/ax" ctx
"${ROOT_DIR}/bin/ax" version

echo "✔ Google AX control plane is deployed and ready!"
