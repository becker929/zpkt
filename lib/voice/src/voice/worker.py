"""`voice serve`: the speech models behind a pipe (frames: voice.protocol; requests: docs/studio.md).

    voice serve [--tts kokoro|fake] [--stt parakeet|fake]
    voice say "Hello there." -o hello.wav           # one-off synthesis, for trying voices
    voice hear turn.wav                              # one-off transcription of a file, as a turn

One thread runs the models, so a long synthesis never blocks reading the next frame, and speech and transcription
never run at the same time on the GPU (they never need to: the mic and the speaker take turns). Anything a library
prints goes to stderr: stdout carries frames only.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from . import engines, protocol

log = logging.getLogger("voice")
END = object()


class Worker:
    def __init__(self, tts: engines.TTS, stt: engines.STT, write: Any, load_s: dict[str, float],
                 models: ThreadPoolExecutor | None = None):
        self.tts, self.stt, self._write, self.load_s = tts, stt, write, load_s
        self.models = models or ThreadPoolExecutor(1, thread_name_prefix="models")
        self.speech: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.cancelled: set[str] = set()
        self.turns: dict[str, asyncio.Queue] = {}
        self.tasks: set[asyncio.Task] = set()

    def send(self, header: dict[str, Any], payload: bytes = b"") -> None:
        self._write(protocol.encode(header, payload))

    async def _model(self, fn: Any, *args: Any) -> Any:
        return await asyncio.get_running_loop().run_in_executor(self.models, fn, *args)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def handle(self, header: dict[str, Any], payload: bytes) -> None:
        op, rid = header["op"], str(header.get("id", ""))
        if op == "ping":
            self.send({"op": "pong", "id": rid, "tts": self.tts.name, "stt": self.stt.name, "load_s": self.load_s,
                       "pid": os.getpid()})
        elif op == "tts":
            self.speech.put_nowait(header)
        elif op == "tts.cancel":
            self.cancelled.add(rid)
        elif op == "stt.begin":
            queue: asyncio.Queue = asyncio.Queue()
            self.turns[rid] = queue
            turn = self.stt.turn(str(header.get("stop_word", "tomato")), int(header.get("rate", 16_000)))
            self._spawn(self._listen(rid, turn, queue))
        elif op == "stt.audio" and rid in self.turns:
            self.turns[rid].put_nowait(np.frombuffer(payload, dtype="<i2"))
        elif op == "stt.end" and rid in self.turns:
            self.turns[rid].put_nowait(END)

    async def speak(self) -> None:
        """Synthesis requests, one after another, in the order they came."""
        while True:
            header = await self.speech.get()
            rid, t0 = str(header["id"]), time.monotonic()
            if rid in self.cancelled:
                self.cancelled.discard(rid)
                self.send({"op": "tts.end", "id": rid, "cancelled": True})
                continue
            chunks = self.tts.stream(str(header.get("text", "")), str(header.get("voice", "af_heart")),
                                     float(header.get("speed", 1.0)))
            index, error = 0, None
            try:
                while (item := await self._model(next, chunks, None)) is not None and rid not in self.cancelled:
                    pcm, rate = item
                    self.send({"op": "tts.chunk", "id": rid, "rate": rate, "index": index,
                               "ms": round((time.monotonic() - t0) * 1000)}, pcm.astype("<i2").tobytes())
                    index += 1
            except Exception as exc:  # noqa: BLE001 - report it; the next request may be fine
                log.exception("tts failed")
                error = f"{type(exc).__name__}: {exc}"
            self.send({"op": "tts.end", "id": rid, "ms": round((time.monotonic() - t0) * 1000),
                       **({"error": error} if error else {}), **({"cancelled": True} if rid in self.cancelled else {})})
            self.cancelled.discard(rid)

    async def _listen(self, rid: str, turn: engines.Turn, queue: asyncio.Queue) -> None:
        """One turn: feed the audio in order (catching up in one call when frames pile up) until a final."""
        try:
            while True:
                items = [await queue.get()]
                while not queue.empty():
                    items.append(queue.get_nowait())
                audio = [a for a in items if a is not END]
                ended = len(audio) < len(items)
                events: list[dict[str, Any]] = []
                if audio:
                    events = await self._model(turn.feed, np.concatenate(audio))
                if ended and not any(e["op"] == "stt.final" for e in events):
                    events.append(await self._model(turn.finish))
                for event in events:
                    self.send({**event, "id": rid})
                    if event["op"] == "stt.final":
                        return
        except Exception as exc:  # noqa: BLE001
            log.exception("stt failed")
            self.send({"op": "stt.final", "id": rid, "text": "", "stop_word": False, "error": str(exc)})
        finally:
            self.turns.pop(rid, None)


async def serve(tts_name: str, stt_name: str) -> None:
    out = os.fdopen(os.dup(1), "wb", buffering=0)   # frames go to the real stdout...
    os.dup2(2, 1)                                     # ...and anything printed lands on stderr
    load_s: dict[str, float] = {}

    def ready(kind: str, name: str) -> Any:
        t0 = time.monotonic()
        engine = engines.load(kind, name)
        engine.warmup()
        load_s[kind] = round(time.monotonic() - t0, 2)
        return engine

    # The models are loaded, warmed and run on one thread: MLX keeps its streams per thread, and arrays made on one
    # thread cannot be evaluated on another.
    models = ThreadPoolExecutor(1, thread_name_prefix="models")
    loop = asyncio.get_running_loop()
    tts = await loop.run_in_executor(models, ready, "tts", tts_name)
    stt = await loop.run_in_executor(models, ready, "stt", stt_name)
    log.info("ready: tts %s (%.1f s), stt %s (%.1f s)", tts.name, load_s["tts"], stt.name, load_s["stt"])
    reader = asyncio.StreamReader(limit=protocol.MAX_PAYLOAD)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    worker = Worker(tts, stt, out.write, load_s, models)
    speaking = asyncio.create_task(worker.speak())
    try:
        while (frame := await protocol.read(reader)) is not None:
            await worker.handle(*frame)
    finally:
        speaking.cancel()


def _say(text: str, out: str, tts_name: str, voice: str) -> None:
    tts = engines.load("tts", tts_name)
    t0 = time.monotonic()
    parts, rate = [], 24_000
    for pcm, rate in tts.stream(text, voice, 1.0):
        parts.append(pcm)
    audio = np.concatenate(parts) if parts else np.zeros(0, np.int16)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.astype("<i2").tobytes())
    print(f"{out}: {len(audio) / rate:.2f} s of audio in {time.monotonic() - t0:.2f} s", file=sys.stderr)


def _hear(path: str, stt_name: str, stop_word: str) -> None:
    with wave.open(path, "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise SystemExit("hear wants a mono 16-bit WAV")
        rate, audio = w.getframerate(), np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    turn = engines.load("stt", stt_name).turn(stop_word, rate)
    step = rate // 25
    for i in range(0, len(audio), step):
        for event in turn.feed(audio[i:i + step]):
            print(event)
            if event["op"] == "stt.final":
                return
    print(turn.finish())


def main() -> None:
    ap = argparse.ArgumentParser(prog="voice")
    ap.add_argument("--tts", default=os.environ.get("VOICE_TTS", "kokoro"))
    ap.add_argument("--stt", default=os.environ.get("VOICE_STT", "parakeet"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="answer requests on stdin/stdout")
    say = sub.add_parser("say", help="synthesise one text to a WAV")
    say.add_argument("text")
    say.add_argument("-o", "--out", default="say.wav")
    say.add_argument("--voice", default="af_heart")
    hear = sub.add_parser("hear", help="transcribe a mono 16-bit WAV as one turn")
    hear.add_argument("wav")
    hear.add_argument("--stop-word", default="tomato")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    if a.cmd == "serve":
        asyncio.run(serve(a.tts, a.stt))
    elif a.cmd == "say":
        _say(a.text, a.out, a.tts, a.voice)
    else:
        _hear(a.wav, a.stt, a.stop_word)


if __name__ == "__main__":
    main()
