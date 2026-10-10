"""One client for the AbletonLiveMCP Remote Script, plus the doubles tests use.

The Remote Script runs inside Live on 127.0.0.1:16619 and speaks one JSON object per line:

    -> {"id": "cmd-1", "code": "<python>"}          or  {"ping": true}
    <- {"status": "ok", "result": ..., "elapsed": s}     {"status": "ok", "pong": true}
    <- {"status": "error", "error": "...", "traceback": "...", "warning": "..."}

The code runs on Live's main thread, as an expression if it parses as one, else as statements
that may set `result`. The server stops waiting after 12 s and answers "Timed out after 12s"
with a warning that the code may still be running, so keep each call well under that. A call
costs about 0.85 s whatever it does, so batch edits into one call (50 parameter sets took
0.76 s in one call and 42.6 s as 50 calls; docs/probe-packing-findings.md).

LiveClient opens a connection per call: the server serves one connection at a time, and
other tools share it. It retries only while connecting, when the request cannot have reached
Live. A request that was sent and then lost its reply may still run, and sending it again
could apply an edit twice, so that is an error for the caller to judge.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Sequence, runtime_checkable

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 16619
UNREACHABLE = "Cannot reach Ableton"  # starts every transport error; StepRunner keys on it


@dataclass
class McpResult:
    status: Literal["ok", "error"]
    result: Any = None
    error: str | None = None
    warning: str | None = None     # e.g. "Code may still be running on the main thread."
    elapsed: float | None = None   # seconds Live spent running the code
    traceback: str | None = None


class LiveError(RuntimeError):
    """A LOM call failed: Live raised, timed out or could not be reached. `.result` is the reply."""

    def __init__(self, message: str, result: McpResult | None = None) -> None:
        super().__init__(message)
        self.result = result


@runtime_checkable
class McpTransport(Protocol):
    """What the rest of hands needs from a connection to Live."""

    def execute(self, code: str) -> McpResult:
        """Run code; report failure in the result."""
        ...

    def run(self, code: str) -> Any:
        """Run code; return its result or raise LiveError."""
        ...


class Transport:
    """`run` on top of `execute`, shared by every transport."""

    def execute(self, code: str) -> McpResult:
        raise NotImplementedError

    def run(self, code: str) -> Any:
        """Execute code and return its result; raise LiveError if it failed."""
        res = self.execute(code)
        if res.status == "ok":
            return res.result
        message = res.error or "unknown error"
        if res.warning:
            message += f" ({res.warning})"
        first = code.strip().splitlines()[0][:70] if code.strip() else ""
        raise LiveError(f"{message} [in {first!r}]", res)


class _NotSent(OSError):
    """The connection failed before the request went out: safe to try again."""


class _Lost(OSError):
    """The request went out but no usable reply came back: it may have run."""


class LiveClient(Transport):
    """TCP client for the AbletonLiveMCP Remote Script."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 15.0,
                 retries: int = 2, backoff: float = 0.5) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.retries, self.backoff = retries, backoff
        self._cmd_id = 0

    def execute(self, code: str) -> McpResult:
        self._cmd_id += 1
        try:
            reply = self._exchange({"id": f"cmd-{self._cmd_id}", "code": code})
        except (_NotSent, _Lost) as exc:
            return McpResult(status="error", error=str(exc))
        ok = reply.get("status") == "ok"
        return McpResult(
            status="ok" if ok else "error",
            result=reply.get("result"),
            error=None if ok else str(reply.get("error") or reply),
            warning=reply.get("warning") or reply.get("hint"),
            elapsed=reply.get("elapsed"),
            traceback=reply.get("traceback"),
        )

    def ping(self) -> float:
        """Round-trip seconds of the server's ping; raise LiveError without a pong.

        The server answers a ping from its own thread, so a pong shows the Remote Script is
        listening, not that Live's main thread is free: `run("result = 1")` checks that.
        """
        t0 = time.monotonic()
        try:
            reply = self._exchange({"ping": True})
        except (_NotSent, _Lost) as exc:
            raise LiveError(str(exc)) from exc
        if not reply.get("pong"):
            raise LiveError(f"no pong from the Remote Script: {reply}")
        return time.monotonic() - t0

    def _connect(self) -> socket.socket:
        """Connect, retrying with backoff: nothing has been sent yet, so a retry is safe."""
        attempt = 0
        while True:
            try:
                return socket.create_connection((self.host, self.port), timeout=self.timeout)
            except OSError as exc:
                if attempt >= self.retries:
                    raise _NotSent(f"{UNREACHABLE}: {exc}") from exc
            time.sleep(self.backoff * 2 ** attempt)
            attempt += 1

    def _exchange(self, message: dict) -> dict:
        with self._connect() as sock:
            try:
                sock.sendall((json.dumps(message) + "\n").encode())
                line = sock.makefile("rb").readline()
            except TimeoutError as exc:
                raise _Lost(f"{UNREACHABLE}: no reply in {self.timeout:g} s; the code may still run") from exc
            except OSError as exc:
                raise _Lost(f"{UNREACHABLE}: connection lost ({exc}); the code may have run") from exc
        if not line.strip():
            raise _Lost(f"{UNREACHABLE}: Live closed the connection without a reply")
        try:
            return json.loads(line)
        except ValueError as exc:
            raise _Lost(f"{UNREACHABLE}: unreadable reply {line[:80]!r}") from exc


class DryRunTransport(Transport):
    """Print each code block without executing it. Used for --dry-run."""

    def execute(self, code: str) -> McpResult:
        print("--- DRY RUN ---")
        print(code)
        print("---------------")
        return McpResult(status="ok", result="dry-run ok")


class MockTransport(Transport):
    """Return canned responses for unit tests, recording every call."""

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
