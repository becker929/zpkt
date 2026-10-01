"""Ableton Live MCP bridge server.

Exposes the full LiveMcpTransport surface (execute, api, search_api) as a
native MCP server over Streamable HTTP, so that Letta (running in Docker)
can connect directly without a stdio shim.

Transport
---------
  Streamable HTTP on 127.0.0.1:<ABLETON_MCP_BRIDGE_PORT> (default 9010).

Security
--------
  `execute` runs arbitrary Python inside Ableton Live, i.e. code execution as
  the user. The bridge therefore:
    - binds loopback only (Docker Desktop still reaches it as
      host.docker.internal); ABLETON_MCP_BRIDGE_BIND widens it explicitly;
    - refuses to start without MCP_BRIDGE_TOKEN and checks it as a bearer
      token on every request;
    - enables DNS-rebinding protection (Host/Origin allow-lists).

  Letta registers this as:
    type: streamable_http
    server_url: http://host.docker.internal:9010/mcp

Architecture
-----------
  Letta → MCP (Streamable HTTP :9010) → LiveMcpTransport (TCP :16619) → Ableton
"""

from __future__ import annotations

import os

import hmac

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from hands.transport import LiveMcpTransport

# ── Server & transport setup ───────────────────────────────────────────────────

_PORT = int(os.environ.get("ABLETON_MCP_BRIDGE_PORT", "9010"))
_HOST = os.environ.get("ABLETON_MCP_HOST", "127.0.0.1")
_ABLETON_PORT = int(os.environ.get("ABLETON_TCP_PORT", "16619"))

_BIND = os.environ.get("ABLETON_MCP_BRIDGE_BIND", "127.0.0.1")

mcp = FastMCP(
    "ableton-live",
    host=_BIND,
    port=_PORT,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "host.docker.internal:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    ),
)

_transport = LiveMcpTransport(host=_HOST, port=_ABLETON_PORT)


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def execute(code: str) -> str:
    """Execute Python code inside Ableton Live and return the result.

    The code runs in a fresh namespace each call with these globals available:
      song     — the Live Set (tempo, tracks, scenes, transport)
      app      — the Live Application (browser, version)
      tracks   — shortcut for song.tracks (stale after mutations)
      returns  — shortcut for song.return_tracks
      master   — shortcut for song.master_track
      browser  — app.browser for loading instruments/effects/sounds
      Live     — the Live module
      MidiNoteSpecification — shortcut, no import needed
      find_item   — find_item(browser.instruments, "Piano") -> BrowserItem or None
      find_items  — find_items(browser.drums, "808") -> ranked list
      find_track  — find_track("Bass") -> Track or None
      load_to     — load_to(track, browser.instruments, "Piano")
      log      — write to Ableton's Log.txt
      json     — the json module
      time     — the time module
      api      — browse the Live API reference
      search_api — search the Live API reference

    Expressions like `song.tempo` are eval'd and return their value.
    Statements like `song.tempo = 140` are exec'd — assign to `result`
    to return data from a statement block.
    """
    result = _transport.execute(code)
    if result.status == "error":
        return "Error: " + (result.error or "unknown error")
    return str(result.result)


@mcp.tool()
def api(class_name: str = "") -> str:
    """Browse the Ableton Live API reference by class.

    No argument: list all classes with descriptions and access paths.
    With class name: show full details (properties, methods) for that class.
    With dotted path: show a single member — e.g. api("Song.tempo").
    Special: api("enums") shows all enum/constant tables.

    Examples: api(), api("Song"), api("clip"), api("Song.tempo"), api("enums").
    """
    if class_name:
        code = "result = api(" + repr(class_name) + ")"
    else:
        code = "result = api()"
    result = _transport.execute(code)
    if result.status == "error":
        return "Error: " + (result.error or "unknown error")
    return str(result.result)


@mcp.tool()
def search_api(query: str) -> str:
    """Search the Live API reference by keyword.

    Searches across class names, property/method names, descriptions, and types.
    Supports multi-word queries ("loop start"), fuzzy stems (quantize ≈ quantization),
    and underscore-aware matching. Returns matching entries grouped by class.

    Examples: search_api("tempo"), search_api("quantize"), search_api("loop start").
    """
    code = "result = search_api(" + repr(query) + ")"
    result = _transport.execute(code)
    if result.status == "error":
        return "Error: " + (result.error or "unknown error")
    return str(result.result)


# ── Entry point ────────────────────────────────────────────────────────────────

class _RequireBearer:
    """ASGI middleware: reject any HTTP request without the bridge token."""

    def __init__(self, app, token: str) -> None:
        self._app = app
        self._expected = ("Bearer " + token).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            sent = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(sent, self._expected):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self._app(scope, receive, send)


def build_app(token: str):
    """The bridge's ASGI app, wrapped in the bearer-token check."""
    return _RequireBearer(mcp.streamable_http_app(), token)


def serve() -> None:
    """Run the bridge. Refuses to start without MCP_BRIDGE_TOKEN."""
    token = os.environ.get("MCP_BRIDGE_TOKEN", "")
    if not token:
        raise SystemExit(
            "MCP_BRIDGE_TOKEN is not set. The bridge runs arbitrary Python in Live, "
            "so it will not start without a token. Set it here and in Letta's MCP "
            "server config (scripts/setup_letta_tools.py sends it)."
        )
    import uvicorn

    uvicorn.run(build_app(token), host=_BIND, port=_PORT, log_level="info")
