"""ACP (Agent Client Protocol): JSON-RPC 2.0 on the stdio of one long-lived `gemini --acp` process, on threads.

Requests from the agent (it asks permission) go to `on_request`, each answered on its own thread, since the answer
may wait for a person. Notifications (session/update) go to `on_notify`.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any


class AcpError(RuntimeError):
    """Gemini CLI answered with an error, or is not running."""


class Acp:
    def __init__(
        self,
        cmd: list[str],
        cwd: Path,
        env: dict[str, str],
        on_notify: Callable[[str, dict[str, Any]], None],
        on_request: Callable[[str, dict[str, Any]], Any],
    ) -> None:
        self.cmd, self.cwd, self.env = cmd, cwd, env
        self.on_notify, self.on_request = on_notify, on_request
        self.proc: subprocess.Popen[str] | None = None
        self.next_id = 0
        self.pending: dict[int, Future[dict[str, Any]]] = {}
        self.write_lock = threading.Lock()
        self.id_lock = threading.Lock()
        self.info: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [*self.cmd, "--acp", "--skip-trust"],
            cwd=str(self.cwd),
            env=self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read, daemon=True, name="acp-read").start()
        self.info = (
            self.request(
                "initialize",
                {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}}},
                60,
            )
            or {}
        )

    def close(self) -> None:
        if self.proc is not None and self.alive:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _send(self, msg: dict[str, Any]) -> None:
        if not self.alive or self.proc is None or self.proc.stdin is None:
            raise AcpError("Gemini CLI is not running.")
        with self.write_lock:
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except OSError as exc:
                raise AcpError("Gemini CLI is not running.") from exc

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> Any:
        with self.id_lock:
            self.next_id += 1
            ident = self.next_id
        fut: Future[dict[str, Any]] = Future()
        self.pending[ident] = fut
        self._send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        try:
            msg = fut.result(timeout)
        except FutureTimeout:
            self.pending.pop(ident, None)
            raise AcpError(f"{method}: no answer in {timeout} s") from None
        if "error" in msg:
            e = msg["error"]
            raise AcpError(f"{method}: {e.get('message', e)}" + (f" ({e['data']})" if e.get("data") else ""))
        return msg.get("result")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _read(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            for line in self.proc.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(msg, dict):
                    continue
                if "method" not in msg:
                    fut = self.pending.pop(msg.get("id"), None)  # type: ignore[arg-type]
                    if fut is not None and not fut.done():
                        fut.set_result(msg)
                elif "id" in msg:
                    threading.Thread(target=self._answer, args=(msg,), daemon=True).start()
                else:
                    with contextlib.suppress(Exception):  # an update that cannot be shown must not stop the reader
                        self.on_notify(msg["method"], msg.get("params") or {})
        finally:
            for fut in list(self.pending.values()):
                if not fut.done():
                    fut.set_result({"error": {"message": "Gemini CLI stopped."}})
            self.pending.clear()

    def _answer(self, msg: dict[str, Any]) -> None:
        try:
            result = self.on_request(msg["method"], msg.get("params") or {})
            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        except Exception as exc:  # the agent gets the error as its answer
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(exc)}}
        with contextlib.suppress(AcpError):
            self._send(reply)
