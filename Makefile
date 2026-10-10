# Makefile for Google AX and Agent Substrate on Kind
# Target cluster: google-ax

SHELL := /bin/bash

.PHONY: help all cluster substrate ax example clean status test

help:
	@echo "Google AX & Agent Substrate on Kind Cluster 'google-ax'"
	@echo ""
	@echo "Usage:"
	@echo "  make all         - Complete setup: cluster, substrate, and Google AX"
	@echo "  make cluster     - Create kind cluster 'google-ax' with local registry"
	@echo "  make substrate   - Deploy Agent Substrate control plane and workerpool"
	@echo "  make ax          - Build and deploy Google AX control plane, runner, and CLI"
	@echo "  make example     - Run the end-to-end demo agent task lifecycle"
	@echo "  make status      - Check cluster, substrate, and AX status"
	@echo "  make clean       - Tear down the kind cluster and local registry"
	@echo ""

all: cluster substrate ax example

cluster:
	./scripts/setup-kind-cluster.sh

substrate:
	./scripts/deploy-substrate.sh

ax:
	./scripts/deploy-ax.sh

example:
	./scripts/run-example.sh

status:
	@echo "==> Cluster Nodes:"
	@kubectl --context kind-google-ax get nodes
	@echo ""
	@echo "==> Substrate Services (ate-system):"
	@kubectl --context kind-google-ax get svc,pods -n ate-system
	@echo ""
	@echo "==> Google AX Services (ax-system):"
	@kubectl --context kind-google-ax get svc,pods -n ax-system
	@echo ""
	@echo "==> AX Tasks:"
	@command -v ax >/dev/null && ax get tasks || bin/ax get tasks

clean:
	@echo "==> Deleting kind cluster google-ax..."
	kind delete cluster --name google-ax || true
	@echo "==> Stopping kind-registry container..."
	docker rm -f kind-registry || true
