"""Screenshots of what Claude does on the Mac, as pairs: the full screen and a zoom into what changed.

Levels (the highest any connected page asked for decides what is captured at all):
    major     the end of a turn in which the screen changed; Claude's own screenshot calls; major script steps
    minor     every tool call (the zoom shows what that call changed); minor script steps
    firehose  a look every second while a tool runs, posted when something changed; every script step

Capturing never holds Claude up. The hook before a tool captures nothing (at firehose level it starts watching);
the hook after it queues the tool's shot and returns. Captures are taken one at a time, each compared with the one
before it: the previous step's, or the turn's first, which is taken in the background as the turn starts. So the
frames kept are the latest and the turn's first (and, while watching, the last one looked at).

grab.py captures the screen, shots.py finds the zoom and encodes the pair; this module decides when.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from . import shots
from .activity import describe
from .grab import Capture, CaptureError, CaptureUnavailable, Streaming
from .model import Kind, MediaRef, Message, ShotLevel
from .shots import Frame, Point
from .store import Store

log = logging.getLogger(__name__)

Emit = Callable[[Kind, dict[str, Any], ShotLevel | None], Message]


class Screens:
    TICK_S = 1.0               # firehose: how often the screen is looked at while a tool runs
    STREAM_FPS = 2             # ... through a stream this fast, so a look reads its latest frame instead of taking one
    TURN_END_WAIT_S = 10.0     # the longest a turn's end waits for the shots still being made

    def __init__(self, store: Store, level: Callable[[], ShotLevel], capture: Capture):
        self.store, self._level, self.capture = store, level, capture
        self.emit: Emit | None = None            # set by the conversation: makes the chat message
        self._lock = asyncio.Lock()              # one capture at a time, so each knows the one before it
        self._last: Frame | None = None          # the latest capture: what the next zoom compares against
        self._turn_base: Frame | None = None     # the turn's first capture: what its end compares against
        self._tracker: shots.ChangeTracker | None = None    # what keeps changing on its own, while watching
        self._running: dict[str, str] = {}       # tools running at firehose level, and their captions
        self._idle = asyncio.Event()             # set when the last of them finishes, so watching stops at once
        self._watcher: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._off = False                        # captures can't work in this process (the chat was told once)
        self._failing = False                    # the last capture failed (logged once, until one works)

    @property
    def level(self) -> ShotLevel:
        return ShotLevel.NONE if self._off else self._level()

    def wants(self, level: ShotLevel) -> bool:
        return self.level >= level

    async def shot(self, level: ShotLevel, caption: str, hint: Point | None = None) -> Message | None:
        """Capture now and post the pair, if a page wants `level`. The zoom shows what changed since the capture
        before, else `hint` (screen pixels), else the front window."""
        if not self.wants(level) or self.emit is None:
            return None
        taken = await self._take()
        return None if taken is None else await self._post(level, caption, *taken, hint=hint)

    # --- turns -----------------------------------------------------------------------------------------------------
    def turn_started(self) -> None:
        """Take the turn's first capture, in the background: the turn's end is compared with it."""
        self._turn_base = None
        if self.wants(ShotLevel.MAJOR) and self.emit is not None:
            self._spawn(self._take_turn_base(), "shot-turn-start")

    async def _take_turn_base(self) -> None:
        taken = await self._take()
        if taken is not None:
            self._turn_base = taken[1]

    async def turn_ended(self, caption: str = "Where things ended up") -> None:
        """Stop watching, let the shots still being made finish, then post where things ended up (major) if the
        screen changed during the turn."""
        self._running.clear()                    # a tool cut short by an interrupt never reports back
        self._idle.set()
        if self._tasks:
            await asyncio.wait(set(self._tasks), timeout=self.TURN_END_WAIT_S)
        base, self._turn_base = self._turn_base, None
        if base is not None and self.wants(ShotLevel.MAJOR) and self.emit is not None:
            taken = await self._take()
            if taken is not None:
                await self._post(ShotLevel.MAJOR, caption, base, taken[1], only_if_changed=True)
        self._tracker = None

    # --- tool calls (Agent SDK hooks) ------------------------------------------------------------------------------
    def before_tool(self, tool_use_id: str, tool: str, args: dict[str, Any]) -> None:
        """A tool is about to run. Nothing is captured (Claude would wait for it); at firehose level, watching
        starts."""
        if self.wants(ShotLevel.FIREHOSE) and self.emit is not None:
            self._running[tool_use_id] = describe(tool, args)
            self._idle.clear()
            if self._watcher is None:
                self._watcher = self._spawn(self._watch(), "shots-firehose")

    def after_tool(self, tool_use_id: str, tool: str, args: dict[str, Any]) -> None:
        """A tool finished: its shot (minor) is made in the background, and this returns at once."""
        if self._running.pop(tool_use_id, None) is not None and not self._running:
            self._idle.set()
        if self.wants(ShotLevel.MINOR) and self.emit is not None:
            self._spawn(self.shot(ShotLevel.MINOR, describe(tool, args)), "shot-after-tool")

    def hooks(self) -> dict[str, Any]:
        """Agent SDK hook callbacks for before and after every tool call. Both return at once."""
        async def pre(data: dict[str, Any], tool_use_id: str | None, _ctx: Any) -> dict[str, Any]:
            if tool_use_id:
                self.before_tool(tool_use_id, data.get("tool_name", ""), data.get("tool_input") or {})
            return {}

        async def post(data: dict[str, Any], tool_use_id: str | None, _ctx: Any) -> dict[str, Any]:
            if tool_use_id:
                self.after_tool(tool_use_id, data.get("tool_name", ""), data.get("tool_input") or {})
            return {}

        return {"pre": pre, "post": post}

    async def _watch(self) -> None:
        """Look at the screen every TICK_S while tools run at firehose level. A capture that streams opens its
        stream at the first look, so tools quicker than a tick never open it."""
        streaming = False
        try:
            while True:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._idle.wait(), self.TICK_S)
                if not self._running or not self.wants(ShotLevel.FIREHOSE):
                    return
                if not streaming and isinstance(self.capture, Streaming):
                    await self.capture.watch(self.STREAM_FPS)
                    streaming = True
                await self._look(next(reversed(self._running.values())))
        finally:
            self._watcher = None                 # a tool starting from here on starts a new watcher
            if streaming:
                await self.capture.unwatch()

    async def _look(self, caption: str) -> None:
        """One firehose look: the latest frame is posted if it changed from the capture before it, beyond what
        keeps changing on its own (which the tracker learns from the looks)."""
        if self._tracker is None:
            self._tracker = shots.ChangeTracker()
        tracker = self._tracker
        take = self.capture.latest if isinstance(self.capture, Streaming) else self.capture.grab
        async with self._lock:
            frame = await self._capture(take)
            if frame is None:
                return
            fresh = frame.pixels is not tracker.prev     # a stream gives the same frame again while nothing changed
            before = self._last
            if fresh:
                self._last = frame
        await asyncio.to_thread(tracker.update, frame.pixels)
        if fresh:
            await self._post(ShotLevel.FIREHOSE, caption, before, frame, only_if_changed=True)

    # --- capturing and posting -------------------------------------------------------------------------------------
    async def _take(self) -> tuple[Frame | None, Frame] | None:
        """A capture now, and the one before it; None when it failed."""
        async with self._lock:
            frame = await self._capture(self.capture.grab)
            if frame is None:
                return None
            before, self._last = self._last, frame
            return before, frame

    async def _capture(self, take: Callable[[], Awaitable[Frame]]) -> Frame | None:
        """`take()`, or None when it failed: logged once until a capture works again, or, when no capture can work
        in this process, screenshots off for good."""
        try:
            frame = await take()
        except CaptureUnavailable as exc:
            self._turn_off(str(exc))
            return None
        except CaptureError as exc:
            if not self._failing:
                log.warning("no screenshot: %s", exc)
            self._failing = True
            return None
        self._failing = False
        return frame

    async def _post(self, level: ShotLevel, caption: str, before: Frame | None, frame: Frame, *,
                    hint: Point | None = None, only_if_changed: bool = False) -> Message | None:
        """Make the pair, zoomed on what changed since `before`, and put it in the chat."""
        noise = self._tracker.noise if self._tracker is not None else None
        pair = await asyncio.to_thread(shots.make_pair, before.pixels if before else None, frame.pixels, hint=hint,
                                       window=frame.window, noise=noise, preset=shots.PRESETS[level.label],
                                       require_change=only_if_changed)
        if pair is None or self.emit is None:
            return None
        full, zoom = await asyncio.to_thread(self._keep, pair)
        return self.emit(Kind.SHOTS, {"level": level.label, "caption": caption[:200], "full": full.wire(),
                                      "zoom": zoom.wire(), "rect": list(pair.rect), "screen": list(pair.screen),
                                      "changed": pair.changed}, level)

    def _keep(self, pair: shots.Pair) -> tuple[MediaRef, MediaRef]:
        return (self.store.put_media(pair.full, "webp", w=pair.full_size[0], h=pair.full_size[1]),
                self.store.put_media(pair.zoom, "webp", w=pair.zoom_size[0], h=pair.zoom_size[1]))

    def _turn_off(self, why: str) -> None:
        """No capture can work in this process: no more screenshots, and the chat hears why, once."""
        if self._off:
            return
        self._off = True
        log.warning("screenshots off: %s", why)
        if self.emit is not None:
            self.emit(Kind.NOTICE, {"level": "warn", "text": why}, None)

    # --- background tasks ------------------------------------------------------------------------------------------
    def _spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._reaped)
        return task

    def _reaped(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception():
            log.error("screenshot task %s failed", task.get_name(), exc_info=task.exception())

    async def close(self) -> None:
        """Stop: drop the shots still being made, stop watching, and close the capture's helper."""
        self._running.clear()
        self._idle.set()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(self.capture, Streaming):
            await self.capture.close()
