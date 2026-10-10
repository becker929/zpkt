"""The connected pages. Each has one writer task, so sends never interleave and a stalled phone never blocks the
Mac: its queue fills, and past a limit it is dropped (it reconnects and catches up from the store).

One page at a time owns the mic and the speaker: the one that last pressed Start. The others watch.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from .model import Prefs, ShotLevel

log = logging.getLogger(__name__)

MAX_QUEUE = 4000   # frames; ~40 s of speech audio. A phone this far behind is gone.


class Client:
    def __init__(self, ws: web.WebSocketResponse, client_id: str, prefs: Prefs, ua: str = ""):
        self.ws, self.id, self.prefs, self.ua = ws, client_id, prefs, ua
        self.playing = False      # its output queue is busy
        self.mic_open = False
        self._closing = False
        self._queue: asyncio.Queue[str | bytes | None] = asyncio.Queue()
        self._writer = asyncio.create_task(self._write(), name=f"studio-writer-{client_id}")

    def send(self, msg: dict[str, Any] | bytes) -> None:
        if self._closing:
            return
        if self._queue.qsize() >= MAX_QUEUE:
            log.warning("page %s is %d frames behind; dropping it", self.id, self._queue.qsize())
            self._closing = True
            self._queue.put_nowait(None)
            return
        self._queue.put_nowait(msg if isinstance(msg, bytes) else json.dumps(msg, separators=(",", ":")))

    async def _write(self) -> None:
        try:
            while (item := await self._queue.get()) is not None:
                if isinstance(item, bytes):
                    await self.ws.send_bytes(item)
                else:
                    await self.ws.send_str(item)
        except (ConnectionError, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            if not self.ws.closed:
                await self.ws.close()

    async def close(self) -> None:
        if not self._closing:
            self._closing = True
            self._queue.put_nowait(None)
        try:
            await asyncio.wait_for(self._writer, 2)
        except asyncio.TimeoutError:
            self._writer.cancel()


class Hub:
    def __init__(self) -> None:
        self.clients: dict[str, Client] = {}
        self.owner: Client | None = None

    def add(self, client: Client) -> None:
        old = self.clients.get(client.id)
        if old is not None and old is not client:   # the same page reconnected
            asyncio.create_task(old.close())
            if self.owner is old:
                self.owner = client
        self.clients[client.id] = client

    def remove(self, client: Client) -> None:
        if self.clients.get(client.id) is client:
            del self.clients[client.id]
        if self.owner is client:
            self.owner = None

    def broadcast(self, msg: dict[str, Any], level: ShotLevel | None = None) -> None:
        """To every page; with `level`, only to pages that asked for screenshots at least that detailed."""
        for c in list(self.clients.values()):
            if level is None or c.prefs.shots >= level:
                c.send(msg)

    def to_owner(self, msg: dict[str, Any] | bytes) -> bool:
        if self.owner is None:
            return False
        self.owner.send(msg)
        return True

    @property
    def shots_level(self) -> ShotLevel:
        return max((c.prefs.shots for c in self.clients.values()), default=ShotLevel.NONE)

    @property
    def autoplay(self) -> bool:
        return bool(self.owner and self.owner.prefs.autoplay)
