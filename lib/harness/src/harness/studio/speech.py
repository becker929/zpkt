"""Speech: the voice worker's client (lib/voice in its own process), and Claude's voice.

The worker runs Kokoro (text to speech) and the speech-to-text with the stop word. This module starts it, keeps it
running, and multiplexes requests over its pipes. The Speaker turns Claude's text, as it streams in, into short
speakable pieces, has them synthesised in order, streams the audio to the phone that owns the speaker, and keeps an
MP3 of each utterance so its bubble can be replayed.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from voice import protocol as frames

from . import audio
from .hub import Hub
from .model import Message
from .protocol import speech_frame
from .store import Store

log = logging.getLogger(__name__)


class WorkerGone(RuntimeError):
    """The voice worker is not running (it is being restarted)."""


# --- the worker ----------------------------------------------------------------------------------------------------

class VoiceWorker:
    RESTART_DELAYS = (1, 2, 5, 10, 30)

    def __init__(self, command: list[str], env: dict[str, str] | None = None):
        self.command, self.env = command, env
        self.info: dict[str, Any] = {}
        self._proc: asyncio.subprocess.Process | None = None
        self._waiters: dict[str, asyncio.Queue[tuple[dict[str, Any], bytes] | None]] = {}
        self._ids = itertools.count(1)
        self._ready = asyncio.Event()
        self._supervisor: asyncio.Task | None = None
        self._stopping = False

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def start(self) -> None:
        self._supervisor = asyncio.create_task(self._supervise(), name="voice-worker")

    async def wait_ready(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        self._stopping = True
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), 5)
            except asyncio.TimeoutError:
                self._proc.kill()
        if self._supervisor:
            self._supervisor.cancel()

    async def _supervise(self) -> None:
        failures = 0
        while not self._stopping:
            started = time.monotonic()
            try:
                await self._run_once()
            except Exception:  # noqa: BLE001 - a broken worker must not take the server down
                log.exception("voice worker crashed")
            if self._stopping:
                return
            failures = 0 if time.monotonic() - started > 60 else failures + 1
            delay = self.RESTART_DELAYS[min(failures, len(self.RESTART_DELAYS) - 1)]
            log.warning("voice worker stopped; restarting in %d s", delay)
            await asyncio.sleep(delay)

    async def _run_once(self) -> None:
        self._proc = proc = await asyncio.create_subprocess_exec(
            *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env={**os.environ, **(self.env or {})}, limit=frames.MAX_PAYLOAD)
        logs = asyncio.create_task(self._log_stderr(proc))
        try:
            self._send({"op": "ping", "id": "hello"})
            async for header, payload in self._frames(proc):
                if header.get("id") == "hello" and header["op"] == "pong":
                    self.info = header
                    self._ready.set()
                    log.info("voice worker ready: %s", {k: v for k, v in header.items() if k not in ("op", "id")})
                    continue
                waiter = self._waiters.get(str(header.get("id")))
                if waiter is not None:
                    waiter.put_nowait((header, payload))
        finally:
            self._ready.clear()
            for waiter in self._waiters.values():
                waiter.put_nowait(None)
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            logs.cancel()

    @staticmethod
    async def _frames(proc: asyncio.subprocess.Process) -> AsyncIterator[tuple[dict[str, Any], bytes]]:
        while (frame := await frames.read(proc.stdout)) is not None:
            yield frame

    @staticmethod
    async def _log_stderr(proc: asyncio.subprocess.Process) -> None:
        while line := await proc.stderr.readline():
            log.info("voice: %s", line.decode(errors="replace").rstrip())

    def _send(self, header: dict[str, Any], payload: bytes = b"") -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None or proc.stdin is None or proc.stdin.is_closing():
            raise WorkerGone("the voice worker is not running")
        proc.stdin.write(frames.encode(header, payload))

    def _open(self) -> tuple[str, asyncio.Queue]:
        if not self.ready:
            raise WorkerGone("the voice worker is not ready")
        rid = f"r{next(self._ids)}"
        queue: asyncio.Queue = asyncio.Queue()
        self._waiters[rid] = queue
        return rid, queue

    async def synthesize(self, text: str, voice: str, speed: float) -> AsyncIterator[tuple[int, bytes]]:
        """Yields (sample rate, s16le mono PCM) chunks for `text`, as they are made."""
        rid, queue = self._open()
        try:
            self._send({"op": "tts", "id": rid, "text": text, "voice": voice, "speed": speed})
            while True:
                item = await queue.get()
                if item is None:
                    raise WorkerGone("the voice worker stopped mid-sentence")
                header, payload = item
                if header["op"] == "tts.chunk":
                    yield int(header["rate"]), payload
                elif header["op"] == "tts.end":
                    if header.get("error"):
                        log.warning("tts failed for %r: %s", text[:60], header["error"])
                    return
        finally:
            if self._waiters.pop(rid, None) is not None and queue.empty() and self.ready:
                try:
                    self._send({"op": "tts.cancel", "id": rid})   # stopped early: let the worker skip the rest
                except WorkerGone:
                    pass

    def transcription(self, stop_word: str, rate: int) -> "Transcription":
        rid, queue = self._open()
        self._send({"op": "stt.begin", "id": rid, "rate": rate, "stop_word": stop_word})
        return Transcription(self, rid, queue)


class Transcription:
    """One user turn's speech-to-text: feed it mic audio; read partial captions and the final text."""

    def __init__(self, worker: VoiceWorker, rid: str, queue: asyncio.Queue):
        self._worker, self.id, self._queue = worker, rid, queue
        self.closed = False

    def feed(self, pcm: bytes) -> None:
        if not self.closed:
            self._worker._send({"op": "stt.audio", "id": self.id}, pcm)

    def end(self) -> None:
        """Finish now, stop word or not; a final event follows."""
        if not self.closed:
            self._worker._send({"op": "stt.end", "id": self.id})

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """`stt.partial` and `stt.final` headers; ends after the final one, or quietly if closed. Raises
        WorkerGone if the worker dies mid-turn."""
        try:
            while (item := await self._queue.get()) is not None:
                header, _ = item
                yield header
                if header["op"] == "stt.final":
                    return
            if not self.closed:
                raise WorkerGone("the voice worker stopped while listening")
        finally:
            self.close()

    def close(self) -> None:
        """Stop listening: the worker drops the turn, and events() ends."""
        if self.closed:
            return
        self.closed = True
        if self._worker._waiters.pop(self.id, None) is not None:
            try:
                self._worker._send({"op": "stt.end", "id": self.id})
            except WorkerGone:
                pass
        self._queue.put_nowait(None)


# --- Claude's voice ------------------------------------------------------------------------------------------------

ABBREVIATIONS = {"e.g", "i.e", "vs", "etc", "approx", "mr", "mrs", "ms", "dr", "no", "fig", "cf"}
SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*\s+|\n+")
CLAUSE_END = re.compile(r"[,;:]\s+|\s+[—–-]\s+")


class Segmenter:
    """Cuts streamed text into pieces to speak: a short first piece (so the first sound comes soon), then
    sentences, with overlong sentences cut at clauses. Fenced code is never spoken."""

    FIRST_MIN_WORDS = 4
    MAX_CHARS = 220

    def __init__(self) -> None:
        self.buf = ""
        self.first = True
        self.in_code = False

    def feed(self, text: str) -> list[str]:
        self.buf += text
        return self._cut(final=False)

    def flush(self) -> list[str]:
        out = self._cut(final=True)
        rest, self.buf = ("" if self.in_code else self.buf.strip()), ""
        if _speakable(rest):
            out.append(rest)
        return out

    def _cut(self, final: bool) -> list[str]:
        out: list[str] = []
        while True:
            if self.in_code:
                end = self.buf.find("```")
                if end < 0:
                    self.buf = "" if final else self.buf[-2:]   # keep what may be half a closing fence
                    return out
                self.buf, self.in_code = self.buf[end + 3:], False
                continue
            fence = self.buf.find("```")
            text = self.buf if fence < 0 else self.buf[:fence]
            if fence < 0 and not final:
                text = text.rstrip("`")                         # may be half an opening fence
            cut = self._boundary(text)
            if cut is not None:
                self._emit(out, text[:cut])
                self.buf = self.buf[cut:]
            elif fence >= 0:
                self._emit(out, text)
                self.buf, self.in_code = self.buf[fence + 3:], True
            else:
                return out

    def _emit(self, out: list[str], piece: str) -> None:
        piece = piece.strip()
        if _speakable(piece):
            out.append(piece)
            self.first = False

    def _boundary(self, text: str) -> int | None:
        """Where to cut `text`, or None to wait for more."""
        for m in SENTENCE_END.finditer(text):
            words = text[: m.start()].split()
            if not words:
                continue
            if "\n" not in m.group() and words[-1].rstrip(".").lower() in ABBREVIATIONS:
                continue
            return m.end()
        if not (self.first or len(text) > self.MAX_CHARS):
            return None
        cut = None
        for m in CLAUSE_END.finditer(text):
            if len(text[: m.start()].split()) >= self.FIRST_MIN_WORDS:
                cut = m.end()
                if self.first:
                    break                                       # the earliest clause, for the first sound
        if cut is None and len(text) > self.MAX_CHARS:
            cut = text.rfind(" ", 0, self.MAX_CHARS) + 1 or self.MAX_CHARS
        return cut


def _speakable(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


@dataclass
class Utterance:
    """One bubble's speech. Text arrives with feed() and ends with close()."""

    msg: Message | None                       # None for a narration: its bubble is made only if it is spoken
    make: Callable[[], Message] | None = None
    droppable: bool = False                   # a narration: skip it if it is stale by its turn
    created: float = field(default_factory=time.monotonic)
    on_first_audio: Callable[[], None] | None = None
    pieces: asyncio.Queue = field(default_factory=asyncio.Queue)
    segmenter: Segmenter = field(default_factory=Segmenter)
    cancelled: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)

    def feed(self, text: str) -> None:
        for piece in self.segmenter.feed(text):
            self.pieces.put_nowait(piece)

    def close(self) -> None:
        for piece in self.segmenter.flush():
            self.pieces.put_nowait(piece)
        self.pieces.put_nowait(None)

    def cancel(self) -> None:
        self.cancelled = True
        self.pieces.put_nowait(None)


class Speaker:
    STALE_S = 6.0      # a narration that waited longer than this has nothing left to say

    def __init__(self, worker: VoiceWorker, hub: Hub, store: Store, *, voice: str, speed: float,
                 on_update: Callable[[Message], None], on_output: Callable[[], None]):
        """on_update: a bubble got its replay audio. on_output: a stream was sent to the phone to play."""
        self.worker, self.hub, self.store = worker, hub, store
        self.voice, self.speed, self.on_update, self.on_output = voice, speed, on_update, on_output
        self._queue: asyncio.Queue[Utterance] = asyncio.Queue()
        self._pending: list[Utterance] = []
        self._streams = itertools.count(1)
        self._task: asyncio.Task | None = None
        self._encoders: set[asyncio.Task] = set()
        self.current: Utterance | None = None
        self._warned = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="speaker")

    async def stop(self) -> None:
        self.cancel()
        if self._task:
            self._task.cancel()

    @property
    def busy(self) -> bool:
        return self.current is not None or bool(self._pending)

    def say(self, utt: Utterance) -> Utterance:
        if not utt.droppable:   # Claude speaking makes any narration still waiting stale
            for waiting in self._pending:
                if waiting.droppable:
                    waiting.cancel()
        self._pending.append(utt)
        self._queue.put_nowait(utt)
        return utt

    def cancel(self) -> None:
        for utt in [*self._pending, *([self.current] if self.current else [])]:
            utt.cancel()

    async def idle(self) -> None:
        """Until everything queued has been synthesised (not played: the phone reports that)."""
        while self.busy:
            await asyncio.sleep(0.05)

    async def _run(self) -> None:
        while True:
            utt = await self._queue.get()
            self._pending.remove(utt)
            if utt.cancelled or (utt.droppable and time.monotonic() - utt.created > self.STALE_S):
                utt.done.set()
                continue
            self.current = utt
            try:
                await self._speak(utt)
            except Exception:  # noqa: BLE001 - one failed utterance must not silence the rest
                log.exception("speaking failed")
            finally:
                self.current = None
                utt.done.set()

    async def _speak(self, utt: Utterance) -> None:
        stream, rate, pcm, msg = next(self._streams), 0, [], utt.msg
        play = False      # decided at the first sound: the phone plays it only with autoplay on
        try:
            while (piece := await utt.pieces.get()) is not None and not utt.cancelled:
                async for rate, chunk in self.worker.synthesize(piece, self.voice, self.speed):
                    if utt.cancelled:
                        break
                    if not pcm:
                        msg = msg or utt.make()
                        if utt.on_first_audio:
                            utt.on_first_audio()
                        play = self.hub.autoplay
                        if play:
                            self.hub.to_owner({"type": "speech", "stream": stream, "seq": msg.seq, "rate": rate,
                                               "state": "begin"})
                            self.on_output()
                    if play:
                        self.hub.to_owner(speech_frame(stream, chunk))
                    pcm.append(chunk)
        except WorkerGone as exc:
            if not self._warned:
                self._warned = True
                log.warning("speaking without a voice: %s", exc)
        finally:
            if play:
                self.hub.to_owner({"type": "speech", "stream": stream, "seq": msg.seq, "state": "end"})
            if pcm and msg is not None:
                task = asyncio.create_task(self._keep(msg, b"".join(pcm), rate))
                self._encoders.add(task)
                task.add_done_callback(self._encoders.discard)

    async def _keep(self, msg: Message, pcm: bytes, rate: int) -> None:
        """Store the utterance as an MP3 so its bubble can be replayed."""
        try:
            mp3 = await audio.pcm_to_mp3(pcm, rate)
        except audio.AudioError:
            log.exception("could not encode a replay")
            return
        ref = await asyncio.to_thread(self.store.put_media, mp3, "mp3")
        msg.data["audio"] = ref.wire()
        msg.data["duration"] = round(len(pcm) / 2 / rate, 2)
        self.store.update(msg)
        self.on_update(msg)
