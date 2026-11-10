"""When screenshots are taken: never holding a tool up, compared with the capture before, posted at turn end only
if something changed, and at firehose level only when something changed."""

import asyncio
import logging
import time

import numpy as np
import pytest

from harness.studio.grab import CaptureError, CaptureUnavailable, NO_PERMISSION
from harness.studio.model import Kind, Message, ShotLevel
from harness.studio.screens import Screens
from harness.studio.shots import Frame
from harness.studio.store import Store


class Screen:
    """A 480 x 360 screen whose captures take `delay` seconds and show it as it was when asked."""

    def __init__(self, delay: float = 0.0):
        self.delay, self.grabs = delay, 0
        self.pixels = np.zeros((360, 480, 3), np.uint8)

    def paint(self, x: int, y: int, w: int, h: int) -> None:
        pixels = self.pixels.copy()
        pixels[y:y + h, x:x + w] = 220
        self.pixels = pixels

    async def grab(self) -> Frame:
        self.grabs += 1
        pixels = self.pixels
        await asyncio.sleep(self.delay)
        return Frame(pixels, time.monotonic())


class StreamingScreen(Screen):
    """... that can also stream: latest() hands back the same Frame while nothing changed."""

    def __init__(self) -> None:
        super().__init__()
        self.watches = self.unwatches = 0
        self.closed = False
        self._frame: Frame | None = None

    async def watch(self, fps: int) -> None:
        self.watches += 1

    async def latest(self) -> Frame:
        if self._frame is None or self._frame.pixels is not self.pixels:
            self._frame = Frame(self.pixels, time.monotonic())
        return self._frame

    async def unwatch(self) -> None:
        self.unwatches += 1

    async def close(self) -> None:
        self.closed = True


class Chat:
    """What Screens posts."""

    def __init__(self, store: Store):
        self.store, self.messages = store, []

    def __call__(self, kind: Kind, data: dict, level: ShotLevel | None) -> Message:
        msg = self.store.add(Message(kind, data))
        self.messages.append(msg)
        return msg

    def shots(self, level: str | None = None) -> list[dict]:
        return [m.data for m in self.messages if m.kind is Kind.SHOTS and level in (None, m.data["level"])]

    def notices(self) -> list[dict]:
        return [m.data for m in self.messages if m.kind is Kind.NOTICE]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    yield s
    s.close()


def screens_for(store: Store, screen, level: ShotLevel) -> tuple[Screens, Chat]:
    screens = Screens(store, lambda: level, screen)
    screens.emit = chat = Chat(store)
    screens.TICK_S = 0.05
    return screens, chat


async def timed(coro) -> float:
    t0 = time.perf_counter()
    await coro
    return time.perf_counter() - t0


def tool(name: str = "Bash", **args) -> dict:
    return {"tool_name": name, "tool_input": args or {"command": "make it louder", "description": "Make it louder"}}


async def test_the_hooks_return_at_once_and_the_shot_follows(store):
    screen = Screen(delay=0.3)
    screens, chat = screens_for(store, screen, ShotLevel.MINOR)
    hooks = screens.hooks()
    screens.turn_started()
    await asyncio.sleep(0.01)                                    # the turn's first capture is under way

    assert await timed(hooks["pre"](tool(), "t1", None)) < 0.05
    assert screen.grabs == 1                                     # the hook before a tool captures nothing
    screen.paint(100, 100, 120, 60)                              # what the tool did
    assert await timed(hooks["post"](tool(), "t1", None)) < 0.05
    assert chat.shots() == []                                    # its shot is still being made

    await screens.turn_ended()
    minor, major = chat.shots("minor"), chat.shots("major")
    assert len(minor) == 1 and minor[0]["caption"] == "Make it louder" and minor[0]["changed"]
    x, y, w, h = minor[0]["rect"]                                # compared with the turn's first capture
    assert x <= 100 and y <= 100 and x + w >= 220 and y + h >= 160 and w * 3 == h * 4
    assert minor[0]["screen"] == [480, 360] and minor[0]["full"]["w"] == 480
    assert minor[0]["zoom"]["type"] == "image/webp"
    assert len(major) == 1 and major[0]["caption"] == "Where things ended up"


async def test_a_turn_end_is_posted_only_if_the_screen_changed(store):
    screen = Screen()
    screens, chat = screens_for(store, screen, ShotLevel.MAJOR)
    screens.turn_started()
    await asyncio.sleep(0.01)
    await screens.turn_ended()
    assert chat.shots() == []

    screens.turn_started()
    await asyncio.sleep(0.01)
    screen.paint(300, 200, 100, 100)
    await screens.turn_ended()
    assert [s["changed"] for s in chat.shots("major")] == [True]


async def test_at_major_level_tools_capture_nothing(store):
    screen = Screen()
    screens, chat = screens_for(store, screen, ShotLevel.MAJOR)
    hooks = screens.hooks()
    screens.turn_started()
    for i in range(3):
        await hooks["pre"](tool(), f"t{i}", None)
        await hooks["post"](tool(), f"t{i}", None)
    await screens.turn_ended()
    assert screen.grabs == 2 and chat.shots() == []              # the turn's first and last; nothing changed


async def test_firehose_posts_only_what_changed(store):
    screen = StreamingScreen()
    screens, chat = screens_for(store, screen, ShotLevel.FIREHOSE)
    hooks = screens.hooks()
    screens.turn_started()
    await asyncio.sleep(0.01)

    await hooks["pre"](tool(), "quick", None)                    # a tool quicker than a tick...
    await hooks["post"](tool(), "quick", None)
    await asyncio.sleep(0.15)
    assert screen.watches == 0                                   # ...never opens the stream

    await hooks["pre"](tool(description="Render the A/B"), "long", None)
    await asyncio.sleep(0.3)                                     # a few looks at a still screen
    assert screen.watches == 1 and chat.shots("firehose") == []
    screen.paint(40, 60, 200, 100)
    await asyncio.sleep(0.3)                                     # a change, then more still looks
    fire = chat.shots("firehose")
    assert len(fire) == 1 and fire[0]["changed"] and fire[0]["caption"] == "Render the A/B"
    assert fire[0]["full"]["w"] == 480                           # small screens are never enlarged
    await hooks["post"](tool(description="Render the A/B"), "long", None)
    await asyncio.sleep(0.1)
    assert screen.unwatches == 1                                 # the stream closes with the last tool

    await screens.turn_ended()
    assert len(chat.shots("firehose")) == 1
    assert len(chat.shots("minor")) == 2                         # one per tool, changed or not
    assert len(chat.shots("major")) == 1


async def test_without_screen_recording_screenshots_turn_off_with_one_notice(store):
    class NoPermission(Screen):
        async def grab(self) -> Frame:
            self.grabs += 1
            raise CaptureUnavailable(NO_PERMISSION)

    screen = NoPermission()
    screens, chat = screens_for(store, screen, ShotLevel.MINOR)
    screens.turn_started()
    await asyncio.sleep(0.01)
    screens.after_tool("t1", "Bash", {})
    assert await screens.shot(ShotLevel.MAJOR, "Look") is None
    await screens.turn_ended()
    assert screens.level is ShotLevel.NONE and screen.grabs == 1
    assert chat.notices() == [{"level": "warn", "text": NO_PERMISSION}] and "tmux" in NO_PERMISSION


async def test_a_failing_capture_is_logged_once_until_one_works(store, caplog):
    class Flaky(Screen):
        fail = True

        async def grab(self) -> Frame:
            if self.fail:
                raise CaptureError("the helper died")
            return await super().grab()

    screen = Flaky()
    screens, _ = screens_for(store, screen, ShotLevel.MAJOR)
    with caplog.at_level(logging.WARNING, logger="harness.studio.screens"):
        for _ in range(3):
            assert await screens.shot(ShotLevel.MAJOR, "Look") is None
        screen.fail = False
        assert await screens.shot(ShotLevel.MAJOR, "Look") is not None
    assert [r.message for r in caplog.records] == ["no screenshot: the helper died"]
    assert screens.level is ShotLevel.MAJOR                      # a passing failure doesn't turn them off


async def test_close_stops_watching_and_the_capture(store):
    screen = StreamingScreen()
    screens, _ = screens_for(store, screen, ShotLevel.FIREHOSE)
    await screens.hooks()["pre"](tool(), "t1", None)
    await asyncio.sleep(0.12)
    assert screen.watches == 1
    await screens.close()
    assert screen.unwatches == 1 and screen.closed
