"""Whole turns through the WebSocket: the real voice worker process (with its stand-in engines), a scripted Claude,
and a page played by the test."""

import asyncio
import functools
import json
import re
import shutil
import sys
import wave

import numpy as np
import pytest
from aiohttp.test_utils import TestClient, TestServer

from harness.config import Config
from harness.studio import Studio, tools
from harness.studio.agent import TextDelta, TextDone, ThinkingDelta, ThinkingDone, ToolDone, ToolStart, TurnDone
from harness.studio.model import Kind
from harness.studio.narrator import Narrator
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


def spoken(worker) -> list[str]:
    """Every piece of text the speaker has synthesised from now on, in order (the stand-in voice is only a tone)."""
    said: list[str] = []
    synthesize = worker.synthesize

    def spy(text, voice, speed):
        said.append(text)
        return synthesize(text, voice, speed)

    worker.synthesize = spy
    return said


def items(page, since=0):
    """What the phone was given to play, in order: ("speech", seq) for a stream, ("play", seq, loops) for a play.
    Streams never interleave: each ends before the next item begins."""
    out, open_stream = [], None
    for m in page.msgs[since:]:
        if m["type"] == "speech":
            assert (open_stream is None) == (m["state"] == "begin"), f"streams overlap at {m}"
            open_stream = m["stream"] if m["state"] == "begin" else None
            if m["state"] == "begin":
                out.append(("speech", m["seq"]))
        elif m["type"] == "play":
            assert open_stream is None, f"a play inside stream {open_stream}"
            out.append(("play", m["seq"], m["loops"]))
    return out


def studio_tools(conversation, monkeypatch):
    """The studio tools' handlers by name, to call them as Claude does."""
    handlers = {}
    monkeypatch.setattr(tools, "create_sdk_mcp_server",
                        lambda name, tools: handlers.update({t.name: t.handler for t in tools}))
    tools.server(conversation)
    return handlers


def answer(result) -> str:
    return result["content"][0]["text"]


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
    hooks, call = studio.screens.hooks(), {"tool_name": "Bash", "tool_input": bash}
    agent.script = lambda prompt: [
        TextDelta(0, "Sure, a louder kick. "), TextDelta(0, "Rendering it now."),
        TextDone(0, "Sure, a louder kick. Rendering it now."),
        ToolStart("t1", "Bash", bash),
        functools.partial(hooks["pre"], call, "t1", None),        # what the SDK does around the tool
        render,
        functools.partial(hooks["post"], call, "t1", None),
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
    music = await page.until(upsert("music"))
    assert music["message"]["data"]["audio"]["type"] == "audio/mpeg"
    play = await page.until(lambda m: m["type"] == "play")
    assert play == {"type": "play", "seq": music["message"]["seq"], "loops": 1}
    # The render waited for the turn's end: Claude's two replies, then its intro (spoken for the card), then it.
    begins = [m for m in page.msgs if m["type"] == "speech" and m["state"] == "begin"]
    assert [m["seq"] == music["message"]["seq"] for m in begins] == [False, False, True] and page.audio > 0
    assert (await page.until(upsert("activity", status="ok")))["message"]["data"]["title"] == "Render the A/B"
    shot = (await page.until(upsert("shots", level="minor")))["message"]["data"]
    assert shot["caption"] == "Render the A/B" and shot["full"]["type"] == "image/webp" and shot["changed"]
    assert (await page.until(upsert("shots", level="major")))["message"]["data"]["caption"] == "Where things ended up"

    # The mic waits for the phone: four items were sent (three speech streams and one play)...
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 3})
    await asyncio.sleep(0.2)
    assert studio.conversation.phase.value == "responding"
    # ...and opens once all four are played.
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 4})
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
    said = spoken(studio.worker)
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    music = await studio.conversation.present_music(tone(tmp / "a.wav"), "A", None, "")
    await page.until(lambda m: m["type"] == "play")
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 2})

    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "Loop that three times"})
    play = await page.until(lambda m: m["type"] == "play" and m["loops"] == 3, since=now)
    assert play["seq"] == music.seq and agent.prompts == []
    # A replay's intro is short: "Again", the title and the count-in, said once for all three loops.
    assert items(page, now) == [("speech", music.seq), ("play", music.seq, 3)]
    assert said[-2:] == ["Again: A.", "Three, two, one."]
    now = page.mark()
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 2})   # counting restarted at the stop
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "listening", since=now)

    # Claude hears about it on its next turn.
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "What did you change?"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "responding", since=now)
    assert "played" in agent.prompts[0] and agent.prompts[0].endswith("What did you change?")


async def test_thinking_is_kept_in_the_chat_and_never_spoken(rig):
    client, studio, agent, _ = rig
    agent.script = lambda prompt: [
        ThinkingDelta(0, "He wants the kick "), ThinkingDelta(0, "louder; check its chain first."),
        ThinkingDone(0, "He wants the kick louder; check its chain first."),
        ToolStart("t1", "Read", {"file_path": "/x/kick-chain.json"}), ToolDone("t1", "Read", True, "{}"),
        ThinkingDelta(2, "Three dB is enough."),                 # never finished: the turn ends first
        TextDelta(3, "Done."), TextDone(3, "Done."),
        TurnDone("Done.", True, 0.0, "s1"),
    ]
    page = await connect(client, {"autoplay": True, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    await page.ws.send_json({"type": "say", "text": "louder kick"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "responding")
    await page.until(lambda m: m["type"] == "speech" and m["state"] == "end")
    begins = [m for m in page.msgs if m["type"] == "speech" and m["state"] == "begin"]
    assert len(begins) == 1                                     # only the reply is spoken
    stored = [(m.kind, m.data) for m in studio.store.page(studio.conversation.conv.id, None, 20)[0]]
    assert [k for k, _ in stored] == [Kind.USER, Kind.THINKING, Kind.ACTIVITY, Kind.THINKING, Kind.AGENT]
    assert stored[1][1] == {"text": "He wants the kick louder; check its chain first.", "streaming": False}
    assert stored[3][1] == {"text": "Three dB is enough.", "streaming": False}
    final = await page.until(upsert("thinking", streaming=False))
    assert final["message"]["data"]["text"].startswith("He wants")


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


async def test_the_page_carries_the_newest_history_and_its_files_are_cached_for_good(rig):
    client, studio, *_ = rig
    for i in range(45):
        studio.conversation.add(Kind.NOTICE, {"level": "info", "text": f"n{i}"})
    r = await client.get("/studio/")
    html = await r.text()
    assert r.headers["Cache-Control"] == "no-cache" and r.headers["Content-Encoding"] == "gzip"
    boot = json.loads(re.search(r'<script type="application/json" id="boot">(.*?)</script>', html).group(1))
    assert len(boot["items"]) == 40 and boot["has_more"] and boot["items"][-1]["data"]["text"] == "n44"
    assert boot["conversation"] == studio.conversation.conv.id

    version = re.search(r'"/studio/static/([0-9a-f]{12})/js/main\.js"', html).group(1)
    assert f'<link rel="modulepreload" href="/studio/static/{version}/js/view.js">' in html
    assert f'href="/studio/static/{version}/app.css"' in html
    js = await client.get(f"/studio/static/{version}/js/main.js")
    assert js.status == 200 and js.headers["Content-Encoding"] == "gzip" and "immutable" in js.headers["Cache-Control"]
    assert js.content_type == "text/javascript" and "showBoot" in await js.text()
    # A page from before a deploy asks under its old version: it gets today's file, revalidated rather than kept.
    old = await client.get("/studio/static/0123456789ab/js/main.js")
    assert old.status == 200 and old.headers["Cache-Control"] == "no-cache"
    assert (await client.get(f"/studio/static/{version}/js/nothing.js")).status == 404

    api = await client.get("/studio/api/messages?limit=40")
    assert api.headers["Content-Encoding"] == "gzip" and len((await api.json())["items"]) == 40


async def test_a_claude_that_ignores_the_interrupt_is_dropped(rig, monkeypatch):
    client, studio, agent, _ = rig
    monkeypatch.setattr("harness.studio.conversation.INTERRUPT_S", 0.3)
    closed = []

    async def stuck():
        await asyncio.Event().wait()             # never stops on its own

    async def close():
        closed.append(True)

    agent.interrupt = lambda: asyncio.sleep(0)   # the interrupt goes nowhere
    agent.close = close
    agent.script = lambda prompt: [ToolStart("t1", "Bash", {"command": "hang"}), stuck]
    page = await connect(client, {"autoplay": True, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    await page.ws.send_json({"type": "say", "text": "hang please"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "working" and m["label"] == "hang")
    now = page.mark()
    await page.ws.send_json({"type": "interrupt"})
    await page.until(lambda m: m["type"] == "listen", since=now, timeout=5)
    assert closed == [True]


async def test_the_mic_opens_even_if_the_phone_never_says_it_finished(rig, monkeypatch):
    client, studio, agent, _ = rig
    monkeypatch.setattr("harness.studio.playback.SPEECH_MAX_S", 0.2)
    monkeypatch.setattr("harness.studio.playback.PLAYBACK_SLACK_S", 0.2)
    agent.script = lambda prompt: [TextDelta(0, "Done."), TextDone(0, "Done."), TurnDone("Done.", True, 0, "s")]
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "quick one"})
    await page.until(lambda m: m["type"] == "speech" and m["state"] == "end", since=now)
    await page.until(lambda m: m["type"] == "listen", since=now, timeout=5)    # no playback message was sent


# --- whatever fails, the app gets back to a usable state ---------------------------------------------------------

async def test_a_turn_that_fails_after_claude_is_done_still_gives_the_mic_back(rig):
    client, studio, agent, _ = rig

    async def broken(*_args, **_kw):
        raise OSError("disk full")

    studio.screens.turn_ended = broken                # the turn's last screenshot can't be stored
    page = await connect(client, {"autoplay": True, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "anything"})
    await page.until(lambda m: m["type"] == "listen", since=now, timeout=5)
    assert studio.conversation.phase.value == "listening"


async def test_a_typed_turn_while_the_answer_plays_does_not_open_the_mic(rig):
    client, studio, agent, _ = rig
    agent.script = lambda prompt: [TextDelta(0, "Done."), TextDone(0, "Done."), TurnDone("Done.", True, 0, "s")]
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "first"})
    await page.until(lambda m: m["type"] == "speech" and m["state"] == "end", since=now)
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "responding", since=now)
    await asyncio.sleep(0.2)
    assert studio.conversation.phase.value == "responding"     # the phone hasn't said it played the answer
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "second"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "responding", since=now)
    assert [m for m in page.msgs[now:] if m["type"] == "listen"] == []      # Claude has the turn, not the mic
    assert studio.conversation._listening is None and agent.prompts == ["first", "second"]


async def test_an_interrupt_the_session_never_answers_still_returns_the_mic(rig, monkeypatch):
    client, studio, agent, _ = rig
    monkeypatch.setattr("harness.studio.conversation.INTERRUPT_S", 0.3)
    closed = []

    async def hang():
        await asyncio.Event().wait()             # the CLI never answers the interrupt (the SDK waits 60 s)

    async def close():
        closed.append(True)

    agent.interrupt, agent.close = hang, close
    agent.script = lambda prompt: [ToolStart("t1", "Bash", {"command": "hang"}), hang]
    page = await connect(client, {"autoplay": True, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    await page.ws.send_json({"type": "say", "text": "hang please"})
    await page.until(lambda m: m["type"] == "phase" and m["phase"] == "working" and m["label"] == "hang")
    now = page.mark()
    await page.ws.send_json({"type": "interrupt"})
    await page.ws.send_json({"type": "ping", "t": 1})
    await page.until(lambda m: m["type"] == "pong", since=now, timeout=1)     # the page's socket isn't held up
    await page.until(lambda m: m["type"] == "listen", since=now, timeout=5)
    assert closed == [True]


async def test_the_mic_is_offered_once_speech_is_ready_however_long_that_takes(rig):
    client, studio, agent, _ = rig
    worker, calls = studio.worker, []
    real = worker.wait_ready

    async def slow_start(timeout):
        calls.append(timeout)
        return False if len(calls) == 1 else await real(timeout)    # the first wait runs out (models downloading)

    worker.wait_ready = slow_start
    worker._ready.clear()
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "phase" and m["label"] == "Speech is starting")
    await asyncio.sleep(0.1)
    worker._ready.set()
    await page.until(lambda m: m["type"] == "listen", timeout=5)


async def test_stopping_waits_for_the_conversations_tasks(rig):
    _, studio, *_ = rig
    conv = studio.conversation
    task = conv._spawn(asyncio.sleep(100), "a-wait")
    await conv.stop()
    assert task.done()


async def test_a_page_is_told_when_it_gains_or_loses_the_mic(rig):
    client, *_ = rig
    pages = []
    for name in ("phone", "tv"):
        ws = await client.ws_connect("/studio/ws")
        pages.append(page := Page(ws))
        await ws.send_json({"type": "hello", "client": name, "prefs": {"autoplay": True, "shots": "none"}})
        await page.until(lambda m: m["type"] == "welcome")
    phone, tv = pages
    await phone.ws.send_json({"type": "start"})
    assert (await phone.until(lambda m: m["type"] == "owner"))["owner"] is True
    await phone.until(lambda m: m["type"] == "listen")
    mark = phone.mark()
    await tv.ws.send_json({"type": "start"})
    assert (await tv.until(lambda m: m["type"] == "owner"))["owner"] is True
    assert (await phone.until(lambda m: m["type"] == "owner", since=mark))["owner"] is False
    await phone.until(lambda m: m["type"] == "unlisten", since=mark)
    assert not tv.of("unlisten") and [m["owner"] for m in tv.of("owner")] == [True]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_options_are_checked_against_the_file_and_the_macs_play_is_a_sweep(rig):
    from harness.studio.conversation import play_seconds
    from harness.studio.tools import baked_options

    client, studio, agent, tmp = rig
    raw = {"layout": "slider", "name": "rumble Drive", "bar_seconds": 0.25, "bars": 1, "now": 7,
           "options": [{"label": "0%", "match_db": -1.234, "lufs": -12.0}, {"label": "50%"}, {"label": "100%"},
                       {"label": "x" * 99, "match_db": 2}]}
    opts = baked_options(raw)
    assert opts["now"] is None, "a `now` that is not one of the options is dropped"
    assert opts["options"][0] == {"label": "0%", "match_db": -1.23} and len(opts["options"][3]["label"]) == 40
    for bad in ({**raw, "options": raw["options"][:1]}, {**raw, "bar_seconds": 0}):
        with pytest.raises(ValueError):
            baked_options(bad)

    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    with pytest.raises(ValueError, match="make 1.00 s"):              # 4 x 1 bar x 0.25 s, but the file is 2 s
        await studio.conversation.present_music(tone(tmp / "long.wav", seconds=2.0), "Drive", None, "", options=opts)
    music = await studio.conversation.present_music(tone(tmp / "o.wav", seconds=1.0), "Drive", None, "", options=opts)
    assert music.data["options"]["layout"] == "slider" and music.data["duration"] == pytest.approx(1.0, abs=0.01)
    play = await page.until(lambda m: m["type"] == "play")
    assert play["seq"] == music.seq
    assert play_seconds(music.data) == pytest.approx(1.0), "the Mac's play: one bar of each of the 4 options"
    assert play_seconds({"duration": 3.5}) == 3.5


# --- music waits for Claude's words, and never starts unannounced --------------------------------------------------

PRESENT = "mcp__studio__present_music"


async def until(cond, timeout=5.0):
    """For a script step that waits on the app."""
    t0 = asyncio.get_running_loop().time()
    while not cond():
        assert asyncio.get_running_loop().time() - t0 < timeout, "timed out"
        await asyncio.sleep(0.02)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_music_presented_in_a_turn_plays_after_the_reply_with_its_intro(rig, monkeypatch):
    client, studio, agent, tmp = rig
    said = spoken(studio.worker)
    present = studio_tools(studio.conversation, monkeypatch)["present_music"]
    note = "Nine drive settings, clean to crushed. Listen for when the kick breaks up."
    answers = []

    async def present_it():
        answers.append(await present({"path": str(tone(tmp / "o.wav")), "title": "Rumble drive", "note": note}))

    agent.script = lambda prompt: [
        TextDelta(0, "Baking the drive settings."), TextDone(0, "Baking the drive settings."),
        ToolStart("t1", PRESENT, {"title": "Rumble drive"}), present_it, ToolDone("t1", PRESENT, True, "ok"),
        TextDelta(1, "Here they are."), TextDone(1, "Here they are."),
        TurnDone("Here they are.", True, 0.01, "s1"),
    ]
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "a slider for the rumble drive"})
    await page.until(lambda m: m["type"] == "play", since=now)
    card = await page.until(upsert("music"), since=now)
    seq = card["message"]["seq"]
    replies = sorted({m["message"]["seq"] for m in page.msgs[now:]
                      if m["type"] == "upsert" and m["message"]["kind"] == "agent"})

    # The card is in the chat as soon as it is presented, but nothing plays before Claude has spoken: its two
    # replies, then the intro (a stream of the card's), then the render, with nothing between the two.
    assert items(page, now) == [("speech", replies[0]), ("speech", replies[1]), ("speech", seq), ("play", seq, 1)]
    second = next(i for i, m in enumerate(page.msgs) if m["type"] == "speech" and m["seq"] == replies[1])
    assert page.msgs.index(card) < second
    # The intro is the title, the note and the count-in; and Claude was told when the render would play.
    assert " ".join(said).endswith(f"Here they are. Rumble drive. {note} Three, two, one.")
    assert "when your turn ends, after your reply" in answer(answers[0])

    # Every stream and the play are counted: the mic opens once the phone has played all four.
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 3})
    await asyncio.sleep(0.2)
    assert studio.conversation.phase.value == "responding"
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 4})
    await page.until(lambda m: m["type"] == "listen", since=now)

    # The intro kept no replay (the card's audio is still the render) and added no bubble of its own.
    await page.until(lambda m: m["type"] == "upsert" and m["message"]["seq"] == replies[1]
                     and m["message"]["data"].get("audio"), since=now)
    await asyncio.sleep(0.3)
    stored = studio.store.get(seq).data
    assert stored["audio"] == card["message"]["data"]["audio"] and stored["duration"] == pytest.approx(1.0, abs=0.01)
    assert stored["plays"] == 1
    kinds = [m.kind for m in studio.store.page(studio.conversation.conv.id, None, 20)[0]]
    assert kinds.count(Kind.AGENT) == 2


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_once_music_is_waiting_the_narrator_says_nothing_more(rig, monkeypatch):
    client, studio, agent, tmp = rig
    conv = studio.conversation
    monkeypatch.setattr(Narrator, "QUIET_S", 0.0)
    monkeypatch.setattr(Narrator, "MIN_GAP_S", 0.0)
    asked, release = [], asyncio.Event()

    async def summarize(prompt):
        asked.append(prompt)
        if len(asked) > 1:
            await release.wait()                 # this line is still being written when the render is presented
        return f"Line {len(asked)}."

    conv.narrator._summarize = summarize

    def narrations():
        return [m for m in studio.store.page(conv.conv.id, None, 30)[0] if m.data.get("role") == "narration"]

    async def first_line_spoken():
        await until(lambda: narrations())        # its bubble is made at its first sound

    async def a_line_waits():
        conv._narrate("A line that waits.")      # behind Claude's reply, which is still open

    async def second_line_asked():
        await until(lambda: len(asked) == 2)

    async def present_it():
        waiting = [u for u in conv.speaker._pending if u.droppable]
        await conv.present_music(tone(tmp / "o.wav"), "Rumble drive", None, "Listen to the kick.")
        assert waiting and all(u.cancelled for u in waiting), "the narration waiting was dropped"
        release.set()                            # the line being written comes back, to a hushed narrator
        await asyncio.sleep(0.3)

    async def a_while():
        await asyncio.sleep(1.2)                 # long enough for the narrator to have spoken again (it looks every 0.5 s)

    agent.script = lambda prompt: [
        ToolStart("t1", "Bash", {"description": "Bake the options"}), first_line_spoken,
        ToolDone("t1", "Bash", True, ""),
        TextDelta(0, "Baking. "), a_line_waits,
        ToolStart("t2", "Bash", {"description": "Measure their loudness"}), second_line_asked, present_it,
        ToolDone("t2", "Bash", True, ""),
        TextDone(0, "Baking."),
        ToolStart("t3", "Bash", {"description": "Tidy up"}), a_while, ToolDone("t3", "Bash", True, ""),
        TextDelta(1, "Here it is."), TextDone(1, "Here it is."),
        TurnDone("Here it is.", True, 0.01, "s1"),
    ]
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "a slider for the rumble drive"})
    play = await page.until(lambda m: m["type"] == "play", since=now, timeout=15)

    # One narration, from before the render; the line in flight and the one waiting were dropped, and nothing more
    # was asked after it.
    said = narrations()
    assert [m.data["text"] for m in said] == ["Line 1."] and len(asked) == 2
    replies = sorted({m["message"]["seq"] for m in page.msgs[now:] if m["type"] == "upsert"
                      and m["message"]["kind"] == "agent" and m["message"]["data"].get("role") == "reply"})
    assert items(page, now) == [("speech", said[0].seq), ("speech", replies[0]), ("speech", replies[1]),
                                ("speech", play["seq"]), ("play", play["seq"], 1)]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_music_presented_outside_a_turn_plays_at_once_after_its_intro(rig):
    client, studio, agent, tmp = rig
    said = spoken(studio.worker)
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    music = await studio.conversation.present_music(tone(tmp / "b.wav"), "Bass tail", None, "Listen to the tail.")
    await page.until(lambda m: m["type"] == "play", since=now)
    assert items(page, now) == [("speech", music.seq), ("play", music.seq, 1)]
    assert said == ["Bass tail.", "Listen to the tail.", "Three, two, one."]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_play_music_in_a_turn_plays_after_the_reply_with_a_short_intro(rig, monkeypatch):
    client, studio, agent, tmp = rig
    page = await connect(client)
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    music = await studio.conversation.present_music(tone(tmp / "a.wav"), "Kick drive", None, "Listen to the kick.")
    await page.until(lambda m: m["type"] == "play")
    await page.ws.send_json({"type": "playback", "state": "idle", "done": 2})
    said = spoken(studio.worker)
    play_music = studio_tools(studio.conversation, monkeypatch)["play_music"]
    answers = []

    async def replay():
        answers.append(await play_music({"loops": 2}))

    agent.script = lambda prompt: [
        ToolStart("t1", "mcp__studio__play_music", {"loops": 2}), replay,
        ToolDone("t1", "mcp__studio__play_music", True, "ok"),
        TextDelta(0, "Listen for the tail this time."), TextDone(0, "Listen for the tail this time."),
        TurnDone("ok", True, 0.0, "s1"),
    ]
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "what should I listen for"})
    await page.until(lambda m: m["type"] == "play", since=now)
    reply = next(m["message"]["seq"] for m in page.msgs[now:] if m["type"] == "upsert" and m["message"]["kind"] == "agent")
    assert items(page, now) == [("speech", reply), ("speech", music.seq), ("play", music.seq, 2)]
    assert said == ["Listen for the tail this time.", "Again: Kick drive.", "Three, two, one."]
    assert answer(answers[0]) == (f"Music #{music.seq} (Kick drive) plays 2 time(s) on his phone when your turn "
                                  "ends, after your reply and a short intro.")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_with_autoplay_off_nothing_plays_by_itself_and_a_replay_plays_without_an_intro(rig):
    client, studio, agent, tmp = rig
    said = spoken(studio.worker)

    async def present_it():
        await studio.conversation.present_music(tone(tmp / "a.wav"), "A", None, "Listen.")

    agent.script = lambda prompt: [ToolStart("t1", PRESENT, {}), present_it, ToolDone("t1", PRESENT, True, "ok"),
                                   TextDelta(0, "Here it is."), TextDone(0, "Here it is."), TurnDone("ok", True, 0, "s")]
    page = await connect(client, {"autoplay": False, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "render it"})
    await page.until(lambda m: m["type"] == "listen", since=now)      # nothing was sent to play: the mic is back
    assert items(page, now) == [] and "Three, two, one." not in said
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "play again"})
    play = await page.until(lambda m: m["type"] == "play", since=now)
    assert items(page, now) == [("play", play["seq"], 1)] and "Three, two, one." not in said


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
async def test_an_interrupted_turn_plays_none_of_its_music(rig):
    client, studio, agent, tmp = rig

    async def present_it():
        await studio.conversation.present_music(tone(tmp / "a.wav"), "A", None, "")

    async def until_interrupted():
        await agent.interrupted.wait()

    agent.script = lambda prompt: [ToolStart("t1", PRESENT, {}), present_it, ToolDone("t1", PRESENT, True, "ok"),
                                   ToolStart("t2", "Bash", {"command": "sleep 100"}), until_interrupted,
                                   TurnDone("interrupted", False, 0.0, "s1")]
    page = await connect(client, {"autoplay": True, "shots": "none"})
    await page.ws.send_json({"type": "start"})
    await page.until(lambda m: m["type"] == "listen")
    now = page.mark()
    await page.ws.send_json({"type": "say", "text": "render it"})
    await page.until(lambda m: m["type"] == "phase" and m["label"] == "sleep 100", since=now)
    await page.ws.send_json({"type": "interrupt"})
    await page.until(lambda m: m["type"] == "listen", since=now)
    await asyncio.sleep(0.2)
    assert items(page, now) == []
