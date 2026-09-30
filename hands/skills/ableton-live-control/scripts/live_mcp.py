#!/usr/bin/env python3
"""
live_mcp.py - Dependency-free client + library for driving Ableton Live 12 via
the Live Object Model (LOM), through the opendining/ableton-mcp-server Remote
Script's TCP bridge (default 127.0.0.1:16619).

Unlike AbletonOSC (see live.py, a small fixed vocabulary of OSC addresses),
this executes arbitrary Python against the full LOM: devices, browser,
automation envelopes, arrangement view, drum racks, etc. It is far more
powerful but also far more crash-prone — read reference/lom-guide.md before
writing nontrivial `execute()` code (no post-set readback, no large parameter
sweeps, sleep between browser loads, etc).

Wire protocol: one JSON object per line, both directions.
    -> {"id": "cmd-1", "code": "<python>"}
    <- {"status": "ok", "result": ...}                 # or
    <- {"status": "error", "error": "..."}

Inside the executed code, these globals are available (provided by the
Remote Script, not by this client):
    song, app, tracks, returns, master, browser, Live,
    MidiNoteSpecification, find_item, find_items, find_track, load_to,
    log, json, time, api, search_api
Expressions (e.g. `song.tempo`) are eval'd and returned directly.
Statements (e.g. `song.tempo = 140`) are exec'd — assign to `result` to
return data from a statement block.

CLI usage:
    live_mcp.py "song.tempo"                       # eval an expression
    live_mcp.py "song.tempo = 140"                  # exec a statement (no result)
    live_mcp.py "result = [t.name for t in song.tracks]"
    live_mcp.py --file snippet.py                   # execute a multi-line file
    echo "song.tempo" | live_mcp.py --stdin
    live_mcp.py --host 127.0.0.1 --port 16619 "api('Song.tempo')"
    live_mcp.py --json "result = len(song.tracks)"  # print result as JSON

Library usage:
    from live_mcp import LiveMcp
    live = LiveMcp()
    live.execute("song.tempo").result        # -> 128.0
    live.eval_("len(song.tracks)")           # -> raises on error, else value
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 16619


@dataclass
class McpResult:
    status: str  # "ok" | "error"
    result: Any = None
    error: Optional[str] = None


class LiveMcpError(Exception):
    pass


class LiveMcp:
    """TCP client for the opendining Ableton MCP server (LOM bridge)."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 30.0, retries: int = 0, retry_backoff: float = 0.5):
        self.host = host
        self.port = port
        self.timeout = timeout
        # Opt-in retry for TRANSIENT transport failures only (see _execute_once).
        self.retries = retries
        self.retry_backoff = retry_backoff
        self._cmd_id = 0

    def _execute_once(self, code: str) -> McpResult:
        """Single attempt: send one code block, return the single-line JSON reply."""
        self._cmd_id += 1
        payload = json.dumps({"id": f"cmd-{self._cmd_id}", "code": code}) + "\n"
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(payload.encode())
                line = sock.makefile("r").readline()
            resp = json.loads(line) if line.strip() else {}
            if resp.get("status") == "ok":
                return McpResult(status="ok", result=resp.get("result"))
            return McpResult(
                status="error",
                error=str(resp.get("error") or resp.get("result") or resp),
            )
        except socket.timeout:
            return McpResult(status="error", error="Cannot reach Ableton: timed out")
        except (ConnectionRefusedError, OSError) as exc:
            return McpResult(status="error", error=f"Cannot reach Ableton: {exc}")

    @staticmethod
    def _is_transient(err: Optional[str]) -> bool:
        """Only transport failures are safe to retry. LOM code errors are
        deterministic -- retrying them just repeats the same failure (and may
        double a mutation), so we never retry those."""
        return bool(err) and err.startswith("Cannot reach Ableton")

    def execute(self, code: str) -> McpResult:
        """Send one code block; on TRANSIENT transport errors, retry with backoff
        up to ``self.retries`` times. Deterministic LOM errors are not retried."""
        attempt = 0
        while True:
            resp = self._execute_once(code)
            if resp.status == "ok" or not self._is_transient(resp.error):
                return resp
            if attempt >= self.retries:
                return resp
            time.sleep(self.retry_backoff * (2 ** attempt))
            attempt += 1

    def eval_(self, code: str) -> Any:
        """Execute code; return the result or raise LiveMcpError on failure."""
        resp = self.execute(code)
        if resp.status != "ok":
            raise LiveMcpError(resp.error or "unknown error")
        return resp.result

    # convenience helpers, mirroring common hands/helpers.py queries -----------
    def song_state(self) -> dict:
        return self.eval_("""
result = {
    "tempo": song.tempo,
    "signature": f"{song.signature_numerator}/{song.signature_denominator}",
    "is_playing": song.is_playing,
    "num_tracks": len(song.tracks),
    "num_scenes": len(song.scenes),
    "track_names": [t.name for t in song.tracks],
    "loop": song.loop,
    "loop_start": song.loop_start,
    "loop_length": song.loop_length,
}
""")

    def track_names(self) -> list:
        return self.eval_("[t.name for t in song.tracks]")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Execute Python against the Ableton Live Object Model via the MCP TCP bridge"
    )
    p.add_argument("code", nargs="?", help="Python code to execute (expression or statements)")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--timeout", type=float, default=30.0, help="reply timeout in seconds")
    p.add_argument("--retries", type=int, default=0,
                   help="retry count for TRANSIENT transport errors only (backoff between tries)")
    p.add_argument("--file", help="read code from a file instead of the argument")
    p.add_argument("--stdin", action="store_true", help="read code from stdin")
    p.add_argument("--json", action="store_true", help="print result as JSON")
    a = p.parse_args(argv)

    if a.file:
        code = open(a.file).read()
    elif a.stdin:
        code = sys.stdin.read()
    elif a.code:
        code = a.code
    else:
        p.error("provide code as an argument, --file, or --stdin")
        return 2

    live = LiveMcp(a.host, a.port, a.timeout, retries=a.retries)
    resp = live.execute(code)
    if resp.status == "error":
        print("ERROR: %s" % resp.error, file=sys.stderr)
        return 1
    if a.json:
        try:
            print(json.dumps(resp.result))
        except TypeError:
            print(json.dumps(str(resp.result)))
    else:
        print(resp.result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
