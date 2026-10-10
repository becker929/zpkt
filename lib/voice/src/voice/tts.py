"""Kokoro (82 M parameters): text to 24 kHz speech, a sentence at a time.

VOICE_TTS_MODEL picks the build. `fluid` (the default) runs it through FluidAudio on the Neural Engine (voice.fluid),
about 0.1 s to the first audio; where that cannot be built or started, ONNX Runtime fp32 (~0.5 s) takes over. `fp32`
and `int8` ask for ONNX directly; int8 is about half the time of fp32 (260 against 520 ms on the benchmark,
docs/voice-benchmark.md) for a slightly rougher voice. The ONNX model and its voices are fetched on first use into
VOICE_MODELS (default ~/.cache/zpkt-voice) and kept there.
Text is cut into sentences (and over-long sentences at clause marks) so the first audio is ready after the first
sentence rather than after the whole reply; each piece is synthesised and handed on as soon as it is made.
"""

from __future__ import annotations

import logging
import os
import re
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("voice.tts")

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
MODELS = {"fp32": "kokoro-v1.0.onnx", "int8": "kokoro-v1.0.int8.onnx"}
VOICES = "voices-v1.0.bin"
RATE = 24_000
MAX_CHARS = 220              # a piece longer than this is cut at a clause mark (or a space)

_SENTENCE = re.compile(r"(?<=[.!?…])[\"')\]]*\s+")
_CLAUSE = re.compile(r"(?<=[,;:—–])\s+")


def models_dir() -> Path:
    return Path(os.environ.get("VOICE_MODELS", Path.home() / ".cache" / "zpkt-voice")).expanduser()


def fetch(name: str, into: Path) -> Path:
    path = into / name
    if path.is_file() and path.stat().st_size > 0:
        return path
    into.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    log.info("downloading %s", name)
    urllib.request.urlretrieve(f"{RELEASE}/{name}", part)
    part.rename(path)
    return path


def pieces(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Sentences, with any longer than `max_chars` cut at clause marks, then at the last space that fits."""
    out: list[str] = []
    for sentence in _SENTENCE.split(" ".join(text.split())):
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            out.append(sentence)
            continue
        buf = ""
        for clause in _CLAUSE.split(sentence):
            while len(clause) > max_chars:
                cut = clause.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(clause[:cut].strip())
                clause = clause[cut:].strip()
            if buf and len(buf) + 1 + len(clause) > max_chars:
                out.append(buf)
                buf = clause
            else:
                buf = f"{buf} {clause}".strip()
        if buf:
            out.append(buf)
    return [p for p in out if p.strip()]


def to_int16(audio: np.ndarray) -> np.ndarray:
    return (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)


def kokoro() -> Any:
    """Kokoro as VOICE_TTS_MODEL asks; FluidAudio falls back to ONNX fp32, saying why."""
    variant = os.environ.get("VOICE_TTS_MODEL", "fluid")
    if variant == "fluid":
        from .fluid import FluidUnavailable, KokoroFluid
        try:
            return KokoroFluid()
        except FluidUnavailable as exc:
            log.warning("Kokoro on FluidAudio is unavailable, so ONNX fp32 speaks: %s", exc)
            variant = "fp32"
    return Kokoro(variant=variant)


class Kokoro:
    """Kokoro through ONNX Runtime, on the CPU."""

    name = "kokoro"
    rate = RATE

    def __init__(self, models: Path | None = None, variant: str | None = None):
        from kokoro_onnx import Kokoro as Model     # heavy: only when the engine is chosen

        into = models or models_dir()
        variant = variant or os.environ.get("VOICE_TTS_MODEL", "fp32")
        variant = variant if variant in MODELS else "fp32"
        self.model = Model(str(fetch(MODELS.get(variant, MODELS["fp32"]), into)), str(fetch(VOICES, into)))
        self.name = f"kokoro ({variant})"
        self.voices = set(self.model.get_voices())

    def warmup(self) -> None:
        """The first inference pays for graph setup; pay it before the first reply."""
        for _ in self.stream("Ready.", "af_heart", 1.0):
            pass

    def stream(self, text: str, voice: str, speed: float) -> Iterator[tuple[np.ndarray, int]]:
        voice = voice if voice in self.voices else "af_heart"
        speed = min(max(speed, 0.5), 2.0)
        for piece in pieces(text):
            try:
                audio, rate = self.model.create(piece, voice=voice, speed=speed, lang="en-us")
            except ValueError as exc:      # nothing speakable in this piece (only symbols, say)
                log.info("skipped %r: %s", piece, exc)
                continue
            if len(audio):
                yield to_int16(np.asarray(audio, dtype=np.float32)), rate
