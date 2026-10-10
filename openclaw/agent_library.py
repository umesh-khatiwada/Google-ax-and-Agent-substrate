import os
import json
import time
import logging
import urllib.request
from typing import Dict, List, Optional, Any
from openclaw.ax_client import AXClient

logger = logging.getLogger("openclaw.agent_library")

KNOWN_ROLES = {
    "security": {
        "title": "Security Auditor Agent",
        "description": "Audits file permissions, scans for malware signatures, checks network sockets, lists processes, and checks CVE vulnerability database.",
        "tools": [
            {"name": "audit_permissions", "description": "Audits sensitive file permissions and suid flags across workspace"},
            {"name": "scan_for_malware", "description": "Scans workspace files for known malware signatures and suspicious scripts"},
            {"name": "check_network", "description": "Inspects sandbox network interfaces, listening sockets, and egress routing"},
            {"name": "list_processes", "description": "Enumerates all running processes inside the sandbox actor"},
            {"name": "get_system_info", "description": "Retrieves operating system details, kernel release, and environment"},
            {"name": "verify_gvisor_isolation", "description": "Verifies Google gVisor kernel sandboxing and Substrate isolation boundaries"},
            {"name": "scan_cve_database", "description": "Scans package and kernel CVE database for vulnerabilities"}
        ]
    },
    "linter": {
        "title": "Code Quality & Linter Agent",
        "description": "Performs static syntax analysis, flake8/pep8 checks, and computes cyclomatic code complexity.",
        "tools": [
            {"name": "check_python_syntax", "description": "Scans Python source files for AST syntax errors and formatting"},
            {"name": "analyze_complexity", "description": "Computes cyclomatic complexity across modules and functions"}
        ]
    },
    "perf": {
        "title": "Performance Profiler Agent",
        "description": "Samples runtime memory allocations, benchmarks CPU compute throughput, and detects bottlenecks.",
        "tools": [
            {"name": "sample_memory_profile", "description": "Profiles current virtual memory, RSS, and heap usage"},
            {"name": "benchmark_cpu", "description": "Benchmarks CPU floating point throughput and latency"}
        ]
    },
    "docs": {
        "title": "API & Docs Validator Agent",
        "description": "Generates OpenAPI 3.1 specifications and validates internal/external markdown documentation links.",
        "tools": [
            {"name": "generate_openapi_spec", "description": "Generates OpenAPI specification from endpoints and models"},
            {"name": "validate_markdown_links", "description": "Validates local and external markdown links in docs"}
        ]
    },
    "sre": {
        "title": "Site Reliability & Health Agent",
        "description": "Probes system readiness, checks process/service health, and evaluates cluster resilience metrics.",
        "tools": [
            {"name": "probe_readiness", "description": "Probes uptime, load averages, and port availability"},
            {"name": "evaluate_resilience", "description": "Evaluates error recovery rate and crash-loop resilience"}
        ]
    }
}

class AgentLibrary:
    """Maintains a dynamic registry of all Google AX / Substrate actors and tasks."""

    def __init__(
        self,
        ax_client: AXClient,
        library_file: str,
        openai_base_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.ax_client = ax_client
        self.library_file = library_file
        self.openai_base_url = openai_base_url
        self.openai_api_key = openai_api_key
        self.model_name = model_name
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.load_from_disk()

    def load_from_disk(self):
        """Loads cached agent library state from disk if available."""
        if os.path.exists(self.library_file):
            try:
                with open(self.library_file, "r") as f:
                    self.agents = json.load(f)
                logger.info("Loaded %d agents from library cache: %s", len(self.agents), self.library_file)
            except Exception as e:
                logger.warning("Could not read agent library cache: %s", e)

    def save_to_disk(self):
        """Persists current agent library catalog to disk."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.library_file)), exist_ok=True)
            with open(self.library_file, "w") as f:
                json.dump(self.agents, f, indent=2)
            logger.debug("Persisted %d agents to %s", len(self.agents), self.library_file)
        except Exception as e:
            logger.error("Failed to persist agent library: %s", e)

    def sync(self) -> Dict[str, Any]:
        """
        Polls Google AX cluster for all tasks/actors.
        Registers new tasks, updates existing statuses, and prunes removed tasks.
        """
        cluster_tasks = self.ax_client.get_tasks()
        active_task_names = {t["name"] for t in cluster_tasks}
        changes = {"added": [], "updated": [], "removed": []}

        # 1. Update and Register
        for t in cluster_tasks:
            name = t["name"]
            phase = t["phase"]
            atespace = t["atespace"]
            worker_ip = t.get("worker_ip", "")
            actor = t.get("actor", name)

            if name not in self.agents:
                # Discovered a brand-new task/actor!
                agent_info = self._inspect_and_register_task(name, atespace, phase, actor, worker_ip)
                self.agents[name] = agent_info
                changes["added"].append(name)
                logger.info("[Agent Library] 🌟 Newly registered agent: %s (Phase: %s, Role: %s)",
                            name, phase, agent_info.get("role"))
            else:
                # Update existing task
                agent = self.agents[name]
                old_phase = agent.get("phase")
                agent["phase"] = phase
                agent["worker_ip"] = worker_ip
                agent["last_synced"] = time.time()
                if old_phase != phase:
                    changes["updated"].append(f"{name} ({old_phase} -> {phase})")
                    logger.info("[Agent Library] 🔄 Updated agent %s phase: %s -> %s", name, old_phase, phase)

        # 2. Prune removed tasks
        removed = [name for name in list(self.agents.keys()) if name not in active_task_names]
        for name in removed:
            del self.agents[name]
            changes["removed"].append(name)
            logger.info("[Agent Library] 🗑️ Deregistered removed task: %s", name)

        if changes["added"] or changes["updated"] or changes["removed"]:
            self.save_to_disk()

        return changes

    def _inspect_and_register_task(
        self,
        name: str,
        atespace: str,
        phase: str,
        actor: str,
        worker_ip: str
    ) -> Dict[str, Any]:
        """Inspects task spec and workspaces to extract metadata, role, and tools."""
        spec = self.ax_client.get_task_spec(name) or {}
        task_spec = spec.get("spec", {})
        env_vars = {e.get("name"): e.get("value") for e in task_spec.get("env", []) if isinstance(e, dict)}
        
        role = env_vars.get("AGENT_ROLE", "")
        if not role:
            # Fallback deduction from name prefix
            for r in KNOWN_ROLES.keys():
                if r in name:
                    role = r
                    break

        workspaces = [w.get("name") for w in task_spec.get("workspaces", []) if isinstance(w, dict)]
        model = env_vars.get("MODEL_NAME", self.model_name or "default")
        command = task_spec.get("command", [])

        # Role metadata resolution
        if role in KNOWN_ROLES:
            title = KNOWN_ROLES[role]["title"]
            desc = KNOWN_ROLES[role]["description"]
            tools = KNOWN_ROLES[role]["tools"]
        else:
            title = f"{name.capitalize()} Agent"
            desc = f"Autonomous Google AX Task Actor running command: {' '.join(command) if command else 'default'}"
            tools = []

        return {
            "name": name,
            "atespace": atespace,
            "actor": actor,
            "phase": phase,
            "worker_ip": worker_ip,
            "role": role or "general",
            "title": title,
            "description": desc,
            "tools": tools,
            "model": model,
            "command": command,
            "workspaces": workspaces,
            "registered_at": time.time(),
            "last_synced": time.time(),
            "last_report": None
        }

    def get_agent(self, name: str) -> Optional[Dict[str, Any]]:
        return self.agents.get(name)

    def list_agents(self) -> List[Dict[str, Any]]:
        return list(self.agents.values())

    def update_report_cache(self, name: str, report_text: str):
        if name in self.agents:
            self.agents[name]["last_report"] = report_text
            self.save_to_disk()

    def match_agent(self, user_query: str) -> Optional[str]:
        """
        Intelligently resolves which agent from the library is best suited to handle a user request.
        1. Exact or partial name match.
        2. Keyword and tool mapping.
        3. LLM semantic routing fallback via NVIDIA Nemotron.
        """
        query = user_query.lower().strip()

        # 1. Exact name match
        for name in self.agents.keys():
            if name.lower() in query:
                return name

        # 2. Keyword heuristic mapping
        keyword_map = {
            "security": ["sec", "cve", "vuln", "permission", "sudo", "audit", "exploit", "safety"],
            "linter": ["lint", "syntax", "pep8", "flake8", "complexity", "clean code", "ast"],
            "perf": ["perf", "memory", "ram", "cpu", "benchmark", "bottleneck", "profile", "speed"],
            "docs": ["doc", "docs", "documentation", "openapi", "swagger", "spec", "markdown", "link"],
            "sre": ["sre", "health", "readiness", "resilience", "probe", "uptime", "reliability", "crash"]
        }

        for role, kws in keyword_map.items():
            for kw in kws:
                if kw in query:
                    for name, agent in self.agents.items():
                        if agent.get("role") == role:
                            return name

        # 3. LLM semantic classification via Nemotron
        if self.openai_base_url and self.openai_api_key and self.agents:
            try:
                candidate_summary = "\n".join([
                    f"- {name}: {a.get('title')} ({a.get('description')})"
                    for name, a in self.agents.items()
                ])
                prompt = (
                    f"You are the OpenClaw router. Given the available agents:\n{candidate_summary}\n\n"
                    f"User request: '{user_query}'\n\n"
                    f"Which single agent name from the list above should handle this request? "
                    f"Return ONLY the exact agent name, or 'none' if no agent is suitable."
                )

                payload = {
                    "model": self.model_name or "nvidia/nemotron-3-super-120b-a12b",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 64,
                    "temperature": 0.1
                }

                req = urllib.request.Request(
                    f"{self.openai_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json",
                        "Connection": "close"
                    },
                    data=json.dumps(payload).encode("utf-8")
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    ans = data["choices"][0]["message"].get("content", "").strip().lower()
                    for name in self.agents.keys():
                        if name.lower() in ans:
                            return name
            except Exception as e:
                logger.warning("LLM router fallback encountered error: %s", e)

        # Default fallback to first active agent or security-agent
        if "security-agent" in self.agents:
            return "security-agent"
        if self.agents:
            return next(iter(self.agents.keys()))
        return None
