import os
import re
import yaml
import subprocess
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger("openclaw.ax_client")

class AXClient:
    """Client wrapper for interacting with Google AX and Agent Substrate CLI."""

    def __init__(
        self,
        ax_bin: str = "ax",
        kubectl_ate_bin: str = "kubectl-ate",
        egress_policy_path: Optional[str] = None,
        ax_server_url: Optional[str] = None
    ):
        self.ax_bin = ax_bin
        self.kubectl_ate_bin = kubectl_ate_bin
        self.egress_policy_path = egress_policy_path
        self.ax_server_url = ax_server_url

    def _get_env(self) -> Dict[str, str]:
        env = os.environ.copy()
        # Add bin directory to PATH if present
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        bin_dir = os.path.join(project_root, "bin")
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        
        # If AX_SERVER is explicitly configured, pass it
        if self.ax_server_url:
            env["AX_SERVER"] = self.ax_server_url
        elif "AX_SERVER" in os.environ:
            env["AX_SERVER"] = os.environ["AX_SERVER"]

        return env

    def _run_cmd(self, cmd: List[str], timeout: int = 40) -> subprocess.CompletedProcess:
        env = self._get_env()
        logger.debug("Executing command: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )

    def get_tasks(self) -> List[Dict[str, str]]:
        """Parses output of 'ax get tasks' into structured records."""
        try:
            res = self._run_cmd([self.ax_bin, "get", "tasks"], timeout=20)
            if res.returncode != 0:
                logger.error("Failed to run ax get tasks: %s", res.stderr)
                return []

            lines = res.stdout.strip().split("\n")
            if len(lines) <= 1:
                return []

            tasks = []
            for line in lines[1:]:
                cols = line.strip().split()
                if len(cols) >= 6:
                    tasks.append({
                        "name": cols[0],
                        "atespace": cols[1],
                        "phase": cols[2],
                        "actor": cols[3],
                        "worker_ip": cols[4],
                        "age": cols[5]
                    })
            return tasks
        except Exception as e:
            logger.error("Exception in get_tasks: %s", e)
            return []

    def get_task_spec(self, task_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves and parses full YAML specification of a task."""
        try:
            res = self._run_cmd([self.ax_bin, "get", "task", task_name], timeout=20)
            if res.returncode != 0:
                logger.error("Failed to get task spec for %s: %s", task_name, res.stderr)
                return None
            return yaml.safe_load(res.stdout)
        except Exception as e:
            logger.error("Exception getting task spec for %s: %s", task_name, e)
            return None

    def get_workspace_spec(self, ws_name: str) -> Optional[Dict[str, Any]]:
        """Retrieves and parses full YAML specification of a workspace."""
        try:
            res = self._run_cmd([self.ax_bin, "get", "workspace", ws_name], timeout=20)
            if res.returncode != 0:
                logger.error("Failed to get workspace spec for %s: %s", ws_name, res.stderr)
                return None
            return yaml.safe_load(res.stdout)
        except Exception as e:
            logger.error("Exception getting workspace spec for %s: %s", ws_name, e)
            return None

    def resume_task(self, task_name: str) -> bool:
        """Resumes a task in Google AX, scheduling an actor on Agent Substrate."""
        try:
            res = self._run_cmd([self.ax_bin, "resume", "task", task_name], timeout=30)
            if res.returncode == 0:
                logger.info("Successfully resumed task %s: %s", task_name, res.stdout.strip())
                return True
            else:
                logger.error("Error resuming task %s: %s", task_name, res.stderr.strip())
                return False
        except Exception as e:
            logger.error("Exception in resume_task %s: %s", task_name, e)
            return False

    def suspend_task(self, task_name: str) -> bool:
        """Suspends a task in Google AX, checkpointing state and halting compute."""
        try:
            res = self._run_cmd([self.ax_bin, "suspend", "task", task_name], timeout=30)
            if res.returncode == 0:
                logger.info("Successfully suspended task %s: %s", task_name, res.stdout.strip())
                return True
            else:
                logger.error("Error suspending task %s: %s", task_name, res.stderr.strip())
                return False
        except Exception as e:
            logger.error("Exception in suspend_task %s: %s", task_name, e)
            return False

    def ensure_egress_policy(self, actor_name: str) -> bool:
        """Applies Substrate egress policy for the actor to enable internet access."""
        if not self.egress_policy_path or not os.path.exists(self.egress_policy_path):
            logger.warning("Egress policy manifest path not found: %s", self.egress_policy_path)
            return False

        try:
            cmd = [
                self.kubectl_ate_bin,
                "create",
                "egress-policy",
                actor_name,
                "-a",
                "default",
                "-f",
                self.egress_policy_path
            ]
            res = self._run_cmd(cmd, timeout=15)
            # Egress policy may already exist; check for duplicate or success
            if res.returncode == 0 or "already exists" in res.stderr.lower():
                logger.info("Egress policy verified for actor %s", actor_name)
                return True
            logger.warning("Egress policy notice for %s: %s", actor_name, res.stderr.strip())
            return True
        except Exception as e:
            logger.warning("Exception configuring egress policy for %s: %s", actor_name, e)
            return False

    def ssh_exec(self, task_name: str, command: str, timeout: int = 60) -> subprocess.CompletedProcess:
        """Executes a command inside the running task sandbox via 'ax ssh'."""
        cmd = [self.ax_bin, "ssh", task_name, "--", "sh", "-c", command]
        return self._run_cmd(cmd, timeout=timeout)
