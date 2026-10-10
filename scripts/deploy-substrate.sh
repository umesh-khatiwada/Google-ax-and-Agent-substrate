#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Deploys Agent Substrate control plane and worker pool onto kind cluster.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-google-ax}"
KUBECTL_CONTEXT="kind-${KIND_CLUSTER_NAME}"
REG_PORT="${KIND_REGISTRY_PORT:-5001}"

echo "=========================================================="
echo " Deploying Agent Substrate on cluster: ${KIND_CLUSTER_NAME}"
echo "=========================================================="

# 1. Deploy core Substrate control plane
cd "${ROOT_DIR}/substrate"
echo "==> Deploying Agent Substrate control plane (ate-system)..."
go run ./cmd/ate-setup deploy ate-system \
  --kind \
  --kind-cluster-name="${KIND_CLUSTER_NAME}" \
  --credential-provider='{"name":"k8s.io"}'

# 2. Build and publish ateom-gvisor worker image
echo "==> Ensuring ateom-gvisor worker image is built..."
WORKER_IMG=$(KO_DOCKER_REPO="localhost:${REG_PORT}" ko build github.com/agent-substrate/substrate/cmd/ateom-gvisor)
echo "    Worker image: ${WORKER_IMG}"

# 3. Deploy WorkerPool
cd "${ROOT_DIR}"
echo "==> Applying Substrate WorkerPool..."
cat <<EOF | kubectl --context="${KUBECTL_CONTEXT}" apply -f -
apiVersion: ate.dev/v1alpha1
kind: WorkerPool
metadata:
  name: ax-workerpool
  namespace: ate-system
  labels:
    workload: ax
spec:
  replicas: 1
  workerImage: ${WORKER_IMG}
  sandboxClasses:
  - name: gvisor
  template:
    resources:
      limits:
        cpu: "4"
        memory: 4Gi
      requests:
        cpu: 500m
        memory: 1Gi
EOF

echo "==> Waiting for WorkerPool rollout..."
kubectl --context="${KUBECTL_CONTEXT}" rollout status deployment/ax-workerpool -n ate-system --timeout=60s || true

echo "==> Verifying Substrate API service..."
kubectl --context="${KUBECTL_CONTEXT}" get svc api -n ate-system

echo "✔ Agent Substrate is up and running!"
