#!/usr/bin/env python3
"""
o9 Self Heal Agent — Python backend server.

Replaces direct Anthropic API calls with Claude CLI (claude -p) subprocess calls.
No ANTHROPIC_API_KEY required — uses the Claude Code CLI login.

Routes:
  GET  /              -> file-upload-new.html  (Active Rule Triage)
  GET  /self-heal     -> index 1.html          (Self Heal Agent)
  POST /api/analyze   -> calls claude -p, returns {"result": "..."}
  POST /api/analyze   -> returns {"error": "..."} on error
"""
import http.server
import json
import subprocess
import sys
import os
from pathlib import Path
from urllib.parse import urlparse

PORT = 5173
BASE_DIR = Path(__file__).parent


class AgentHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.command} {self.path}  [{fmt % args}]")

    # ── CORS pre-flight ────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self._add_cors()
        self.end_headers()

    # ── GET ────────────────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/", ""):
            self._serve_file("file-upload-new.html")
        elif path == "/self-heal":
            self._serve_file("index 1.html")
        elif path == "/health":
            self._json({"status": "ok", "server": "o9-self-heal-agent"})
        else:
            self.send_error(404, "Not found")

    # ── POST ───────────────────────────────────────────────────────────
    def do_POST(self):
        if self.path == "/api/analyze":
            self._handle_analyze()
        else:
            self.send_error(404, "Not found")

    # ── /api/analyze ───────────────────────────────────────────────────
    def _handle_analyze(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
        except Exception as e:
            self._json({"error": f"Bad request: {e}"}, 400)
            return

        system_prompt = data.get("system_prompt", "")
        user_message  = data.get("user_message", "")

        # Build the full prompt that claude -p receives via stdin.
        # claude -p is single-turn; we combine system instructions + user content.
        parts = []
        if system_prompt:
            parts.append(f"SYSTEM INSTRUCTIONS:\n{system_prompt}")
        if user_message:
            parts.append(f"USER:\n{user_message}")
        full_prompt = "\n\n---\n\n".join(parts)

        try:
            proc = subprocess.run(
                ["claude", "-p", "--output-format", "json"],
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=180,
                # No cwd override — avoids auto-loading .mcp.json which can
                # cause MCP init failures before claude even processes the prompt.
            )
        except FileNotFoundError:
            self._json(
                {"error": "Claude CLI not found. Install Claude Code from https://claude.ai/code"},
                503,
            )
            return
        except subprocess.TimeoutExpired:
            self._json({"error": "Analysis timed out (180 s). Try a shorter input."}, 504)
            return
        except Exception as e:
            self._json({"error": f"Failed to run Claude CLI: {e}"}, 500)
            return

        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        # Log raw output so the server window shows what claude returned.
        if stdout:
            preview = stdout[:300].replace("\n", " ")
            print(f"  [claude stdout] {preview!r}")
        if stderr:
            print(f"  [claude stderr] {stderr[:200]!r}")

        if proc.returncode != 0:
            err = stderr or stdout or "Claude CLI returned a non-zero exit code."
            self._json({"error": err}, 500)
            return

        # claude -p --output-format json returns:
        # {"type":"result","result":"<text>","usage":{...}, ...}
        try:
            out = json.loads(stdout)
        except json.JSONDecodeError:
            # stdout is not JSON — it's an error message from the CLI
            # (e.g. "Forbidden.", "Error: not authenticated", etc.)
            err_text = stdout or stderr or "Claude CLI returned unexpected non-JSON output."
            self._json({"error": f"Claude CLI error: {err_text}"}, 500)
            return

        # claude -p sets is_error=true when the API itself returns an error
        if out.get("is_error"):
            err_text = out.get("result", "") or stderr or "Claude returned an error."
            self._json({"error": f"Claude error: {err_text}"}, 500)
            return

        result_text = out.get("result", stdout)
        self._json({"result": result_text})

    # ── helpers ────────────────────────────────────────────────────────
    def _serve_file(self, filename):
        filepath = BASE_DIR / filename
        if not filepath.exists():
            self.send_error(404, f"File not found: {filename}")
            return
        content = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self._add_cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _add_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def _check_claude():
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return r.stdout.strip() or "ok"
    except Exception:
        pass
    return None


def main():
    ver = _check_claude()
    if not ver:
        print("[FAIL] Claude CLI not found.")
        print("       Install Claude Code from https://claude.ai/code then re-run.")
        sys.exit(1)
    print(f"[OK] Claude CLI found ({ver})")

    os.chdir(BASE_DIR)
    print()
    print("o9 Self Heal Agent")
    print(f"  Active Rule Triage : http://localhost:{PORT}/")
    print(f"  Self Heal Agent    : http://localhost:{PORT}/self-heal")
    print("  Press Ctrl+C to stop.\n")

    server = http.server.HTTPServer(("localhost", PORT), AgentHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
