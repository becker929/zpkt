"""The tools as an MCP server on stdio: `python -m zpkt.app.ask.mcp`.

Claude Code and Gemini CLI start it for a session. It lists the five tools of tools.py and sends each call to the app
(`POST /app/ask/api/tool`) with the session's id and token, which come in the environment: ZPKT_DESK_URL,
ZPKT_APP_SESSION, ZPKT_APP_TOKEN. It holds no Live connection and imports nothing from zpkt.live: it is a client of
the app, like any other.

The tool list is the app's own (`GET /app/ask/api/tools`): the five built in, then one tool for each ability the
person allowed with "Always" (tools.py). It is asked for afresh at every `tools/list`. The server says it can tell
when the list changes (`listChanged`), and does: after every call, and every WATCH_S seconds while it waits, it
compares the app's list with the one it last gave and sends `notifications/tools/list_changed` when they differ, so
an ability kept in one turn is a tool in the same turn where the client listens, and at the latest in the next
(a new server lists afresh). If the app cannot be reached, the five built-in tools are listed.

A call waits TIMEOUT_S for the app. A tool that waits for the person's tap (`propose_live`) is given that tool's own
wait on top (tools.Tool.wait_s), so the app's "nobody answered" always comes back before this side gives up.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, TextIO

from zpkt.app.ask.tools import TOOLS

PROTOCOL = "2024-11-05"
TIMEOUT_S = 60
WAITS = {t.name: t.wait_s for t in TOOLS}  # the tools that wait for a person, and for how long


def timeout_for(tool: Any) -> float:
    """How long a call of `tool` may take over HTTP: the app's own time, plus the time a person has to answer."""
    return TIMEOUT_S + WAITS.get(str(tool), 0.0)


WATCH_S = 5.0  # how often a waiting server asks the app whether the tool list changed

Post = Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]
Lister = Callable[[], list[dict[str, Any]]]  # the tools as MCP lists them: {"name", "description", "inputSchema"}


def http_post(url: str) -> Post:
    """A function that sends one tool call to the app and returns (status, JSON)."""

    def post(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_for(body.get("tool"))) as r:
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
    """The five built-in tools: what is listed when the app cannot say."""
    return [{"name": t.name, "description": t.description, "inputSchema": t.schema} for t in TOOLS]


def http_tools(url: str) -> Lister:
    """A function that asks the app for the tools an agent has now (its abilities among them). When the app does
    not answer, or answers something else, the built-in tools."""

    def tools() -> list[dict[str, Any]]:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                found = json.loads(r.read() or b"{}").get("tools")
            return [{"name": t["name"], "description": t["description"], "inputSchema": t["input"]} for t in found]
        except (OSError, ValueError, KeyError, TypeError):
            return tool_list()

    return tools


def handle(
    message: dict[str, Any], post: Post, session: str, token: str, tools: Lister = tool_list
) -> dict[str, Any] | None:
    """The reply to one JSON-RPC message, or None for a notification."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": True}},
            "serverInfo": {"name": "zpkt", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": tools()}
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


class Watch:
    """Tells the client when the tool list is no longer the one it was last given: a `list_changed` notification,
    once per change. `seen` is asked after a call and by a timer; writes to stdout take their turn."""

    def __init__(self, stdout: TextIO, tools: Lister) -> None:
        self.stdout, self.tools = stdout, tools
        self.lock = threading.Lock()
        self.given: str | None = None  # the list the client last got, as text; None until it asked

    def write(self, message: dict[str, Any]) -> None:
        with self.lock:
            self.stdout.write(json.dumps(message) + "\n")
            self.stdout.flush()

    def gave(self, listed: list[dict[str, Any]]) -> None:
        self.given = json.dumps(listed, sort_keys=True)

    def seen(self) -> bool:
        """Compare the app's list with the one given; say so if it changed. True when it did."""
        if self.given is None:
            return False
        now = json.dumps(self.tools(), sort_keys=True)
        if now == self.given:
            return False
        self.given = now  # said once: the client asks for the list again and `gave` confirms it
        self.write({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        return True

    def every(self, seconds: float, stop: threading.Event) -> threading.Thread:
        def loop() -> None:
            while not stop.wait(seconds):
                self.seen()

        t = threading.Thread(target=loop, daemon=True, name="tools-watch")
        t.start()
        return t


def serve(
    stdin: TextIO,
    stdout: TextIO,
    post: Post,
    session: str,
    token: str,
    tools: Lister = tool_list,
    watch_s: float = 0.0,
) -> None:
    """Answer the client until stdin ends. `tools` lists the tools (default: the built-in five); with `watch_s`
    the list is also checked on a timer, for a server that lives on between turns."""
    watch = Watch(stdout, tools)
    stop = threading.Event()
    if watch_s > 0:
        watch.every(watch_s, stop)
    try:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            reply = handle(message, post, session, token, tools)
            if reply is None:
                continue
            listed = reply.get("result", {}).get("tools") if message.get("method") == "tools/list" else None
            if listed is not None:
                watch.gave(listed)
            watch.write(reply)
            if message.get("method") == "tools/call":
                watch.seen()  # a call may have kept an ability ("Always"): the list has one more tool
    finally:
        stop.set()


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
        http_tools(f"{url}/app/ask/api/tools"),
        WATCH_S,
    )


if __name__ == "__main__":
    main()
