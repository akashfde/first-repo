#!/usr/bin/env python3
"""
selfHeal
o9_claude_connection.py
o9 Self Heal Agent — Connection layer between Claude CLI and o9 MCP Server.git
=======================
Connection layer between Claude CLI and the o9 MCP Server.

  No ANTHROPIC_API_KEY required — uses the Claude Code CLI login (OAuth).

Architecture
------------
  claude -p (print mode) does NOT load project-level .mcp.json MCP servers,
  so the connection is split into two layers:

    Layer 1 — o9 data:    Python → o9 MCP Server (stdio JSON-RPC via mcp package)
    Layer 2 — reasoning:  Python → claude -p subprocess (Claude Code CLI login)

  call_claude_o9(prompt) does both in sequence:
    1. Optionally fetches live o9 data via the MCP server
    2. Calls claude -p with that context for reasoning

Public API
----------
  call_o9_tool(tool, args)     -> dict   Call an o9 MCP tool directly
  call_claude_o9(prompt)       -> str    Reason with Claude (o9 context optional)
  verify_connection()          -> dict   Confirm both layers are reachable
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ── Configuration ──────────────────────────────────────────────────────────────

# o9 MCP server entry point (installed by o9-platform-mcp-0.6.0-win-setup)
O9_SERVER = Path(r"C:\tools\o9-mcp\node_modules\o9-platform-mcp\dist\index.js")

# Project directory — used as cwd for claude -p so it inherits project context
PROJECT_DIR = Path(__file__).parent


# ── Layer 1: o9 MCP server (direct stdio JSON-RPC) ────────────────────────────

async def _call_o9_tool_async(tool_name: str, arguments: dict) -> dict:
    """Internal async: call one o9 MCP tool via stdio transport."""
    server_params = StdioServerParameters(
        command="node",
        args=[str(O9_SERVER)],
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            # result.content is a list of content blocks; extract text
            texts = [
                block.text
                for block in result.content
                if hasattr(block, "text")
            ]
            return {"tool": tool_name, "result": "\n".join(texts)}


def call_o9_tool(tool_name: str, arguments: dict | None = None) -> dict:
    """
    Call an o9 MCP tool directly (Python → o9 MCP server, no Claude involved).

    Credentials are read from %USERPROFILE%\\.o9-mcp\\config.json automatically
    by the o9 MCP server process.

    Parameters
    ----------
    tool_name  : str   e.g. "o9_list_profiles", "o9_execute_query", "o9_request"
    arguments  : dict  Tool arguments (default: empty dict)

    Returns
    -------
    dict with keys "tool" and "result" (text from the tool).

    Raises
    ------
    FileNotFoundError  if the o9 MCP server binary is missing.
    RuntimeError       on MCP protocol errors.
    """
    if not O9_SERVER.exists():
        raise FileNotFoundError(
            f"o9 MCP server not found: {O9_SERVER}\n"
            "Run o9-platform-mcp-0.6.0-win-setup to install it."
        )
    return asyncio.run(_call_o9_tool_async(tool_name, arguments or {}))


# ── Layer 2: Claude CLI (claude -p, no API key) ───────────────────────────────

def call_claude_p(prompt: str, *, timeout: int = 120) -> str:
    """
    Call `claude -p` (Claude Code CLI print mode).

    No ANTHROPIC_API_KEY needed — uses the user's Claude Code OAuth session.

    Parameters
    ----------
    prompt  : str  Full prompt to send to Claude via stdin.
    timeout : int  Seconds before giving up (default 120).

    Returns
    -------
    str  Claude's text response.
    """
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            # No cwd here — avoids loading project .mcp.json which claude -p
            # cannot use (MCP tools are unavailable in print mode).
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "Claude CLI not found. Install from https://claude.ai/code"
        )
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Claude CLI timed out after {timeout}s.")

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if proc.returncode != 0:
        raise RuntimeError(
            f"Claude CLI exited {proc.returncode}.\n"
            f"stderr: {stderr or '(empty)'}\nstdout: {stdout or '(empty)'}"
        )

    try:
        out = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Claude returned non-JSON: {stdout[:300]!r}")

    if out.get("is_error"):
        raise RuntimeError(f"Claude error: {out.get('result', '')}")

    return out.get("result", "")


# ── Combined: fetch o9 data → reason with Claude ─────────────────────────────

def call_claude_o9(
    prompt: str,
    *,
    o9_tool: str | None = None,
    o9_args: dict | None = None,
    timeout: int = 120,
) -> str:
    """
    Full pipeline: optional o9 data fetch → Claude reasoning.

    If o9_tool is given, the tool result is prepended to the prompt so Claude
    can reason about live o9 data — all without an Anthropic API key.

    Parameters
    ----------
    prompt   : str   The question / instruction for Claude.
    o9_tool  : str   Optional o9 MCP tool to call first (e.g. "o9_execute_query").
    o9_args  : dict  Arguments for the o9 tool.
    timeout  : int   Seconds before timing out (default 120).

    Returns
    -------
    str  Claude's text response.
    """
    context = ""
    if o9_tool:
        o9_result = call_o9_tool(o9_tool, o9_args or {})
        context = f"O9 DATA ({o9_tool}):\n{o9_result['result']}\n\n"

    full_prompt = context + prompt
    return call_claude_p(full_prompt, timeout=timeout)


# ── Connection verification ────────────────────────────────────────────────────

def verify_connection() -> dict:
    """
    Verify both connection layers are reachable.

    Returns
    -------
    dict:
      o9_mcp  : {"status": "ok"|"failed", ...}
      claude  : {"status": "ok"|"failed", ...}
    """
    # Layer 1: o9 MCP server
    try:
        o9_result = call_o9_tool("o9_list_profiles")
        o9_status = {"status": "ok", "profiles": o9_result["result"]}
    except Exception as exc:
        o9_status = {"status": "failed", "error": str(exc)}

    # Layer 2: Claude CLI
    try:
        reply = call_claude_p("Reply with exactly: CLAUDE_OK", timeout=30)
        claude_status = {
            "status": "ok" if "CLAUDE_OK" in reply else "degraded",
            "reply": reply[:100],
        }
    except Exception as exc:
        claude_status = {"status": "failed", "error": str(exc)}

    return {"o9_mcp": o9_status, "claude": claude_status}


# ── Standalone smoke-test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("o9 <-> Claude connection test")
    print(f"  o9 MCP server : {O9_SERVER}")
    print(f"  Installed     : {O9_SERVER.exists()}")
    print()

    result = verify_connection()

    ok = True
    for layer, info in result.items():
        marker = "[OK]  " if info["status"] == "ok" else "[FAIL]"
        print(f"{marker} {layer}: {info}")
        if info["status"] == "failed":
            ok = False

    if not ok:
        print()
        print("Troubleshooting:")
        print("  o9 MCP  : run 1-install-claude-desktop.cmd from o9-platform-mcp-*-win-setup")
        print("            check %USERPROFILE%\\.o9-mcp\\config.json has valid credentials")
        print("  Claude  : run  claude --version  and  claude  (must be logged in)")
        sys.exit(1)
    else:
        print()
        print("Both layers connected. Use call_claude_o9() in your scripts.")
        sys.exit(0)
