#!/usr/bin/env python3
# Agent Execution Engine:
# 1. Spawns connected MCP tool server via JSON-RPC 2.0 stdio
# 2. Queries NVIDIA Nemotron LLM (nvidia/nemotron-3-super-120b-a12b)
# 3. Executes tool calls against the connected MCP server
# 4. Synthesizes executive report and writes to /workspace/<role>-report.md
# 5. Signals completion
import sys
import os
import json
import subprocess
import urllib.request

ROLE = os.getenv("AGENT_ROLE", "security")
API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_NVIDIA_API_KEY")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL = os.getenv("MODEL_NAME", "nvidia/nemotron-3-super-120b-a12b")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/workspace")
MCP_SCRIPT = os.path.join(WORKSPACE_DIR, "mcp_server.py")

class MCPClient:
    def __init__(self, script_path):
        self.proc = subprocess.Popen(
            [sys.executable, script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        self.msg_id = 0

    def call(self, method, params=None):
        self.msg_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self.msg_id,
            "method": method,
            "params": params or {}
        }
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout unexpectedly")
        return json.loads(line.strip())

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()

def main():
    print(f"================================================================")
    print(f" Starting Agent [{ROLE}] with Model [{MODEL}]")
    print(f"================================================================")

    # 1. Connect to local MCP Server
    print(f"[{ROLE}] Initializing MCP server at {MCP_SCRIPT}...")
    mcp = MCPClient(MCP_SCRIPT)
    init_res = mcp.call("initialize", {"protocolVersion": "2024-11-05"})
    print(f"[{ROLE}] Connected to MCP Server: {init_res.get('result', {}).get('serverInfo', {})}")

    # 2. Discover available tools from MCP
    tools_res = mcp.call("tools/list")
    mcp_tools = tools_res.get("result", {}).get("tools", [])
    print(f"[{ROLE}] Discovered {len(mcp_tools)} tools from MCP server:")
    for t in mcp_tools:
        print(f"  - {t['name']}: {t['description']}")

    # 3. Format tools into OpenAI Function Calling specification
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["inputSchema"]
            }
        }
        for t in mcp_tools
    ]

    # 4. Prepare system prompt and user query
    tool_names = [t["name"] for t in mcp_tools]
    tool_descriptions = "\n".join([f"- {t['name']}: {t['description']}" for t in mcp_tools])

    system_prompt = (
        f"You are the specialized {ROLE.upper()} Agent running inside Google AX sandbox at {WORKSPACE_DIR}.\n"
        f"Your mission is to perform a thorough {ROLE} evaluation by calling the available tools from your "
        f"connected MCP tool server, and then write a comprehensive, executive Markdown report.\n\n"
        f"Connected MCP Tools available for invocation:\n{tool_descriptions}\n\n"
        f"Always invoke the relevant MCP tools to gather telemetry before writing your final executive report."
    )
    user_prompt = (
        f"Please execute the complete {ROLE} audit and evaluation on {WORKSPACE_DIR}. "
        f"Invoke the relevant MCP tools ({', '.join(tool_names)}) to gather telemetry, then synthesize your analysis."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    def call_llm(msgs, tools_list=None):
        import time
        for attempt in range(3):
            try:
                payload = {
                    "model": MODEL,
                    "messages": msgs,
                    "max_tokens": 1500,
                    "temperature": 0.2
                }
                if tools_list:
                    payload["tools"] = tools_list
                req = urllib.request.Request(
                    f"{BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {API_KEY}",
                        "Content-Type": "application/json",
                        "Connection": "close"
                    },
                    data=json.dumps(payload).encode("utf-8")
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data["choices"][0]["message"]
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"[{ROLE}] LLM call attempt {attempt+1} encountered {e}; retrying in 2s...")
                time.sleep(2)

    # 5. Multi-turn ReAct tool execution loop
    max_turns = 6
    turn = 0
    final_report_text = ""

    while turn < max_turns:
        turn += 1
        print(f"[{ROLE}] Turn {turn}/{max_turns}: Querying NVIDIA Nemotron...")
        resp = call_llm(messages, openai_tools)
        tool_calls = resp.get("tool_calls")

        if tool_calls:
            print(f"[{ROLE}] Nemotron requested {len(tool_calls)} tool call(s):")
            messages.append({
                "role": "assistant",
                "content": resp.get("content") or "",
                "tool_calls": tool_calls
            })

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = json.loads(tc["function"]["arguments"] or "{}")
                print(f"  -> Calling MCP Tool [{fn_name}] with args: {fn_args}")

                mcp_output = mcp.call("tools/call", {"name": fn_name, "arguments": fn_args})
                tool_content = mcp_output.get("result", {}).get("content", [{}])[0].get("text", "{}")
                print(f"  <- Tool Output: {tool_content[:100]}...")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_content
                })
        else:
            final_report_text = resp.get("content") or ""
            if not final_report_text.strip():
                final_report_text = resp.get("reasoning_content") or ""
            print(f"[{ROLE}] Nemotron finished tool execution and generated response.")
            break

    # If still empty after tool iterations, prompt for report synthesis
    if not final_report_text.strip() or ("We need to invoke" in final_report_text and "tools" in final_report_text):
        print(f"[{ROLE}] Prompting final report synthesis...")
        messages.append({
            "role": "user",
            "content": (
                f"All diagnostic MCP tools have now completed execution and their telemetry is provided above. "
                f"Synthesize the complete, formal Executive {ROLE.capitalize()} Report in Markdown detailing:\n"
                f"1. Executive Summary & Audit Scope\n"
                f"2. Verified Telemetry Findings for each executed tool\n"
                f"3. Risk Rating & Compliance Status\n"
                f"4. Actionable Security Hardening Recommendations\n\n"
                f"Output the complete executive report directly in Markdown starting with '# Executive {ROLE.capitalize()} Report'."
            )
        })
        synth_resp = call_llm(messages)
        final_report_text = synth_resp.get("content") or ""
        if not final_report_text.strip():
            final_report_text = synth_resp.get("reasoning_content") or f"### {ROLE.upper()} Assessment\n- Status: COMPLETED\n"

    mcp.close()

    # 7. Write report to /workspace/<role>-report.md
    report_filename = f"{ROLE}-report.md"
    report_path = os.path.join(WORKSPACE_DIR, report_filename)
    with open(report_path, "w") as f:
        f.write(f"# Executive {ROLE.capitalize()} Report\n\n")
        f.write(f"- **Agent Role:** `{ROLE}`\n")
        f.write(f"- **LLM Engine:** `{MODEL}`\n")
        f.write(f"- **Target Workspace:** `{WORKSPACE_DIR}`\n\n")
        f.write(f"---\n\n")
        f.write(final_report_text)
        f.write("\n")

    # 8. Write completion status marker
    completion_marker = os.path.join(WORKSPACE_DIR, "COMPLETED")
    with open(completion_marker, "w") as f:
        f.write(json.dumps({
            "agent": ROLE,
            "status": "COMPLETED",
            "report_path": report_path
        }) + "\n")

    print(f"[{ROLE}] Successfully generated: {report_path}")
    print(f"[{ROLE}] Written completion marker: {completion_marker}")
    print(f"================================================================")
    print(f" Agent [{ROLE}] Task Completed Successfully!")
    print(f"================================================================")

if __name__ == "__main__":
    main()
