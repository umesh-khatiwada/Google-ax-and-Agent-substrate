# Google AX and Agent Substrate on Kubernetes (Kind)

> Declarative, high-throughput agentic runtime orchestrating sandboxed autonomous AI agents on top of **Agent Substrate** in a local **Kind** cluster (`google-ax`).

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-v1.35.0-326ce5.svg)](https://kubernetes.io)
[![Kind](https://img.shields.io/badge/Kind-google--ax-green.svg)](https://kind.sigs.k8s.io)

---

## 📑 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Directory Structure](#directory-structure)
- [Step-by-Step Setup](#step-by-step-setup)
  - [1. Create the Kind Cluster](#1-create-the-kind-cluster)
  - [2. Deploy Agent Substrate](#2-deploy-agent-substrate)
  - [3. Deploy Google AX](#3-deploy-google-ax)
- [Running the Example Agent Setup](#running-the-example-agent-setup)
- [CLI Reference](#cli-reference)
- [Troubleshooting & Compatibility Notes](#troubleshooting--compatibility-notes)

---

## Overview

[**Google AX**](https://github.com/google/ax) is Google's open-source declarative orchestrator for autonomous AI agents. Unlike stateless web microservices or traditional batch jobs, AI agents are stateful, execute long-running loops, require isolated execution environments, and interact with tool servers (such as MCP) and model APIs.

AX introduces three primary declarative primitives:
1. **`Task`**: Declares an isolated sandbox runtime with CPU/memory limits, lifecycle policies, and optional debug access.
2. **`Workspace`**: Pre-wires Git repositories, Model Context Protocol (MCP) tool servers, and skill packages into `/workspace`.
3. **`Model`**: Configures LLM provider credentials and access centrally.

AX executes directly on top of [**Agent Substrate**](https://github.com/agent-substrate/substrate), which provides secure sandboxing (via gVisor or micro-VMs/KVM), snapshot-based suspension and resumption, and high-density actor scheduling.

---

## Architecture

```
                  ┌────────────────────────────────────────┐
                  │                 ax CLI                 │
                  │        (apply / ssh / suspend)         │
                  └───────────────────┬────────────────────┘
                                      │ gRPC / Port-Forward
                                      ▼
                  ┌────────────────────────────────────────┐
                  │         ax-server (ax-system)          │
                  │  (Reconciler, API Server, Metadata)    │
                  └───────────────┬────────────┬───────────┘
                                  │            │
                         State    │            │ Actor Scheduling
                                  ▼            ▼
                     ┌──────────────────┐   ┌──────────────────────────┐
                     │  Redis Database  │   │  Agent Substrate API     │
                     │   (ax-redis)     │   │     (api.ate-system)     │
                     └──────────────────┘   └─────────────┬────────────┘
                                                          │
                                         ┌────────────────┴───────────────┐
                                         ▼                                ▼
                              ┌──────────────────────┐        ┌──────────────────────┐
                              │    WorkerPool Pod    │        │    WorkerPool Pod    │
                              │ (ax-workerpool /     │        │                      │
                              │   ateom-gvisor)      │        │                      │
                              │  ┌────────────────┐  │        │                      │
                              │  │ Agent Sandbox  │  │        │                      │
                              │  │ (ax-task-runner│  │        │                      │
                              │  │  + /workspace) │  │        │                      │
                              │  └────────────────┘  │        │                      │
                              └──────────────────────┘        └──────────────────────┘
```

---

## Prerequisites

- **Docker**: Docker Engine 24+ with Buildx installed.
- **Go**: Go 1.23+ installed.
- **Kind**: `kind` CLI v0.26+ installed.
- **kubectl**: Kubernetes CLI tool.
- **ko**: Container image builder for Go (`go install github.com/google/ko@latest`).

---

## Quick Start

### Option A: Turnkey Fresh Cluster Setup (Recommended)
Tear down any old cluster, recreate the cluster and registry with all prerequisites, deploy Agent Substrate and Google AX, and verify the example setup in one command:

```bash
# Provision a completely fresh cluster and verify end-to-end
./scripts/setup-fresh-cluster.sh

# Or via Makefile:
make fresh
```

Flags supported by `setup-fresh-cluster.sh`:
- `--skip-example`: Deploy cluster, Substrate, and AX, but skip running the demo task.
- `--no-clean`: Keep existing cluster if present rather than deleting it first.
- `--cluster-name <name>`: Custom cluster name (default: `google-ax`).
- `--registry-port <port>`: Custom registry port (default: `5001`).

### Option B: Step-by-Step Setup

```bash
# 1. Create the kind cluster 'google-ax' with required feature gates
make cluster

# 2. Deploy the Agent Substrate control plane & workerpool
make substrate

# 3. Deploy Google AX (Redis, ax-server, task-runner, ax CLI)
make ax

# 4. Run the example agent task lifecycle
make example
```

---

## Directory Structure

```
.
├── Makefile                     # Root automation targets
├── README.md                    # This documentation
├── ax/                          # Google AX source code & deployment manifests
├── substrate/                   # Agent Substrate source code & installation tools
├── scripts/
│   ├── setup-fresh-cluster.sh   # All-in-one fresh cluster teardown & provisioning script
│   ├── setup-kind-cluster.sh    # Creates the 'google-ax' kind cluster with local registry
│   ├── deploy-substrate.sh      # Deploys Agent Substrate control plane + WorkerPool
│   ├── deploy-ax.sh             # Deploys Redis, builds runner image & ax-server, installs CLI
│   └── run-example.sh           # Runs an end-to-end Task & Workspace lifecycle demo
├── manifests/
│   ├── ax/
│   │   ├── redis.yaml           # AX Redis state store manifest
│   │   └── ax-server.yaml       # AX API and reconciler deployment
│   └── substrate/
│       └── workerpool.yaml      # Substrate WorkerPool specification
└── examples/
    ├── example-task.yaml        # Example Task + Workspace declaring git repo
    └── simple-task.yaml         # Minimal Task without external workspace
```

---

## Step-by-Step Setup

### 1. Create the Kind Cluster

Agent Substrate and Google AX rely on specific Kubernetes certificate primitives (`ClusterTrustBundle` and `PodCertificateRequest`) as well as local image distribution.

Run:
```bash
./scripts/setup-kind-cluster.sh
```

This performs the following configuration:
- Spins up a persistent local container registry at `localhost:5001` (`kind-registry`) connected to the Docker `kind` bridge network.
- Creates the `google-ax` cluster using node image `kindest/node:v1.35.0`.
- Enables feature gates:
  - `ClusterTrustBundle: true`
  - `ClusterTrustBundleProjection: true`
  - `PodCertificateRequest: true`
- Enables runtime API `certificates.k8s.io/v1beta1: "true"`.
- Patches containerd in the node with `[plugins."io.containerd.cri.v1.images".registry] config_path = "/etc/containerd/certs.d"` to resolve `localhost:5001`.
- Enables `/dev/kvm` extraMounts (if present on the host) and sets `sysctl net.ipv4.conf.all.proxy_arp=1`.

Verify node status:
```bash
kubectl --context kind-google-ax get nodes
```

---

### 2. Deploy Agent Substrate

Agent Substrate provides the underlying execution substrate for AX tasks.

Run:
```bash
./scripts/deploy-substrate.sh
```

This deploys:
1. **CRDs & RBAC**: `WorkerPool`, `SandboxConfig`, `CSIDriverConfig`.
2. **`podcertificate-controller`**: Signs identity and mTLS certificates across the substrate mesh.
3. **Control Plane (`ate-system`)**:
   - `postgres-0`: Substrate persistence backend.
   - `ate-api-server`: Substrate Control API (`api.ate-system.svc.cluster.local:443`).
   - `ate-controller`: Lifecycle controller.
   - `atelet`: Node agent DaemonSet.
   - `atenet-router` & `atenet-egress`: Ingress/egress dynamic policy routing.
   - `rustfs`: S3-compatible snapshot object storage.
4. **WorkerPool (`ax-workerpool`)**: Hosts gVisor-isolated worker pods (`ateom-gvisor`) that schedule actor sandboxes.

Verify Substrate components:
```bash
kubectl --context kind-google-ax get pods -n ate-system
kubectl --context kind-google-ax get workerpools -n ate-system
```

---

### 3. Deploy Google AX

Deploy the Google AX control plane, build the task runner image, and install the `ax` CLI.

Run:
```bash
./scripts/deploy-ax.sh
```

This performs:
1. **Redis deployment**: Deploys `ax-redis` in `ax-system` namespace.
2. **CLI compilation**: Compiles `cmd/ax` and places `ax` in `bin/ax` and `~/.local/bin/ax`.
3. **Task Runner image**: Cross-compiles `cmd/ax-task-runner` (with python, `google-antigravity`, git, and metadata hooks) and pushes `localhost:5001/ax/ax-task-runner:latest` to the local registry.
4. **`ax-server` deployment**: Builds and deploys `ax-server` using `ko` with in-cluster service account authentication and token projections.

Verify AX components:
```bash
kubectl --context kind-google-ax get pods -n ax-system
ax ctx
ax version
```

---

## Running the Example Agent Setup

Run the automated lifecycle verification script:

```bash
./scripts/run-example.sh
```

### Manual Walkthrough

#### 1. Define the Workspace and Task
Apply [`examples/example-task.yaml`](examples/example-task.yaml):
```bash
ax apply -f examples/example-task.yaml
```

Check the initial task state:
```bash
ax get tasks
# NAME        ATESPACE   PHASE       ACTOR       WORKER-IP   AGE
# demo-task   default    Suspended   demo-task   <none>      0s
```
> **Note**: Newly declared tasks start in `Suspended` phase to save resources until explicitly scheduled.

#### 2. Resume the Task
Resuming requests compute from Agent Substrate, boots a sandbox actor, pre-clones the Git repository into `/workspace`, and prepares the environment:
```bash
ax resume task demo-task
```

Check status:
```bash
ax describe task demo-task
# Name:         demo-task
# Atespace:     default
# Phase:        Running
# Actor:        demo-task
# Worker IP:    10.244.0.25
# Conditions:
#   Ready           True    TaskRunning    Task is running and its workspace is ready
#   WorkspaceReady  True    SetupComplete  Workspace setup completed at 10.244.0.25
```

#### 3. Inspect Inside the Agent Sandbox via `ax ssh`
Execute commands directly inside the isolated sandbox:
```bash
# Verify cloned Git workspace:
ax ssh demo-task -- ls -la /workspace

# Verify process environment:
ax ssh demo-task -- sh -c 'echo "DEMO_ENV=$DEMO_ENV"; echo "AX_METADATA_URL=$AX_METADATA_URL"'

# Query in-sandbox metadata server for task spec:
ax ssh demo-task -- curl -s "$AX_METADATA_URL/metadata/v1alpha1/ax/task"
```

#### 4. Suspend and Resume the Task
Checkpoint actor state and terminate compute:
```bash
ax suspend task demo-task
ax get tasks
# NAME        ATESPACE   PHASE       ACTOR       WORKER-IP   AGE
# demo-task   default    Suspended   demo-task   <none>      2m
```

Restore the task back to running:
```bash
ax resume task demo-task
ax get tasks
# NAME        ATESPACE   PHASE     ACTOR       WORKER-IP     AGE
# demo-task   default    Running   demo-task   10.244.0.25   2m
```

---

## CLI Reference

The `ax` CLI connects automatically to the active Kubernetes context:

| Command | Description |
|---|---|
| `ax ctx` | Displays active Kubernetes context and port-forward status |
| `ax get tasks` | Lists all tasks in the current atespace |
| `ax get task <name>` | Retrieves task specification and runtime status as YAML |
| `ax describe task <name>` | Displays human-readable details and condition transitions |
| `ax watch task <name>` | Streams phase and condition changes in real-time |
| `ax resume task <name>` | Starts or unpauses an actor in the Agent Substrate cluster |
| `ax suspend task <name>` | Checkpoints task state and halts sandbox container |
| `ax ssh <name> -- <cmd>` | Executes command or opens interactive shell inside sandbox |
| `ax delete task <name>` | Removes task definition and deletes substrate actor |
| `ax get workspaces` | Lists declared workspaces |
| `ax get models` | Lists configured model provider credentials |

---

## Troubleshooting & Compatibility Notes

1. **Kubernetes API Version (`PodCertificateRequest`)**:
   - `PodCertificateRequest` moved to `certificates.k8s.io/v1beta1` in Kubernetes v1.35+.
   - Cluster image is configured as `kindest/node:v1.35.0` with `certificates.k8s.io/v1beta1` enabled in `runtimeConfig`.
2. **Containerd Registry Resolution in Kind**:
   - Containerd 2.x uses `[plugins."io.containerd.cri.v1.images".registry] config_path = "/etc/containerd/certs.d"`.
   - The cluster config automatically injects these containerd patches so images pushed to `localhost:5001` pull properly inside the node.
3. **Snapshot Storage Location**:
   - Substrate validates `actor_template.snapshot_config.storage_location` as a URI with a valid bucket host.
   - `AX_SNAPSHOTS_BUCKET` is configured as `gs://ate-snapshots/` to match in-cluster storage.
