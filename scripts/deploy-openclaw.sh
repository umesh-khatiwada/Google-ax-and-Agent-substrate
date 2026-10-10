#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Deploy OpenClaw Orchestrator in Kind Cluster (google-ax)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

CLUSTER_NAME="google-ax"
IMAGE_TAG="localhost:5001/openclaw/openclaw:latest"

echo "=========================================================="
echo " Deploying OpenClaw to Kind Cluster: ${CLUSTER_NAME}"
echo " Telegram Bot: @openclawaxxbot"
echo "=========================================================="

# 1. Ensure bin dependencies
if [[ ! -f "${ROOT_DIR}/bin/kubectl" ]]; then
  echo "==> Extracting kubectl binary from kind node..."
  docker cp "${CLUSTER_NAME}-control-plane:/usr/bin/kubectl" "${ROOT_DIR}/bin/kubectl"
  chmod +x "${ROOT_DIR}/bin/kubectl"
fi

# 2. Build OpenClaw Docker Image
echo "==> Building OpenClaw container image (${IMAGE_TAG})..."
docker build -t "${IMAGE_TAG}" -f "${ROOT_DIR}/Dockerfile.openclaw" "${ROOT_DIR}"

# 3. Push to local registry and load into Kind
echo "==> Pushing to local registry and loading into Kind cluster..."
docker push "${IMAGE_TAG}"
kind load docker-image "${IMAGE_TAG}" --name "${CLUSTER_NAME}"

# 4. Apply Kubernetes Manifests
echo "==> Applying OpenClaw namespace, RBAC, and deployment..."
kubectl apply -f "${ROOT_DIR}/manifests/openclaw/openclaw.yaml"

# 5. Wait for Deployment Rollout
echo "==> Waiting for OpenClaw pod to become Ready..."
kubectl rollout status deployment/openclaw -n openclaw-system --timeout=60s

echo ""
echo "=========================================================="
echo " ✅ OpenClaw Successfully Deployed in Kind Cluster!"
echo " Telegram: https://t.me/openclawaxxbot"
echo " Check logs: kubectl logs -f -n openclaw-system deployment/openclaw"
echo "=========================================================="
