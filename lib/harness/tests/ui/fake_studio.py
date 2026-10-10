"""A scripted stand-in for the studio server (docs/studio.md), for the page's browser tests.

It serves the real page (studio/static) and speaks the protocol deterministically, the way the Mac does:
- `hello` gets a `welcome` with the newest page of history;
- `start` makes the page the owner and offers it the mic (phase `listening`, then `listen`);
- mic frames become captions, and after `turn_frames` frames the turn ends as if "tomato" had been heard
  (`end_turn` and `say` end a turn too);
- Claude's turn is `script`: by default activity rows, a narration, a screenshot pair, a reply spoken as a
  streamed tone, and an A/B render that is `play`ed;
- `responding` lasts until the owner reports (`playback` idle with `done` >= the items it was sent) that it
  has played everything; then the mic is offered again;
- `interrupt` cancels the turn and sends `stop_audio`.

Tests read what the page sent (`inbox`, `mic_frames`, `marks`) and can take any step themselves.
Run it by hand to look at the page: `uv run --extra dev python tests/ui/fake_studio.py --port 8790`.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

import studio_media as media

STATIC = Path(__file__).resolve().parents[2] / "src" / "harness" / "studio" / "static"
FIRST_PAGE = 40
LEVELS = {"none": 0, "major": 1, "minor": 2, "firehose": 3}
CAPTION = "make the kick a little louder and play it against the old one"
REPLY = ("I rendered the kick at its current level and three dB louder, switching every bar. "
         "A is the current level, B is the louder one.")
TOOLS = [("Read", "Read kick-chain.json", 120), ("Bash", "Render the kick A/B in Live", 2300),
         ("mcp__studio__present_music", "Present Kick level: now vs +3 dB", 80)]

Script = Callable[[str], Awaitable[None]]


class FakeStudio:
    def __init__(self) -> None:
        self.conversation = {"id": "c-test-1", "created": round(time.time(), 3), "title": ""}
        self.version = "1"
        self.messages: list[dict[str, Any]] = []
        self.media: dict[str, tuple[bytes, str]] = {}
        self.pages: list[web.WebSocketResponse] = []
        self.prefs: dict[web.WebSocketResponse, dict[str, Any]] = {}
        self.owner: web.WebSocketResponse | None = None
        self.inbox: list[dict[str, Any]] = []      # every JSON message a page sent, in order
        self.mic_frames: list[bytes] = []          # every binary frame a page sent, channel byte included
        self.mic_times: list[float] = []           # when each arrived (monotonic seconds)
        self.marks: list[dict[str, Any]] = []
        self.phase, self.turn, self.label = "idle", None, ""
        self.page_delay = 0.0          # how long GET /studio/api/messages takes (to see the spinner)
        self.turn_frames = 25          # mic frames that end a spoken turn (0: only end_turn ends it)
        self.step_s = 0.05             # pause between the scripted steps of Claude's turn
        self.speech_s = 0.6            # how long the spoken reply is
        self.chunk_gap_s = 0.02        # between 100 ms speech chunks (faster than real time, like Kokoro)
        self.bar_s, self.bars, self.loops = 0.5, 2, 2
        self.script: Script = self.claude_turn
        self.sent = 0                  # items sent to the owner to play
        self.done = 0                  # ... that it reported finished or dropped
        self._idle = asyncio.Event()
        self._idle.set()
        self._changed = asyncio.Condition()
        self._seq = itertools.count(1)
        self._turns = itertools.count(1)
        self._streams = itertools.count(1)
        self._shots = itertools.count(0)
        self._listening = False
        self._heard = 0
        self._task: asyncio.Task | None = None

    # --- HTTP ------------------------------------------------------------------------------------------
    def app(self) -> web.Application:
        app = web.Application(client_max_size=1 << 20)
        app.router.add_get("/studio/", self._index)
        app.router.add_get("/studio/static/{path:.+}", self._static)
        app.router.add_get("/studio/media/{name}", self._media)
        app.router.add_get("/studio/api/messages", self._messages)
        app.router.add_get("/studio/api/timings", self._timings)
        app.router.add_post("/studio/api/conversation", self._new_conversation)
        app.router.add_get("/studio/ws", self._socket)
        return app

    async def _index(self, _request: web.Request) -> web.StreamResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def _static(self, request: web.Request) -> web.StreamResponse:
        path = (STATIC / request.match_info["path"]).resolve()
        if not path.is_relative_to(STATIC) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})

    async def _media(self, request: web.Request) -> web.Response:
        if request.match_info["name"] not in self.media:
            raise web.HTTPNotFound()
        data, mime = self.media[request.match_info["name"]]
        return web.Response(body=data, content_type=mime, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    async def _messages(self, request: web.Request) -> web.Response:
        before = int(request.query["before"]) if request.query.get("before") else None
        limit = int(request.query.get("limit", "30"))
        await asyncio.sleep(self.page_delay)
        older = [m for m in self.messages if before is None or m["seq"] < before]
        items = older[-limit:]
        return web.json_response({"items": items, "has_more": len(older) > len(items)})

    async def _timings(self, request: web.Request) -> web.Response:
        turns: dict[str, list[dict[str, Any]]] = {}
        for m in self.marks:
            extra = {k: v for k, v in m.items() if k not in ("type", "turn", "name", "ms")}
            turns.setdefault(m.get("turn") or "?", []).append(
                {"name": m["name"], "ms": m.get("ms"), "source": "phone", "at": time.time(), **extra})
        for marks in turns.values():
            marks.insert(0, {"name": "listen", "ms": 0, "source": "mac", "at": time.time()})
        out = [{"turn": t, "at": time.time(), "marks": ms} for t, ms in reversed(turns.items())]
        return web.json_response(out[: int(request.query.get("turns", "10"))])

    async def _new_conversation(self, _request: web.Request) -> web.Response:
        if self.phase == "working":
            return web.json_response({"error": "Claude is working; interrupt it first."}, status=409)
        self.messages.clear()
        self.conversation = {"id": f"c-test-{next(self._seq)}", "created": round(time.time(), 3), "title": ""}
        self._listening = False
        await self.set_phase("idle")
        await self.broadcast({"type": "reset", "conversation": self.conversation})
        return web.json_response({"conversation": self.conversation})

    # --- the socket --------------------------------------------------------------------------------------
    async def _socket(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(max_msg_size=1 << 20)
        await ws.prepare(request)
        try:
            async for frame in ws:
                if frame.type == WSMsgType.BINARY:
                    self.mic_frames.append(frame.data)
                    self.mic_times.append(time.monotonic())
                    await self._hear(ws, frame.data)
                elif frame.type == WSMsgType.TEXT:
                    msg = json.loads(frame.data)
                    self.inbox.append(msg)
                    await self._handle(ws, msg)
                await self._notify()
        finally:
            if ws in self.pages:
                self.pages.remove(ws)
            self.prefs.pop(ws, None)
            if self.owner is ws:
                self.owner = None
                self._idle.set()
        return ws

    async def _handle(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        kind = msg["type"]
        if kind == "hello":
            self.pages.append(ws)
            self.prefs[ws] = dict(msg.get("prefs") or {})
            page = self.messages[-FIRST_PAGE:]
            await self._send(ws, {"type": "welcome", "conversation": self.conversation, "phase": self.phase,
                                  "turn": self.turn, "label": self.label, "version": self.version,
                                  "owner": self.owner is ws, "speech_ready": True,
                                  "page": {"items": page, "has_more": len(self.messages) > len(page)}})
        elif kind == "prefs":
            self.prefs[ws] = dict(msg["prefs"])
        elif kind == "start":
            self.owner = ws
            self.sent = self.done = 0
            self._idle.set()
            if self.phase in ("idle", "responding"):
                await self.offer_mic()
            elif self.phase == "listening":
                await self._send(ws, {"type": "listen", "turn": self.turn})
        elif kind == "pause":
            self.prefs.setdefault(ws, {})["handsfree"] = False
            if ws is self.owner and self.phase == "listening":
                await self._stop_listening()
                await self.set_phase("idle")
        elif kind == "say":
            await self.user_turn(msg["text"], "typed")
        elif kind == "end_turn":
            if ws is self.owner and self._listening:
                await self._stop_listening()
                await self.user_turn(CAPTION, "voice")
        elif kind == "interrupt":
            await self.interrupt()
        elif kind == "playback":
            if ws is self.owner and isinstance(msg.get("done"), int):
                self.done = max(self.done, msg["done"])
                if self.done >= self.sent and msg["state"] == "idle":
                    self._idle.set()
        elif kind == "mark":
            self.marks.append(msg)
        elif kind == "ping":
            await self._send(ws, {"type": "pong", "t": msg.get("t")})

    async def _hear(self, ws: web.WebSocketResponse, data: bytes) -> None:
        if ws is not self.owner or not self._listening or data[:1] != b"\x01":
            return
        self._heard += 1
        if self._heard % 5 == 0:
            words = CAPTION.split()
            n = min(len(words), self._heard // 5 * 2)
            await self.broadcast({"type": "caption", "turn": self.turn, "text": " ".join(words[:n])})
        if self.turn_frames and self._heard >= self.turn_frames:
            await self._stop_listening()
            await self.user_turn(CAPTION, "voice")

    # --- waiting for the page -------------------------------------------------------------------------
    async def _notify(self) -> None:
        async with self._changed:
            self._changed.notify_all()

    async def expect(self, pred: Callable[[dict[str, Any]], bool], timeout: float = 10.0, since: int = 0) -> dict:
        """The first message the page sent (from index `since`) that matches; waits for it if needed."""
        def found() -> dict | None:
            return next((m for m in self.inbox[since:] if pred(m)), None)

        async with self._changed:
            try:
                await asyncio.wait_for(self._changed.wait_for(lambda: found() is not None), timeout)
            except TimeoutError:
                sent = "\n".join(json.dumps(m)[:160] for m in self.inbox[since:])
                raise AssertionError(f"the page never sent that; it sent:\n{sent}") from None
        return found()

    async def until(self, cond: Callable[[], bool], timeout: float = 10.0) -> None:
        async with self._changed:
            await asyncio.wait_for(self._changed.wait_for(cond), timeout)

    def sent_of(self, kind: str, since: int = 0) -> list[dict[str, Any]]:
        return [m for m in self.inbox[since:] if m["type"] == kind]

    # --- the Mac's side of a turn -----------------------------------------------------------------------
    async def _send(self, ws: web.WebSocketResponse | None, msg: dict[str, Any]) -> None:
        if ws is not None and not ws.closed:
            await ws.send_str(json.dumps(msg))

    async def broadcast(self, msg: dict[str, Any], level: str | None = None) -> None:
        for ws in list(self.pages):
            if level is None or LEVELS[self.prefs.get(ws, {}).get("shots", "major")] >= LEVELS[level]:
                await self._send(ws, msg)

    async def set_phase(self, phase: str, label: str = "") -> None:
        self.phase, self.label = phase, label
        await self.broadcast({"type": "phase", "phase": phase, "turn": self.turn, "label": label})

    async def offer_mic(self) -> None:
        self.turn = f"t{next(self._turns)}"
        self._listening, self._heard = True, 0
        await self.set_phase("listening")
        await self._send(self.owner, {"type": "listen", "turn": self.turn})

    async def _stop_listening(self) -> None:
        self._listening = False
        await self._send(self.owner, {"type": "unlisten", "turn": self.turn})

    async def user_turn(self, text: str, source: str) -> None:
        if self.phase == "working":
            await self.broadcast({"type": "notice", "level": "info", "text": "Claude is working; your message goes next."})
            return
        if self._listening:
            await self._stop_listening()
        if source == "typed":
            await self.stop_audio()
        audio = self.put(media.mp3(1.2, 300.0, 16_000), "mp3", "audio/mpeg") if source == "voice" else None
        await self.upsert("user", text=text, source=source, audio=audio, duration=1.2 if audio else None)
        self._task = asyncio.create_task(self._turn(text))

    async def _turn(self, text: str) -> None:
        try:
            await self.script(text)
        except asyncio.CancelledError:
            return
        await self.respond()

    async def respond(self) -> None:
        await self.set_phase("responding")
        while self.owner is not None and self.done < self.sent:
            self._idle.clear()
            await self._idle.wait()
        if self.phase != "responding":
            return
        if self.owner is not None and self.prefs.get(self.owner, {}).get("handsfree", True):
            await self.offer_mic()
        else:
            await self.set_phase("idle")

    async def interrupt(self) -> None:
        if self.phase == "working" and self._task is not None:
            self._task.cancel()
            await self.stop_audio()
            asyncio.create_task(self.respond())
        elif self.phase == "responding":
            await self.stop_audio()

    async def stop_audio(self) -> None:
        await self._send(self.owner, {"type": "stop_audio"})
        self.sent = self.done = 0
        self._idle.set()

    async def claude_turn(self, _text: str) -> None:
        """Claude's turn, the default script."""
        await self.set_phase("working", "Thinking")
        for tool, title, ms in TOOLS:
            act = await self.upsert("activity", tool=tool, title=title, status="running", detail=f"{tool}: {title}")
            await self.set_phase("working", title)
            await asyncio.sleep(self.step_s)
            await self.update(act, status="ok", ms=ms, output="done")
        await self.upsert("agent", text="Rendering the kick at two levels", role="narration", audio=None,
                          duration=None, streaming=False)
        await self.shot("major", "The kick’s device chain after the change")
        reply = await self.upsert("agent", text="", role="reply", audio=None, duration=None, streaming=True)
        await self.update(reply, text=REPLY, streaming=False)
        await self.speak(reply, self.speech_s)
        music = await self.present_music()
        if self.autoplay:                                  # a presented render plays by itself only with autoplay
            await self.play(music["seq"], self.loops)

    # --- making messages ----------------------------------------------------------------------------------
    def put(self, data: bytes, ext: str, mime: str, **extra: Any) -> dict[str, Any]:
        name = f"{hashlib.sha256(data).hexdigest()}.{ext}"
        self.media[name] = (data, mime)
        return {"url": f"/studio/media/{name}", "type": mime, "bytes": len(data), **extra}

    def add(self, kind: str, turn: str | None = None, **data: Any) -> dict[str, Any]:
        msg = {"seq": next(self._seq), "kind": kind, "created": round(time.time(), 3), "turn": turn or self.turn,
               "rev": 0, "data": data}
        self.messages.append(msg)
        return msg

    async def upsert(self, kind: str, **data: Any) -> dict[str, Any]:
        msg = self.add(kind, **data)
        await self.broadcast({"type": "upsert", "message": msg}, data.get("level") if kind == "shots" else None)
        return msg

    async def update(self, msg: dict[str, Any], **data: Any) -> dict[str, Any]:
        msg["data"].update(data)
        msg["rev"] += 1
        level = msg["data"].get("level") if msg["kind"] == "shots" else None
        await self.broadcast({"type": "upsert", "message": msg}, level)
        return msg

    @property
    def autoplay(self) -> bool:
        return self.owner is not None and self.prefs.get(self.owner, {}).get("autoplay", True)

    async def speak(self, msg: dict[str, Any], seconds: float) -> None:
        """Claude's words, streamed to the owner as they are synthesised (only with autoplay on, as the Mac does)."""
        if self.autoplay:
            stream = next(self._streams)
            await self._send(self.owner, {"type": "speech", "stream": stream, "seq": msg["seq"],
                                          "rate": media.SPEECH_RATE, "state": "begin"})
            self.sent += 1
            self._idle.clear()
            pcm = media.speech_pcm(seconds)
            step = media.SPEECH_RATE * 2 // 10
            for i in range(0, len(pcm), step):
                if not self.owner.closed:
                    await self.owner.send_bytes(b"\x02" + stream.to_bytes(4, "big") + pcm[i:i + step])
                await asyncio.sleep(self.chunk_gap_s)
            await self._send(self.owner, {"type": "speech", "stream": stream, "seq": msg["seq"], "state": "end"})
        await self.update(msg, audio=self.put(media.mp3(seconds), "mp3", "audio/mpeg"), duration=seconds)

    async def present_music(self, title: str = "Kick level: now vs +3 dB") -> dict[str, Any]:
        flac = media.ab_flac(self.bar_s, self.bars)
        return await self.upsert(
            "music", title=title, audio=self.put(flac, "flac", "audio/flac"), duration=self.bar_s * self.bars,
            ab={"bar_seconds": self.bar_s, "bars": self.bars, "first": "A", "every": 1,
                "labels": {"A": "Now", "B": "+3 dB"}},
            plays=0, note="Listen to the low end on the downbeat: B should push without blurring the bass.",
            source="kick-ab.wav")

    async def play(self, seq: int, loops: int) -> None:
        msg = next(m for m in self.messages if m["seq"] == seq)
        await self.update(msg, plays=int(msg["data"].get("plays", 0)) + loops)
        if self.owner is not None:
            await self._send(self.owner, {"type": "play", "seq": seq, "loops": loops})
            self.sent += 1
            self._idle.clear()

    async def shot(self, level: str, caption: str, zoom_w: int = 640) -> dict[str, Any]:
        pair = media.shot_pair(next(self._shots) % 5, level, zoom_w)
        (fw, fh), (zw, zh) = pair["full_size"], pair["zoom_size"]
        return await self.upsert(
            "shots", level=level, caption=caption, rect=pair["rect"], changed=True, screen=pair["screen"],
            full=self.put(pair["full"], "webp", "image/webp", w=fw, h=fh),
            zoom=self.put(pair["zoom"], "webp", "image/webp", w=zw, h=zh))

    def seed_history(self, n: int) -> None:
        """`n` stored messages of every kind, as a long conversation leaves them (sharing a few media files)."""
        voice = self.put(media.mp3(1.5, 300.0, 16_000), "mp3", "audio/mpeg")
        said = self.put(media.mp3(2.5), "mp3", "audio/mpeg")
        flac = self.put(media.ab_flac(self.bar_s, self.bars), "flac", "audio/flac")
        pair = media.shot_pair(1)
        (fw, fh), (zw, zh) = pair["full_size"], pair["zoom_size"]
        full = self.put(pair["full"], "webp", "image/webp", w=fw, h=fh)
        zoom = self.put(pair["zoom"], "webp", "image/webp", w=zw, h=zh)
        makers = [
            lambda i: ("user", dict(text=f"Turn {i}: a little more air on the hats", source="voice", audio=voice,
                                    duration=1.5)),
            lambda i: ("activity", dict(tool="Bash", title=f"Render step {i}", status="ok", ms=40 + i % 900,
                                        detail="python render.py")),
            lambda i: ("activity", dict(tool="Read", title=f"Read notes {i}.md", status="ok", ms=12)),
            lambda i: ("agent", dict(text="Checking the hats' send level", role="narration", audio=None,
                                     duration=None, streaming=False)),
            lambda i: ("shots", dict(level=("major", "minor", "firehose")[i % 3], caption=f"Step {i}", full=full,
                                     zoom=zoom, rect=pair["rect"], changed=True, screen=pair["screen"])),
            lambda i: ("agent", dict(text=f"Reply {i}: the hats sit better now; listen for the shimmer.",
                                     role="reply", audio=said, duration=2.5, streaming=False)),
            lambda i: ("music", dict(title=f"Hats A/B {i}", audio=flac, duration=self.bar_s * self.bars,
                                     ab={"bar_seconds": self.bar_s, "bars": self.bars, "first": "A", "every": 1,
                                         "labels": {"A": "Before", "B": "After"}}, plays=i % 3, note="")),
            lambda i: ("notice", dict(level="info", text=f"Notice {i}")),
        ]
        for i in range(n):
            kind, data = makers[i % len(makers)](i)
            self.add(kind, turn=f"t-old-{i // len(makers)}", **data)


async def main() -> None:
    parser = argparse.ArgumentParser(description="The fake studio server, for looking at the page by hand.")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--history", type=int, default=24)
    args = parser.parse_args()
    fake = FakeStudio()
    fake.turn_frames = 150                     # three seconds of talking, then "tomato"
    fake.speech_s, fake.chunk_gap_s = 3.0, 0.08
    fake.bar_s, fake.bars = 1.0, 4
    fake.seed_history(args.history)
    runner = web.AppRunner(fake.app())
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", args.port).start()
    print(f"fake studio on http://127.0.0.1:{args.port}/studio/")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
