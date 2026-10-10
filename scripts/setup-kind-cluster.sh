#!/usr/bin/env bash
# Copyright 2026 Google LLC
# Setup script for google-ax Kind cluster with all required feature gates,
# container registry, containerd certs patches, and gVisor/KVM support.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

KIND_CLUSTER_NAME="${KIND_CLUSTER_NAME:-google-ax}"
KUBECTL_CONTEXT="kind-${KIND_CLUSTER_NAME}"
REG_NAME="kind-registry"
REG_PORT="${KIND_REGISTRY_PORT:-5001}"
NODE_IMAGE="${KIND_NODE_IMAGE:-kindest/node:v1.35.0}"

echo "=========================================================="
echo " Setting up Kind cluster: ${KIND_CLUSTER_NAME}"
echo "=========================================================="

# 1. Setup local registry container on port 5001
echo "==> Ensuring local Docker registry '${REG_NAME}' on port ${REG_PORT}..."
if [ "$(docker inspect -f '{{.State.Running}}' "${REG_NAME}" 2>/dev/null || true)" == "true" ]; then
  if ! docker port "${REG_NAME}" | grep -q "${REG_PORT}"; then
    echo "    Registry exists but not on port ${REG_PORT}. Recreating..."
    docker rm -f "${REG_NAME}"
  fi
fi

if [ "$(docker inspect -f '{{.State.Running}}' "${REG_NAME}" 2>/dev/null || true)" != "true" ]; then
  docker run -d --restart=always \
    --label created-by=google-ax \
    -p "127.0.0.1:${REG_PORT}:5000" \
    --network bridge --name "${REG_NAME}" \
    registry:3
fi

# 2. Check KVM support
HAS_KVM=0
if [ -e /dev/kvm ] && docker run --rm --device /dev/kvm busybox true >/dev/null 2>&1; then
  HAS_KVM=1
  echo "==> /dev/kvm detected: micro-VM / Kata support enabled."
else
  echo "==> /dev/kvm not available: using gVisor container isolation."
fi

# 3. Create Kind cluster configuration
KIND_CONFIG=$(mktemp /tmp/kind-config-XXXXXX.yaml)
cat <<EOF > "${KIND_CONFIG}"
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
EOF

if [ "${HAS_KVM}" = "1" ]; then
  cat <<EOF >> "${KIND_CONFIG}"
  extraMounts:
  - hostPath: /dev/kvm
    containerPath: /dev/kvm
EOF
fi

cat <<EOF >> "${KIND_CONFIG}"
featureGates:
  ClusterTrustBundle: true
  ClusterTrustBundleProjection: true
  PodCertificateRequest: true
runtimeConfig:
  "certificates.k8s.io/v1beta1": "true"
networking:
  ipFamily: ipv4
containerdConfigPatches:
- |-
  [plugins."io.containerd.cri.v1.images".registry]
    config_path = "/etc/containerd/certs.d"
  [plugins."io.containerd.grpc.v1.cri".registry]
    config_path = "/etc/containerd/certs.d"
kubeadmConfigPatches:
- |
  kind: KubeletConfiguration
  serializeImagePulls: false
  maxParallelImagePulls: 4
EOF

# 4. Delete existing cluster if any
if kind get clusters | grep -q "^${KIND_CLUSTER_NAME}$"; then
  echo "==> Deleting existing kind cluster '${KIND_CLUSTER_NAME}'..."
  kind delete cluster --name "${KIND_CLUSTER_NAME}"
fi

# 5. Create cluster
echo "==> Creating kind cluster '${KIND_CLUSTER_NAME}' with node image ${NODE_IMAGE}..."
kind create cluster --name "${KIND_CLUSTER_NAME}" --config "${KIND_CONFIG}" --image "${NODE_IMAGE}"
rm -f "${KIND_CONFIG}"

# 6. Enable Proxy ARP/NDP on nodes
echo "==> Enabling Proxy ARP on kind nodes..."
for node in $(kind get nodes --name "${KIND_CLUSTER_NAME}"); do
  docker exec "${node}" sysctl net.ipv4.conf.all.proxy_arp=1
  docker exec "${node}" sysctl -e net.ipv6.conf.all.proxy_ndp=1 || true
  if [ "${HAS_KVM}" = "1" ]; then
    docker exec "${node}" chmod 666 /dev/kvm || true
  fi
done

# 7. Add registry hosts.toml to nodes
echo "==> Configuring containerd registry mirrors in node..."
REGISTRY_DIR="/etc/containerd/certs.d/localhost:${REG_PORT}"
for node in $(kind get nodes --name "${KIND_CLUSTER_NAME}"); do
  docker exec "${node}" mkdir -p "${REGISTRY_DIR}"
  cat <<EOF | docker exec -i "${node}" cp /dev/stdin "${REGISTRY_DIR}/hosts.toml"
[host."http://${REG_NAME}:5000"]
EOF
done

# 8. Connect registry to kind network
echo "==> Connecting local registry to kind network..."
if [ "$(docker inspect -f='{{json .NetworkSettings.Networks.kind}}' "${REG_NAME}")" = "null" ]; then
  docker network connect "kind" "${REG_NAME}"
fi

# 9. Document registry in kube-public ConfigMap
kubectl --context="${KUBECTL_CONTEXT}" apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: local-registry-hosting
  namespace: kube-public
data:
  localRegistryHosting.v1: |
    host: "localhost:${REG_PORT}"
    help: "https://kind.sigs.k8s.io/docs/user/local-registry/"
EOF

echo "==> Waiting for node Ready status..."
kubectl --context="${KUBECTL_CONTEXT}" wait --for=condition=Ready "node/${KIND_CLUSTER_NAME}-control-plane" --timeout=60s

echo "✔ Kind cluster '${KIND_CLUSTER_NAME}' is ready!"
