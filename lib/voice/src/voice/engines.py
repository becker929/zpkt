"""What the worker needs from a text-to-speech and a speech-to-text engine, and how to pick them by name."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any, Protocol

import numpy as np


class TTS(Protocol):
    name: str

    def warmup(self) -> None: ...

    def stream(self, text: str, voice: str, speed: float) -> Iterator[tuple[np.ndarray, int]]:
        """Mono int16 chunks and their sample rate, as soon as each is made."""


class Turn(Protocol):
    """One user turn. Events are protocol headers without the id: {"op": "stt.partial", "text"} or
    {"op": "stt.final", "text", "stop_word", "audio_s", "ms"}; after a final the turn is over."""

    def feed(self, pcm: np.ndarray) -> list[dict[str, Any]]: ...

    def finish(self) -> dict[str, Any]: ...


class STT(Protocol):
    name: str

    def warmup(self) -> None: ...

    def turn(self, stop_word: str, rate: int) -> Turn: ...


TTS_ENGINES = {"kokoro": "voice.tts:Kokoro", "fake": "voice.fake:FakeTTS"}
STT_ENGINES = {"parakeet": "voice.stt:Parakeet", "fake": "voice.fake:FakeSTT"}


def load(kind: str, name: str, **kwargs: Any) -> Any:
    table = TTS_ENGINES if kind == "tts" else STT_ENGINES
    if name not in table:
        raise SystemExit(f"unknown {kind} engine {name!r}; choose from {', '.join(table)}")
    module, cls = table[name].split(":")
    return getattr(importlib.import_module(module), cls)(**kwargs)
