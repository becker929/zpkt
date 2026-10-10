"""Screenshots of what Claude does on the Mac, as pairs: the full screen and a zoom into what changed.

Levels (the highest any connected page asked for decides what is captured at all):
    major     the end of a turn in which the screen changed; Claude's own screenshot calls; major script steps
    minor     every tool call (the zoom shows what that call changed); minor script steps
    firehose  about once a second while a tool runs, when something changed; every script step

Capture, saliency and encoding are plain functions in `shots`; this module decides when to use them.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from . import shots
from .activity import describe
from .model import Kind, Message, ShotLevel
from .store import Store

log = logging.getLogger(__name__)

Emit = Callable[[Kind, dict[str, Any], ShotLevel], Message]


class Screens:
    FIREHOSE_S = 1.0
    REUSE_S = 0.25            # a capture this fresh is reused rather than taken again

    def __init__(self, store: Store, level: Callable[[], ShotLevel], capture: shots.Capture | None = None):
        self.store, self._level = store, level
        self.capture = capture or shots.ScreenCapture()
        self.emit: Emit | None = None          # set by the conversation: makes the chat message
        self._lock = asyncio.Lock()
        self._last: shots.Frame | None = None
        self._turn_base: shots.Frame | None = None
        self._turn_task: asyncio.Task | None = None
        self._before: dict[str, shots.Frame] = {}
        self._firehose: dict[str, asyncio.Task] = {}
        self._broken = False

    @property
    def level(self) -> ShotLevel:
        return ShotLevel.NONE if self._broken else self._level()

    def wants(self, level: ShotLevel) -> bool:
        return self.level >= level

    async def grab(self) -> shots.Frame | None:
        async with self._lock:
            if self._last is not None and time.monotonic() - self._last.t < self.REUSE_S:
                return self._last
            try:
                self._last = await self.capture.grab()
            except shots.CaptureError as exc:
                log.warning("screenshots off: %s", exc)
                self._broken = True         # e.g. no Screen Recording permission; don't retry every call
                return None
            return self._last

    async def shot(self, level: ShotLevel, caption: str, before: shots.Frame | None = None,
                   hint: tuple[int, int] | None = None, only_if_changed: bool = False) -> Message | None:
        """Capture now and post the pair, if a page wants `level`. `before` is what the zoom compares against;
        firehose shots (and `only_if_changed`) are posted only when something changed since `before`."""
        if not self.wants(level) or self.emit is None:
            return None
        frame = await self.grab()
        if frame is None:
            return None
        pair = await asyncio.to_thread(shots.make_pair, before.pixels if before else None, frame.pixels, hint,
                                       only_if_changed or level is ShotLevel.FIREHOSE)
        if pair is None:
            return None
        full = await asyncio.to_thread(self.store.put_media, pair.full, pair.ext, w=pair.full_size[0],
                                       h=pair.full_size[1])
        zoom = await asyncio.to_thread(self.store.put_media, pair.zoom, pair.ext, w=pair.zoom_size[0],
                                       h=pair.zoom_size[1])
        return self.emit(Kind.SHOTS, {"level": level.label, "caption": caption[:200], "full": full.wire(),
                                      "zoom": zoom.wire(), "rect": list(pair.rect), "changed": pair.changed,
                                      "screen": [frame.pixels.shape[1], frame.pixels.shape[0]]}, level)

    # --- turns -----------------------------------------------------------------------------------------------------
    def turn_started(self) -> None:
        self._turn_base = None
        if self.wants(ShotLevel.MAJOR):
            self._turn_task = asyncio.create_task(self._take_turn_base(), name="shot-turn-base")

    async def _take_turn_base(self) -> None:
        self._turn_base = await self.grab()

    async def turn_ended(self, caption: str = "Where things ended up") -> None:
        if self._turn_task is not None:
            await self._turn_task
            self._turn_task = None
        for task in self._firehose.values():
            task.cancel()
        self._firehose.clear()
        self._before.clear()
        base, self._turn_base = self._turn_base, None
        if base is None or not self.wants(ShotLevel.MAJOR):
            return
        await self.shot(ShotLevel.MAJOR, caption, before=base, only_if_changed=True)

    # --- tool calls (Agent SDK hooks) ----------------------------------------------------------------------------
    async def before_tool(self, tool_use_id: str, tool: str, args: dict[str, Any]) -> None:
        if self.wants(ShotLevel.MINOR):
            frame = await self.grab()
            if frame is not None:
                self._before[tool_use_id] = frame
        if self.wants(ShotLevel.FIREHOSE):
            self._firehose[tool_use_id] = asyncio.create_task(self._watch(describe(tool, args)), name="firehose")

    async def after_tool(self, tool_use_id: str, tool: str, args: dict[str, Any]) -> None:
        task = self._firehose.pop(tool_use_id, None)
        if task is not None:
            task.cancel()
        before = self._before.pop(tool_use_id, None)
        if self.wants(ShotLevel.MINOR) and before is not None:
            await self.shot(ShotLevel.MINOR, describe(tool, args), before=before)

    async def _watch(self, caption: str) -> None:
        prev = await self.grab()
        while True:
            await asyncio.sleep(self.FIREHOSE_S)
            msg = await self.shot(ShotLevel.FIREHOSE, caption, before=prev)
            if msg is not None or prev is None:
                prev = self._last

    def hooks(self) -> dict[str, Any]:
        """Agent SDK hook callbacks: a capture before and after every tool call (when a page wants them)."""
        async def pre(data: dict[str, Any], tool_use_id: str | None, _ctx: Any) -> dict[str, Any]:
            if tool_use_id:
                await self.before_tool(tool_use_id, data.get("tool_name", ""), data.get("tool_input") or {})
            return {}

        async def post(data: dict[str, Any], tool_use_id: str | None, _ctx: Any) -> dict[str, Any]:
            if tool_use_id:
                await self.after_tool(tool_use_id, data.get("tool_name", ""), data.get("tool_input") or {})
            return {}

        return {"pre": pre, "post": post}
