"""Ableton Live MCP bridge server.

Exposes the full LiveMcpTransport surface (execute, api, search_api) as a
native MCP server over Streamable HTTP, so that Letta (running in Docker)
can connect directly without a stdio shim.

Transport
---------
  Streamable HTTP on 0.0.0.0:<ABLETON_MCP_BRIDGE_PORT> (default 9010).

  Letta registers this as:
    type: streamable_http
    server_url: http://host.docker.internal:9010/mcp

Architecture
-----------
  Letta → MCP (Streamable HTTP :9010) → LiveMcpTransport (TCP :16619) → Ableton
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from hands.transport import LiveMcpTransport

# ── Server & transport setup ───────────────────────────────────────────────────

_PORT = int(os.environ.get("ABLETON_MCP_BRIDGE_PORT", "9010"))
_HOST = os.environ.get("ABLETON_MCP_HOST", "127.0.0.1")
_ABLETON_PORT = int(os.environ.get("ABLETON_TCP_PORT", "16619"))

mcp = FastMCP(
    "ableton-live",
    host="0.0.0.0",
    port=_PORT,
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

def serve() -> None:
    """Start the MCP bridge server (blocks until interrupted)."""
    print(f"  [ableton-mcp-bridge] Streamable HTTP on http://0.0.0.0:{_PORT}/mcp")
    print(f"  [ableton-mcp-bridge] Proxying to Ableton at {_HOST}:{_ABLETON_PORT}")
    print(f"  [ableton-mcp-bridge] Letta server_url: http://host.docker.internal:{_PORT}/mcp")
    mcp.run(transport="streamable-http")
