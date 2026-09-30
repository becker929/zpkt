"""Transport protocol and implementations for the Ableton MCP connection.

McpTransport is a Protocol — callers depend only on the interface.
LiveMcpTransport talks TCP to the opendining MCP server.
DryRunTransport prints code without executing.
MockTransport returns canned responses for tests.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Sequence, runtime_checkable


@dataclass
class McpResult:
    status: Literal["ok", "error"]
    result: Any = None
    error: str | None = None


@runtime_checkable
class McpTransport(Protocol):
    """Minimal interface for executing LOM Python code against Ableton."""

    def execute(self, code: str) -> McpResult:
        """Execute code and return the result."""
        ...


class LiveMcpTransport:
    """TCP transport to the opendining Ableton MCP server."""

    def __init__(self, host: str = "127.0.0.1", port: int = 16619) -> None:
        self._host = host
        self._port = port
        self._cmd_id = 0

    def execute(self, code: str) -> McpResult:
        self._cmd_id += 1
        payload = json.dumps({"id": f"cmd-{self._cmd_id}", "code": code}) + "\n"
        try:
            with socket.create_connection((self._host, self._port), timeout=30) as sock:
                sock.sendall(payload.encode())
                # makefile gives us a clean line-buffered reader; avoids
                # partial-read issues when the response spans multiple packets.
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
            return McpResult(
                status="error",
                error=f"Cannot reach Ableton: {exc}",
            )


class DryRunTransport:
    """Print each code block without executing it. Used for --dry-run."""

    def execute(self, code: str) -> McpResult:
        print("--- DRY RUN ---")
        print(code)
        print("---------------")
        return McpResult(status="ok", result="dry-run ok")


class MockTransport:
    """Return canned responses for unit tests."""

    def __init__(self, responses: Sequence[McpResult] | None = None) -> None:
        self._queue: list[McpResult] = list(responses) if responses else []
        self._calls: list[str] = []

    @property
    def calls(self) -> list[str]:
        return self._calls

    def execute(self, code: str) -> McpResult:
        self._calls.append(code)
        if self._queue:
            return self._queue.pop(0)
        return McpResult(status="ok", result="mock ok")
