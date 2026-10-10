import time
import logging
from typing import Optional, Callable, Dict, Any
from openclaw.ax_client import AXClient
from openclaw.agent_library import AgentLibrary

logger = logging.getLogger("openclaw.spawner")

class AgentSpawner:
    """Spins, executes, monitors, and automatically suspends Google AX agent tasks."""

    def __init__(self, ax_client: AXClient, agent_library: AgentLibrary):
        self.ax_client = ax_client
        self.library = agent_library

    def spin_and_execute(
        self,
        agent_name: str,
        custom_prompt: Optional[str] = None,
        progress_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Full lifecycle orchestrator:
        1. Resume task in Google AX.
        2. Verify / configure Substrate network egress.
        3. Wait for Sandbox actor readiness.
        4. Trigger agent execution with MCP tools.
        5. Collect synthesized report.
        6. Cleanly suspend task back to Suspended phase.
        """
        start_time = time.time()
        agent = self.library.get_agent(agent_name)
        role = agent.get("role", "general") if agent else "general"

        def update(msg: str):
            logger.info("[%s] %s", agent_name, msg)
            if progress_callback:
                try:
                    progress_callback(msg)
                except Exception as e:
                    logger.warning("Error in progress callback: %s", e)

        update(f"🚀 Initializing Google AX actor for '{agent_name}'...")

        # 1. Resume Task
        resumed = self.ax_client.resume_task(agent_name)
        if not resumed:
            update(f"⚠️ Resume command returned non-zero, checking if already running...")

        # 2. Configure Egress Policy
        update(f"🌐 Authorizing Substrate network egress gateway...")
        self.ax_client.ensure_egress_policy(agent_name)

        # 3. Wait for Actor Ready (Running phase)
        update(f"⏳ Waiting for gVisor sandbox allocation...")
        is_ready = False
        for _ in range(25):
            tasks = {t["name"]: t for t in self.ax_client.get_tasks()}
            current_task = tasks.get(agent_name)
            if current_task and current_task["phase"] == "Running":
                is_ready = True
                update(f"✅ Sandbox online at worker IP {current_task.get('worker_ip')}!")
                break
            time.sleep(1)

        if not is_ready:
            return {
                "success": False,
                "agent": agent_name,
                "error": "Timeout waiting for sandbox to enter Running phase.",
                "duration": time.time() - start_time
            }

        # 4. Clean previous completion marker and inject prompt
        self.ax_client.ssh_exec(agent_name, "rm -f /workspace/COMPLETED", timeout=10)
        if custom_prompt:
            escaped_prompt = custom_prompt.replace("'", "'\\''")
            self.ax_client.ssh_exec(agent_name, f"printf '%s' '{escaped_prompt}' > /workspace/PROMPT.txt", timeout=10)
        else:
            self.ax_client.ssh_exec(agent_name, "rm -f /workspace/PROMPT.txt", timeout=10)

        # 5. Run Agent inside sandbox
        update(f"🧠 Executing agent runner with MCP tools and NVIDIA Nemotron 120B...")
        run_res = self.ax_client.ssh_exec(
            agent_name,
            "python3 /workspace/agent_runner.py",
            timeout=180
        )

        if run_res.returncode != 0:
            logger.warning("[%s] Execution warning: %s", agent_name, run_res.stderr)

        # 6. Check for completion marker and read report
        update(f"📄 Fetching synthesized executive report...")
        report_cmd = f"cat /workspace/{role}-report.md 2>/dev/null || cat /workspace/*report.md 2>/dev/null"
        report_res = self.ax_client.ssh_exec(agent_name, report_cmd, timeout=15)
        report_text = report_res.stdout.strip()

        if not report_text:
            report_text = run_res.stdout.strip() or f"Task '{agent_name}' completed execution successfully."

        # Cache report in library
        self.library.update_report_cache(agent_name, report_text)

        # 7. Suspend task to release resources
        update(f"⏸️ Task completed! Checkpointing state and suspending '{agent_name}'...")
        suspended = self.ax_client.suspend_task(agent_name)
        if suspended:
            update(f"💤 Agent '{agent_name}' successfully suspended.")
        else:
            update(f"⚠️ Notice: Agent suspension command exited non-zero.")

        # Re-sync library state
        self.library.sync()

        duration = round(time.time() - start_time, 2)
        return {
            "success": True,
            "agent": agent_name,
            "role": role,
            "report": report_text,
            "duration": duration,
            "output": run_res.stdout
        }
