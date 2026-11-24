"""ACP (Agent Client Protocol): JSON-RPC 2.0 on the stdio of one long-lived `gemini --acp` process."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class AcpError(RuntimeError):
    """Gemini CLI answered with an error, or is not running."""


class Acp:
    """JSON-RPC 2.0 over a child's stdio, one JSON object per line. Requests from the agent (permission) go to
    `on_request`; notifications (session/update) to `on_notify`."""

    def __init__(
        self,
        cmd: list[str],
        cwd: Path,
        env: dict,
        on_notify: Callable[[str, dict], None],
        on_request: Callable[[str, dict], Awaitable[Any]],
    ):
        self.cmd, self.cwd, self.env = cmd, cwd, env
        self.on_notify, self.on_request = on_notify, on_request
        self.proc: asyncio.subprocess.Process | None = None
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.info: dict = {}
        self._tasks: list[asyncio.Task] = []
        self._answering: set[asyncio.Task] = set()  # answers to the agent's requests, kept until they finish

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            "--acp",
            "--skip-trust",
            cwd=str(self.cwd),
            env=self.env,
            limit=1 << 25,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._stderr())]
        self.info = await self.request(
            "initialize",
            {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}}},
            60,
        )

    async def close(self) -> None:
        if self.alive:
            self.proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.proc.wait(), 5)
            if self.alive:
                self.proc.kill()
        for t in self._tasks:
            t.cancel()

    async def _send(self, msg: dict) -> None:
        if not self.alive:
            raise AcpError("Gemini CLI is not running.")
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict, timeout: float | None = None) -> Any:
        self.next_id += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.next_id] = fut
        await self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        msg = await (asyncio.wait_for(fut, timeout) if timeout else fut)
        if "error" in msg:
            e = msg["error"]
            raise AcpError(f"{method}: {e.get('message', e)}" + (f" ({e['data']})" if e.get("data") else ""))
        return msg.get("result")

    async def notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _read(self) -> None:
        assert self.proc and self.proc.stdout
        try:
            while line := await self.proc.stdout.readline():
                try:
                    msg = json.loads(line)
                except ValueError:
                    log.debug("gemini acp: %s", line[:200])
                    continue
                if "method" not in msg:
                    fut = self.pending.pop(msg.get("id"), None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif "id" in msg:
                    task = asyncio.create_task(self._answer(msg))
                    self._answering.add(task)
                    task.add_done_callback(self._answering.discard)
                else:
                    try:
                        self.on_notify(msg["method"], msg.get("params") or {})
                    except Exception:
                        log.exception("gemini acp update")
        finally:
            for fut in self.pending.values():
                if not fut.done():
                    fut.set_result({"error": {"message": "Gemini CLI stopped."}})
            self.pending.clear()

    async def _answer(self, msg: dict) -> None:
        try:
            result = await self.on_request(msg["method"], msg.get("params") or {})
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        except Exception as e:  # the agent gets the error as its answer
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}}
        with contextlib.suppress(AcpError, ConnectionError):
            await self._send(reply)

    async def _stderr(self) -> None:
        assert self.proc and self.proc.stderr
        while line := await self.proc.stderr.readline():
            log.info("gemini cli: %s", line.decode(errors="replace").rstrip()[:300])
