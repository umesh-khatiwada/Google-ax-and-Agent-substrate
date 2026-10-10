#!/usr/bin/env python3
import os
import yaml

with open("examples/five-agents/mcp_server.py", "r") as f:
    mcp_code = f.read()

with open("examples/five-agents/agent_runner.py", "r") as f:
    runner_code = f.read()

roles = [
    ("security-agent", "security-workspace", "security", "Security Auditor Agent"),
    ("linter-agent", "linter-workspace", "linter", "Code Quality & Linter Agent"),
    ("perf-agent", "perf-workspace", "perf", "Performance & Resource Agent"),
    ("docs-agent", "docs-workspace", "docs", "API & Documentation Agent"),
    ("sre-agent", "sre-workspace", "sre", "Site Reliability & Health Agent"),
]

docs = []
for task_name, ws_name, role, desc in roles:
    ws_doc = {
        "apiVersion": "ax.io/v1alpha1",
        "kind": "Workspace",
        "metadata": {
            "name": ws_name,
            "atespace": "default"
        },
        "spec": {
            "files": [
                {
                    "path": "mcp_server.py",
                    "content": mcp_code
                },
                {
                    "path": "agent_runner.py",
                    "content": runner_code
                }
            ],
            "mcp": {
                "servers": [
                    {
                        "name": f"{role}-tools",
                        "command": "python3",
                        "args": ["/workspace/mcp_server.py"]
                    }
                ]
            }
        }
    }
    docs.append(ws_doc)

    task_doc = {
        "apiVersion": "ax.io/v1alpha1",
        "kind": "Task",
        "metadata": {
            "name": task_name,
            "atespace": "default"
        },
        "spec": {
            "image": "localhost:5001/ax/ax-task-runner@sha256:e4b09ffdb560190d6001dca2310e9d8cd3aec16a193c90526dd7921361e1a9ba",
            "env": [
                {"name": "OPENAI_BASE_URL", "value": "https://integrate.api.nvidia.com/v1"},
                {"name": "OPENAI_API_KEY", "value": "YOUR_NVIDIA_API_KEY"},
                {"name": "MODEL_NAME", "value": "nvidia/nemotron-3-super-120b-a12b"},
                {"name": "AGENT_ROLE", "value": role}
            ],
            "workspaces": [
                {"name": ws_name, "path": "/workspace"}
            ],
            "command": ["python3", "/workspace/agent_runner.py"],
            "debug": True
        }
    }
    docs.append(task_doc)

with open("examples/five-agents/manifests.yaml", "w") as f:
    yaml.dump_all(docs, f, sort_keys=False, default_flow_style=False)

print("Generated examples/five-agents/manifests.yaml successfully.")
