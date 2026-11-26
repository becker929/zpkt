"""The tools as an MCP server on stdio: `python -m zpkt.app.ask.mcp`.

Claude Code and Gemini CLI start it for a session. It lists the three tools of tools.py and sends each call to the app
(`POST /app/ask/api/tool`) with the session's id and token, which come in the environment: ZPKT_DESK_URL,
ZPKT_APP_SESSION, ZPKT_APP_TOKEN. It holds no Live connection and imports nothing from zpkt.live: it is a client of
the app, like any other.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, TextIO

from zpkt.app.ask.tools import TOOLS

PROTOCOL = "2024-11-05"
TIMEOUT_S = 60

Post = Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]


def http_post(url: str) -> Post:
    """A function that sends one tool call to the app and returns (status, JSON)."""

    def post(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read() or b"{}")
            except ValueError:
                return exc.code, {"error": f"the app answered {exc.code}"}
        except OSError as exc:
            return 503, {"error": f"the app is not reachable: {exc}"}

    return post


def tool_list() -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "inputSchema": t.schema} for t in TOOLS]


def handle(message: dict[str, Any], post: Post, session: str, token: str) -> dict[str, Any] | None:
    """The reply to one JSON-RPC message, or None for a notification."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "zpkt", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": tool_list()}
    elif method == "tools/call":
        params = message.get("params") or {}
        status, reply = post(
            {"session": session, "token": token, "tool": params.get("name"), "args": params.get("arguments") or {}}
        )
        result = {
            "content": [{"type": "text", "text": json.dumps(reply, ensure_ascii=False)}],
            "isError": status >= 400,
        }
    else:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(stdin: TextIO, stdout: TextIO, post: Post, session: str, token: str) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(message, post, session, token)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def main() -> None:
    url = (os.environ.get("ZPKT_DESK_URL") or os.environ.get("ZPKT_APP_URL", "")).rstrip("/")  # APP_URL: the old name
    if not url:
        sys.exit("ZPKT_DESK_URL is not set: this server is started by the app for a session.")
    serve(
        sys.stdin,
        sys.stdout,
        http_post(f"{url}/app/ask/api/tool"),
        os.environ.get("ZPKT_APP_SESSION", ""),
        os.environ.get("ZPKT_APP_TOKEN", ""),
    )


if __name__ == "__main__":
    main()
