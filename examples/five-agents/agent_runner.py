#!/usr/bin/env python3
import sys, os, json, subprocess, urllib.request, socket, time

ROLE = os.getenv("AGENT_ROLE", "security")
API_KEY = os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL = os.getenv("MODEL_NAME", "nvidia/nemotron-3-super-120b-a12b")
WORKSPACE_DIR = os.getenv("WORKSPACE_DIR", "/workspace")
MCP_SCRIPT = os.path.join(WORKSPACE_DIR, "mcp_server.py")

class MCPClient:
    def __init__(self, p):
        self.proc = subprocess.Popen([sys.executable, p], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.msg_id = 0
    def call(self, method, params=None):
        self.msg_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.msg_id, "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line: raise RuntimeError("MCP server closed unexpectedly")
        return json.loads(line.strip())
    def close(self):
        try: self.proc.terminate(); self.proc.wait(timeout=2)
        except Exception: self.proc.kill()

def main():
    print(f"Starting Agent [{ROLE}] with Model [{MODEL}]")
    mcp = MCPClient(MCP_SCRIPT)
    mcp.call("initialize", {"protocolVersion": "2024-11-05"})
    mcp_tools = mcp.call("tools/list").get("result", {}).get("tools", [])
    openai_tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}} for t in mcp_tools]

    prompt_file = os.path.join(WORKSPACE_DIR, "PROMPT.txt")
    custom_query = None
    if os.path.exists(prompt_file):
        try:
            with open(prompt_file, "r") as fp:
                custom_query = fp.read().strip()
        except Exception:
            pass

    sys_prompt = f"You are the specialized {ROLE.upper()} Agent in Google AX sandbox. Use MCP tools to audit, then synthesize a complete Markdown report."
    if custom_query:
        print(f"[{ROLE}] Custom query: {custom_query}")
        user_prompt = f"Request: '{custom_query}'. If an external URL is specified, prioritize calling audit_web_target and verify_gvisor_isolation, then synthesize analysis."
    else:
        user_prompt = f"Perform complete {ROLE} audit on {WORKSPACE_DIR}. Invoke MCP tools, then synthesize analysis."

    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}]

    for _w in range(10):
        try:
            with socket.create_connection(("integrate.api.nvidia.com", 443), timeout=3): break
        except Exception: time.sleep(1)

    def call_llm(msgs, tools=None, max_tokens=4096):
        max_attempts = 5
        for att in range(max_attempts):
            try:
                payload = {"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": 0.2}
                if tools: payload["tools"] = tools
                req = urllib.request.Request(
                    f"{BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "Connection": "close"},
                    data=json.dumps(payload).encode("utf-8")
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]
            except Exception as e:
                if att == max_attempts - 1: raise
                backoff = 2 * (att + 1)
                print(f"[{ROLE}] LLM call attempt {att+1} error: {e}; retrying in {backoff}s...")
                time.sleep(backoff)

    max_turns = 4
    final_report = ""
    for turn in range(1, max_turns + 1):
        print(f"[{ROLE}] Turn {turn}/{max_turns}: Querying Nemotron...")
        resp = call_llm(messages, openai_tools)
        tcs = resp.get("tool_calls")
        if tcs:
            messages.append({"role": "assistant", "content": resp.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                print(f"  -> Tool Call: {name}({args})")
                out = mcp.call("tools/call", {"name": name, "arguments": args})
                content = out.get("result", {}).get("content", [{}])[0].get("text", "{}")
                print(f"  <- Tool Output: {content[:100]}...")
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": content})
        else:
            final_report = resp.get("content") or resp.get("reasoning_content") or ""
            break

    is_full = ("###" in final_report or "##" in final_report) and len(final_report.strip()) > 500 and not final_report.strip().startswith("We need to")
    if not is_full:
        print(f"[{ROLE}] Synthesizing complete formal executive report...")
        messages.append({
            "role": "user",
            "content": f"All diagnostic MCP tools have finished running. Synthesize the complete formal Executive {ROLE.capitalize()} Report in Markdown detailing:\n1. Executive Summary & Audit Scope\n2. Verified Technical Findings (detail tool outputs, certificates, headers)\n3. Risk Rating & Compliance Status\n4. Actionable Security Hardening Recommendations\nDo not include meta-commentary. Output the full markdown report."
        })
        s = call_llm(messages, max_tokens=4096)
        if s:
            c = s.get("content") or s.get("reasoning_content") or ""
            if c.strip(): final_report = c

    if not final_report.strip():
        findings = [m["content"] for m in messages if m.get("role") == "tool"]
        final_report = f"## Executive Summary\nCompleted {ROLE} evaluation on {custom_query or WORKSPACE_DIR}.\n\n## Findings\n" + "\n".join(f"- {f}" for f in findings)

    mcp.close()

    rpath = os.path.join(WORKSPACE_DIR, f"{ROLE}-report.md")
    with open(rpath, "w") as f:
        if not final_report.strip().startswith("#"):
            f.write(f"# Executive {ROLE.capitalize()} Report\n\n- **Agent Role:** `{ROLE}`\n- **LLM Engine:** `{MODEL}`\n- **Target:** `{WORKSPACE_DIR}`\n\n---\n\n")
        f.write(final_report.strip() + "\n")

    with open(os.path.join(WORKSPACE_DIR, "COMPLETED"), "w") as f:
        f.write(json.dumps({"agent": ROLE, "status": "COMPLETED", "report_path": rpath}) + "\n")

    print(f"[{ROLE}] Report written successfully: {rpath}")

if __name__ == "__main__":
    main()
