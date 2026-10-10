"""Whole turns through the WebSocket: the real voice worker process (with its stand-in engines), a scripted Claude,
and a page played by the test."""

import asyncio
import functools
import json
import shutil
import sys
import wave

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.config import Config
from harness.studio import Studio
from harness.studio.agent import TextDelta, TextDone, ToolDone, ToolStart, TurnDone
from harness.studio.model import Kind
from harness.studio.shots import Frame
from harness.studio.speech import VoiceWorker
from harness.web import App

PW = "correct horse battery"
FRAME = b"\x01" + bytes(640)            # 20 ms of silence at 16 kHz


class FakeAgent:
    """Plays a script per turn; a step that is a coroutine function is awaited (a tool's side effect)."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.script = lambda prompt: [TurnDone("ok", True, 0.0, "s1")]
        self.session_id = None
        self.interrupted = asyncio.Event()

    async def turn(self, prompt):
        self.prompts.append(prompt)
        for step in self.script(prompt):
            if callable(step):
                await step()
            else:
                yield step

    async def interrupt(self):
        self.interrupted.set()

    async def close(self):
        pass


class FakeCapture:
    def __init__(self) -> None:
        self.n = 0

    async def grab(self):
        self.n += 1
        px = np.zeros((360, 640, 3), np.uint8)
        px[100:180, 40 + 20 * self.n: 200 + 20 * self.n] = 220      # something moves on every capture
        return Frame(px, asyncio.get_running_loop().time())


async def no_narration(_prompt):
    return ""


def tone(path, seconds=1.0, rate=44100):
    t = np.arange(int(seconds * rate)) / rate
    pcm = (0.3 * np.sin(2 * np.pi * 110 * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return path


@pytest.fixture
async def rig(tmp_path):
    cfg = Config(jobs_dir=tmp_path / "jobs", workdir=tmp_path, skrng_dir=tmp_path / "skrng",
                 studio_dir=tmp_path / "studio", steps_port=0)
    worker = VoiceWorker([sys.executable, "-m", "voice.worker", "--tts", "fake", "--stt", "fake", "serve"],
                         env={"VOICE_FAKE_TEXT": "make the kick louder tomato", "VOICE_FAKE_AFTER_S": "0.4"})
    agent = FakeAgent()
    studio = Studio(cfg, worker=worker, agent=agent, capture=FakeCapture(), summarize=no_narration)
    studio.screens.REUSE_S = 0          # the scripted turns are instant: take a fresh capture every time
    app = App(cfg, None, cfg.skrng_dir, secure_cookie=False, studio=studio)
    client = TestClient(TestServer(app.build()))
    await client.start_server()
    await client.post("/login", data={"password": PW, "confirm": PW, "next": "/"})
    assert await worker.wait_ready(20), "the voice worker did not start"
    yield client, studio, agent, tmp_path
    await client.close()


class Page:
    """The test's side of the socket: everything it received, and a way to wait for something."""

    def __init__(self, ws):
        self.ws, self.msgs, self.audio = ws, [], 0

    def mark(self) -> int:
        """Where the page is now: pass it to until(since=...) to wait for something that happens after it."""
        return len(self.msgs)

    async def until(self, pred, timeout=10.0, since=0):
        for m in self.msgs[since:]:
            if pred(m):
                return m
        async def wait():
            while True:
                frame = await self.ws.receive()
                if frame.type.name == "BINARY":
                    assert frame.data[0] == 0x02
                    self.audio += 1
                    continue
                m = json.loads(frame.data)
                self.msgs.append(m)
                if pred(m):
                    return m
        try:
            return await asyncio.wait_for(wait(), timeout)
        except TimeoutError:
            seen = "\n".join(json.dumps(m)[:200] for m in self.msgs)
            raise AssertionError(f"timed out; received:\n{seen}") from None

    def of(self, kind):
        return [m for m in self.msgs if m["type"] == kind]


def upsert(kind, **data):
    return lambda m: m["type"] == "upsert" and m["message"]["kind"] == kind and all(
        m["message"]["data"].get(k) == v for k, v in data.items())


async def connect(client, prefs=None):
    ws = await client.ws_connect("/studio/ws")
    page = Page(ws)
    await ws.send_json({"type": "hello", "client": "phone", "prefs": prefs or {"autoplay": True, "shots": "minor"}})
    await page.until(lambda m: m["type"] == "welcome")
    return page


async def talk(page, seconds=0.6):
    for _ in range(int(seconds / 0.02)):
        await page.ws.send_bytes(FRAME)


async def test_unauthenticated_socket_is_refused(rig):
    client, *_ = rig
    client.session.cookie_jar.clear()
    r = await client.get("/studio/ws")
    assert r.status == 401
    assert (await client.get("/studio/", allow_redirects=False)).status == 302


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_a_spoken_turn_end_to_end(rig):
    client, studio, agent, tmp = rig
    wav = tone(tmp / "ab.wav")

    async def render():
        await studio.conversation.present_music(wav, "Kick +2 dB", {"bar_seconds": 0.5, "bars": 2, "first": "A",
                                                                  "every": 1, "labels": {"A": "now", "B": "+2 dB"}}, "")

    bash = {"command": "echo render", "description": "Render the A/B"}
    agent.script = lambda prompt: [
        TextDelta(0, "Sure, a louder kick. "), TextDelta(0, "Rendering it now."),
        TextDone(0, "Sure, a louder kick. Rendering it now."),
        ToolStart("t1", "Bash", bash),
        functools.partial(studio.screens.before_tool, "t1", "Bash", bash),    # what the SDK's hooks do
        render,
        functools.partial(studio.screens.after_tool, "t1", "Bash", bash),
        ToolDone("t1", "Bash", True, "done"),
        TextDelta(1, "Here it is."), TextDone(1, "Here it is."),
        TurnDone("Here it is.", True, 0.01, "sess-1"),
    ]
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    await talk(page)
    user = await page.until(upsert("user"))
    assert user["message"]["data"]["text"] == "make the kick louder tomato"   # the stand-in keeps the stop word
    assert page.of("caption") and await page.until(lambda m: m["type"] == "unlisten")
    assert agent.prompts == ["make the kick louder tomato"]

    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "responding")
    begins = [m for m in page.msgs if m["type"] == "speech" and m["state"] == "begin"]
    await page.until(lambda m: m["type"] == "speech" and m["state"] == "end" and m["stream"] == begins[-1]["stream"])
    assert len(begins) == 2 and page.audio > 0
    music = await page.until(upsert("music"))
    assert music["message"]["data"]["audio"]["type"] == "audio/flac"
    play = await page.until(lambda m: m["type"] == "play")
    assert play == {"type": "play", "seq": music["message"]["seq"], "loops": 1}
    assert (await page.until(upsert("activity", status="ok")))["message"]["data"]["title"] == "Render the A/B"
    shot = (await page.until(upsert("shots", level="minor")))["message"]["data"]
    assert shot["caption"] == "Render the A/B" and shot["full"]["type"] == "image/webp" and shot["changed"]
    assert (await page.until(upsert("shots", level="major")))["message"]["data"]["caption"] == "Where things ended up"

    # The mic waits for the phone: three items were sent (two speech streams and one play)...
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 2})
    await asyncio.sleep(0.2)
    assert studio.conversation.phase.value == "responding"
    # ...and opens once all three are played.
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 3})
    await page.until(lambda m: m["type"] == "listen" and m["turn"] != user["message"]["turn"])

    # The speech bubbles get their replay files, and the turn was timed.
    replay = await page.until(lambda m: m["type"] == "upsert" and m["message"]["kind"] == "agent"
                              and m["message"]["data"].get("audio"))
    media = await client.get(replay["message"]["data"]["audio"]["url"])
    assert media.status == 200 and "immutable" in media.headers["Cache-Control"]
    names = [mk["name"] for t in studio.store.timings(5) for mk in t["marks"]]
    assert {"listen", "first_words", "stop_word", "first_text", "first_audio", "agent_done", "responded"} <= set(names)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_play_again_is_handled_without_claude(rig):
    client, studio, agent, tmp = rig
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    music = await studio.conversation.present_music(tone(tmp / "a.wav"), "A", None, "")
    await page.until(lambda m: m["type"] == "play")
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 1})

    await page.ws.send_json({"type": "say", "text": "Loop that three times"})
    play = await page.until(lambda m: m["type"] == "play" and m["loops"] == 3)
    assert play["seq"] == music.seq and agent.prompts == []
    now = page.mark()
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 1})   # counting restarted at the stop
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "listening", since=now)

    # Claude hears about it on its next turn.
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "What did you change?"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "responding", since=now)
    assert "played" in agent.prompts[0] and agent.prompts[0].endswith("What did you change?")


async def test_interrupt_stops_claude_and_returns_the_mic(rig):
    client, studio, agent, _ = rig

    async def long_work():
        await agent.interrupted.wait()

    agent.script = lambda prompt: [ToolStart("t1", "Bash", {"command": "sleep 100"}), long_work,
                                   TurnDone("interrupted", False, 0.0, "s1")]
    page = await connect(client, {"autoplay": True, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    await page.ws.send_json({"type": "say", "text": "do something long"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "working" and m["label"] == "sleep 100")
    now = page.mark()
    await page.ws.send_json({"type": "interrupt"})
    await page.until(lambda m: m["type"] == "stop_audio", since=now)
    await page.until(lambda m: m["type"] == "listen", since=now)
    assert not page.of("notice") or all("stopped" not in n["text"] for n in page.of("notice"))
    assert (await page.until(upsert("activity", status="error")))


async def test_history_pages_and_a_new_conversation(rig):
    client, studio, *_ = rig
    conv = studio.conversation
    for i in range(45):
        conv.add(Kind.NOTICE, {"level": "info", "text": f"n{i}"})
    page = await connect(client)
    welcome = page.of("welcome")[0]
    items = welcome["page"]["items"]
    assert len(items) == 40 and welcome["page"]["has_more"] and items[-1]["data"]["text"] == "n44"
    older = await (await client.get(f"/studio/api/messages?before={items[0]['seq']}&limit=30")).json()
    assert [m["data"]["text"] for m in older["items"]] == [f"n{i}" for i in range(5)] and not older["has_more"]
    r = await client.post("/studio/api/conversation")
    assert r.status == 200
    await page.until(lambda m: m["type"] == "reset")
    fresh = await (await client.get("/studio/api/messages")).json()
    assert fresh == {"items": [], "has_more": False}
