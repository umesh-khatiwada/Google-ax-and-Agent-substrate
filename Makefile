# Makefile for Google AX and Agent Substrate on Kind
# Target cluster: google-ax

SHELL := /bin/bash

.PHONY: help all fresh setup-fresh cluster substrate ax example five-agents openclaw openclaw-deploy openclaw-status openclaw-logs clean status test

help:
	@echo "Google AX & Agent Substrate on Kind Cluster 'google-ax'"
	@echo ""
	@echo "Usage:"
	@echo "  make fresh           - Tear down old setup and provision a fresh cluster from scratch"
	@echo "  make all             - Complete setup: cluster, substrate, and Google AX"
	@echo "  make cluster         - Create kind cluster 'google-ax' with local registry"
	@echo "  make substrate       - Deploy Agent Substrate control plane and workerpool"
	@echo "  make ax              - Build and deploy Google AX control plane, runner, and CLI"
	@echo "  make example         - Run the end-to-end demo agent task lifecycle"
	@echo "  make five-agents     - Run 5 agents with MCP & NVIDIA Nemotron, then suspend"
	@echo "  make openclaw        - Deploy OpenClaw Telegram orchestrator in the cluster"
	@echo "  make openclaw-status - Check OpenClaw pod and Telegram orchestrator status"
	@echo "  make openclaw-logs   - Follow live logs of OpenClaw in Kubernetes"
	@echo "  make status          - Check cluster, substrate, and AX status"
	@echo "  make clean           - Tear down the kind cluster and local registry"
	@echo ""

fresh: setup-fresh
setup-fresh:
	./scripts/setup-fresh-cluster.sh

five-agents:
	./scripts/run-5-agents.sh

openclaw: openclaw-deploy
openclaw-deploy:
	./scripts/deploy-openclaw.sh

openclaw-status:
	@echo "==> OpenClaw Pods (openclaw-system):"
	@kubectl --context kind-google-ax get pods -n openclaw-system -o wide
	@echo ""
	@echo "==> Telegram Bot Connectivity:"
	@curl -s https://api.telegram.org/botYOUR_TELEGRAM_BOT_TOKEN/getMe | python3 -m json.tool

openclaw-logs:
	kubectl --context kind-google-ax logs -f -n openclaw-system deployment/openclaw

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
