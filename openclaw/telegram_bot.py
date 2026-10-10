import json
import time
import logging
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List
from openclaw.agent_library import AgentLibrary
from openclaw.agent_spawner import AgentSpawner
from openclaw.ax_client import AXClient

logger = logging.getLogger("openclaw.telegram")

class TelegramBot:
    """Telegram Bot interface for OpenClaw orchestrator on Google AX."""

    def __init__(
        self,
        bot_token: str,
        library: AgentLibrary,
        spawner: AgentSpawner,
        ax_client: AXClient
    ):
        self.bot_token = bot_token
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.library = library
        self.spawner = spawner
        self.ax_client = ax_client
        self.last_update_id = 0
        self.running = False

    def _api_call(self, method: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.api_url}/{method}"
        headers = {"Content-Type": "application/json", "Connection": "close"}
        encoded_data = json.dumps(data).encode("utf-8") if data else None

        req = urllib.request.Request(url, data=encoded_data, headers=headers)
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Sends a message to the specified Telegram chat."""
        # Telegram max message length is 4096; truncate or split safely
        if len(text) > 4000:
            text = text[:3990] + "\n\n<i>... [output truncated]</i>"

        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            res = self._api_call("sendMessage", payload)
            if res.get("ok"):
                return res.get("result")
            else:
                # If HTML parsing fails, fallback to plain text
                payload.pop("parse_mode", None)
                res = self._api_call("sendMessage", payload)
                return res.get("result")
        except Exception as e:
            logger.error("Error sending message to chat %s: %s", chat_id, e)
            try:
                # Fallback to plain text
                payload.pop("parse_mode", None)
                self._api_call("sendMessage", payload)
            except Exception:
                pass
            return None

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Edits an existing message in-place for live progress updates."""
        if len(text) > 4000:
            text = text[:3990] + "\n\n<i>... [truncated]</i>"

        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            res = self._api_call("editMessageText", payload)
            return bool(res.get("ok"))
        except Exception as e:
            logger.debug("Could not edit message %s: %s", message_id, e)
            return False

    def send_action(self, chat_id: int, action: str = "typing"):
        try:
            self._api_call("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            pass

    def answer_callback(self, callback_id: str, text: Optional[str] = None):
        try:
            payload = {"callback_query_id": callback_id}
            if text:
                payload["text"] = text
            self._api_call("answerCallbackQuery", payload)
        except Exception as e:
            logger.debug("Error answering callback %s: %s", callback_id, e)

    def handle_updates(self):
        """Polls for new Telegram updates and dispatches them."""
        try:
            payload = {
                "offset": self.last_update_id + 1,
                "timeout": 25,
                "allowed_updates": ["message", "callback_query"]
            }
            res = self._api_call("getUpdates", payload)
            if not res.get("ok"):
                return

            updates = res.get("result", [])
            for u in updates:
                self.last_update_id = u["update_id"]
                if "message" in u:
                    self._on_message(u["message"])
                elif "callback_query" in u:
                    self._on_callback(u["callback_query"])
        except urllib.error.URLError as e:
            logger.warning("Telegram network poll notice: %s", e)
            time.sleep(2)
        except Exception as e:
            logger.error("Unexpected error in Telegram polling: %s", e)
            time.sleep(1)

    def _on_message(self, msg: Dict[str, Any]):
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        text = msg.get("text", "").strip()

        if not chat_id or not text:
            return

        user_name = msg.get("from", {}).get("first_name", "User")
        logger.info("Message from %s (%s): %s", user_name, chat_id, text)

        # Command Dispatch
        if text.startswith("/start"):
            self._cmd_start(chat_id, user_name)
        elif text.startswith("/help"):
            self._cmd_help(chat_id)
        elif text.startswith("/library") or text.startswith("/agents"):
            self._cmd_library(chat_id)
        elif text.startswith("/tasks"):
            self._cmd_tasks(chat_id)
        elif text.startswith("/refresh"):
            self._cmd_refresh(chat_id)
        elif text.startswith("/spin") or text.startswith("/run"):
            parts = text.split(maxsplit=2)
            agent_name = parts[1] if len(parts) > 1 else None
            custom_prompt = parts[2] if len(parts) > 2 else None
            if not agent_name:
                self.send_message(chat_id, "⚠️ Usage: <code>/spin &lt;agent_name&gt; [prompt]</code>\nExample: <code>/spin security-agent</code>")
            else:
                self._execute_agent(chat_id, agent_name, custom_prompt)
        elif text.startswith("/suspend"):
            parts = text.split(maxsplit=1)
            agent_name = parts[1] if len(parts) > 1 else None
            if not agent_name:
                self.send_message(chat_id, "⚠️ Usage: <code>/suspend &lt;agent_name&gt;</code>")
            else:
                self._cmd_suspend(chat_id, agent_name)
        elif text.startswith("/report"):
            parts = text.split(maxsplit=1)
            agent_name = parts[1] if len(parts) > 1 else None
            if not agent_name:
                self.send_message(chat_id, "⚠️ Usage: <code>/report &lt;agent_name&gt;</code>")
            else:
                self._cmd_report(chat_id, agent_name)
        elif text.startswith("/ssh"):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                self.send_message(chat_id, "⚠️ Usage: <code>/ssh &lt;agent_name&gt; &lt;command&gt;</code>")
            else:
                self._cmd_ssh(chat_id, parts[1], parts[2])
        else:
            # Free-form Natural Language Query
            self._handle_natural_language(chat_id, text)

    def _on_callback(self, cq: Dict[str, Any]):
        cq_id = cq.get("id")
        msg = cq.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        data = cq.get("data", "")

        self.answer_callback(cq_id)

        if not chat_id:
            return

        if data == "menu:library":
            self._cmd_library(chat_id)
        elif data == "menu:tasks":
            self._cmd_tasks(chat_id)
        elif data == "menu:refresh":
            self._cmd_refresh(chat_id)
        elif data == "menu:help":
            self._cmd_help(chat_id)
        elif data.startswith("spin:"):
            agent_name = data.split(":", 1)[1]
            self._execute_agent(chat_id, agent_name)
        elif data.startswith("report:"):
            agent_name = data.split(":", 1)[1]
            self._cmd_report(chat_id, agent_name)
        elif data.startswith("suspend:"):
            agent_name = data.split(":", 1)[1]
            self._cmd_suspend(chat_id, agent_name)

    def _cmd_start(self, chat_id: int, user_name: str):
        agents = self.library.list_agents()
        text = (
            f"🦅 <b>Welcome to OpenClaw Orchestrator, {user_name}!</b>\n\n"
            f"OpenClaw is your autonomous bridge connecting <b>Telegram</b> to <b>Google AX</b> and <b>Agent Substrate</b>.\n\n"
            f"📊 <b>Active Catalog:</b> <code>{len(agents)}</code> dynamic agents registered\n"
            f"⚙️ <b>LLM Engine:</b> <code>nvidia/nemotron-3-super-120b-a12b</code>\n"
            f"🔒 <b>Isolation:</b> gVisor Sandboxes via Substrate WorkerPool\n\n"
            f"You can send commands, click buttons below, or simply talk in <i>natural language</i> to spin up any agent automatically!"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📋 Agent Library", "callback_data": "menu:library"},
                    {"text": "⚡ Cluster Tasks", "callback_data": "menu:tasks"}
                ],
                [
                    {"text": "🛡️ Security", "callback_data": "spin:security-agent"},
                    {"text": "🧹 Linter", "callback_data": "spin:linter-agent"},
                    {"text": "⚡ Perf", "callback_data": "spin:perf-agent"}
                ],
                [
                    {"text": "📚 Docs", "callback_data": "spin:docs-agent"},
                    {"text": "🩺 SRE Health", "callback_data": "spin:sre-agent"}
                ],
                [
                    {"text": "🔄 Refresh Catalog", "callback_data": "menu:refresh"},
                    {"text": "❓ Help & Commands", "callback_data": "menu:help"}
                ]
            ]
        }
        self.send_message(chat_id, text, reply_markup=keyboard)

    def _cmd_help(self, chat_id: int):
        text = (
            "📖 <b>OpenClaw Command Reference</b>\n\n"
            "• <code>/start</code> - Main dashboard and quick actions\n"
            "• <code>/library</code> or <code>/agents</code> - Dynamic Agent Library & MCP tools\n"
            "• <code>/tasks</code> - Live Google AX cluster tasks & phases\n"
            "• <code>/spin &lt;agent&gt; [prompt]</code> - Spin agent, run MCP tools, synthesize report, and suspend\n"
            "• <code>/suspend &lt;agent&gt;</code> - Suspend an active agent task\n"
            "• <code>/report &lt;agent&gt;</code> - View latest generated report\n"
            "• <code>/ssh &lt;agent&gt; &lt;cmd&gt;</code> - Execute shell command inside sandbox\n"
            "• <code>/refresh</code> - Force re-sync of Agent Library from cluster\n\n"
            "💡 <i>Tip: You can also ask directly in plain English (e.g. 'Can you check code complexity?' or 'Audit CVE vulnerabilities'). OpenClaw will automatically route to the right agent!</i>"
        )
        self.send_message(chat_id, text)

    def _cmd_library(self, chat_id: int):
        agents = self.library.list_agents()
        if not agents:
            self.send_message(chat_id, "⚠️ No agents found in library. Run <code>/refresh</code> to sync with AX.")
            return

        lines = [f"📚 <b>Dynamic Agent Library ({len(agents)} Registered)</b>\n"]
        inline_buttons = []

        for a in agents:
            name = a["name"]
            phase = a.get("phase", "Unknown")
            phase_icon = "🟢" if phase == "Running" else "💤"
            title = a.get("title", name)
            desc = a.get("description", "")
            tools = [t["name"] for t in a.get("tools", [])]
            tools_str = ", ".join(f"<code>{t}</code>" for t in tools) if tools else "<i>none</i>"

            lines.append(
                f"{phase_icon} <b>{title}</b> (<code>{name}</code>)\n"
                f"• <b>Status:</b> <code>{phase}</code>\n"
                f"• <b>Tools:</b> {tools_str}\n"
                f"• <i>{desc}</i>\n"
            )

            inline_buttons.append([
                {"text": f"🚀 Spin {name}", "callback_data": f"spin:{name}"},
                {"text": f"📄 Report", "callback_data": f"report:{name}"}
            ])

        keyboard = {"inline_keyboard": inline_buttons}
        self.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)

    def _cmd_tasks(self, chat_id: int):
        tasks = self.ax_client.get_tasks()
        if not tasks:
            self.send_message(chat_id, "⚠️ No AX tasks returned from cluster.")
            return

        lines = ["⚡ <b>Google AX Live Tasks:</b>\n<pre>"]
        lines.append(f"{'NAME':<17} {'PHASE':<11} {'WORKER-IP':<15} {'AGE'}")
        lines.append("-" * 50)
        for t in tasks:
            lines.append(f"{t['name']:<17} {t['phase']:<11} {t.get('worker_ip', '<none>'):<15} {t.get('age', '-')}")
        lines.append("</pre>")

        keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 Refresh", "callback_data": "menu:tasks"},
                 {"text": "📋 Agent Library", "callback_data": "menu:library"}]
            ]
        }
        self.send_message(chat_id, "\n".join(lines), reply_markup=keyboard)

    def _cmd_refresh(self, chat_id: int):
        changes = self.library.sync()
        added = ", ".join(changes["added"]) or "none"
        updated = ", ".join(changes["updated"]) or "none"
        removed = ", ".join(changes["removed"]) or "none"

        text = (
            "🔄 <b>Agent Library Synchronization Complete</b>\n\n"
            f"• <b>Newly Registered:</b> {added}\n"
            f"• <b>Updated:</b> {updated}\n"
            f"• <b>Deregistered:</b> {removed}\n"
            f"• <b>Total Active:</b> {len(self.library.list_agents())}"
        )
        self.send_message(chat_id, text)

    def _cmd_suspend(self, chat_id: int, agent_name: str):
        self.send_message(chat_id, f"⏸️ Suspending task <code>{agent_name}</code>...")
        res = self.ax_client.suspend_task(agent_name)
        if res:
            self.library.sync()
            self.send_message(chat_id, f"💤 Agent <code>{agent_name}</code> is now <b>Suspended</b>.")
        else:
            self.send_message(chat_id, f"❌ Failed to suspend agent <code>{agent_name}</code>.")

    def _cmd_report(self, chat_id: int, agent_name: str):
        agent = self.library.get_agent(agent_name)
        if agent and agent.get("last_report"):
            report = agent["last_report"]
            self.send_message(chat_id, f"📄 <b>Latest Report for {agent_name}:</b>\n\n<pre>{report}</pre>")
        else:
            self.send_message(chat_id, f"⚠️ No cached report for <code>{agent_name}</code>. Try spinning it first with <code>/spin {agent_name}</code>.")

    def _cmd_ssh(self, chat_id: int, agent_name: str, cmd: str):
        self.send_message(chat_id, f"💻 Executing inside <code>{agent_name}</code>: <code>{cmd}</code>...")
        res = self.ax_client.ssh_exec(agent_name, cmd)
        out = (res.stdout or res.stderr).strip() or "[no output]"
        self.send_message(chat_id, f"<b>Output:</b>\n<pre>{out}</pre>")

    def _execute_agent(self, chat_id: int, agent_name: str, prompt: Optional[str] = None):
        agent = self.library.get_agent(agent_name)
        if not agent:
            self.send_message(chat_id, f"❌ Agent <code>{agent_name}</code> not found in library. Use <code>/library</code> to see available agents.")
            return

        status_msg = self.send_message(
            chat_id,
            f"🚀 <b>Spinning Agent:</b> <code>{agent_name}</code>\n"
            f"• <b>Role:</b> {agent.get('title', agent_name)}\n"
            f"• <b>Status:</b> Preparing Google AX sandbox..."
        )
        msg_id = status_msg.get("message_id") if status_msg else None

        def progress_cb(step_text: str):
            if msg_id:
                self.edit_message(
                    chat_id,
                    msg_id,
                    f"🚀 <b>Spinning Agent:</b> <code>{agent_name}</code>\n"
                    f"• <b>Status:</b> {step_text}"
                )

        self.send_action(chat_id, "typing")

        # Run in worker or execute directly
        result = self.spawner.spin_and_execute(
            agent_name=agent_name,
            custom_prompt=prompt,
            progress_callback=progress_cb
        )

        if result.get("success"):
            report = result.get("report", "")
            duration = result.get("duration", 0)

            final_text = (
                f"✅ <b>Agent Execution Completed!</b>\n\n"
                f"• <b>Agent:</b> <code>{agent_name}</code>\n"
                f"• <b>Execution Time:</b> <code>{duration}s</code>\n"
                f"• <b>Cluster Phase:</b> 💤 <code>Suspended</code> (state preserved)\n\n"
                f"📊 <b>Executive Report:</b>\n"
                f"<pre>{report}</pre>"
            )

            keyboard = {
                "inline_keyboard": [
                    [{"text": "🔄 Run Again", "callback_data": f"spin:{agent_name}"},
                     {"text": "📋 Agent Library", "callback_data": "menu:library"}]
                ]
            }

            if msg_id:
                self.edit_message(chat_id, msg_id, final_text, reply_markup=keyboard)
            else:
                self.send_message(chat_id, final_text, reply_markup=keyboard)
        else:
            err = result.get("error", "Unknown error")
            err_text = f"❌ <b>Execution Failed for {agent_name}</b>\n\nError: <code>{err}</code>"
            if msg_id:
                self.edit_message(chat_id, msg_id, err_text)
            else:
                self.send_message(chat_id, err_text)

    def _handle_natural_language(self, chat_id: int, query: str):
        matched_agent = self.library.match_agent(query)
        if matched_agent:
            agent = self.library.get_agent(matched_agent)
            title = agent.get("title", matched_agent) if agent else matched_agent
            self.send_message(
                chat_id,
                f"🤖 <b>Intent Recognized!</b>\n"
                f"Routing to: <b>{title}</b> (<code>{matched_agent}</code>)\n"
                f"Spinning Google AX actor now..."
            )
            self._execute_agent(chat_id, matched_agent, prompt=query)
        else:
            self.send_message(
                chat_id,
                "🤔 I could not determine which agent to spin for your request.\n"
                "Please choose an agent from <code>/library</code> or ask about security, linting, performance, documentation, or SRE health!"
            )
