"""Stand-in engines for tests and for working on the page without the models: a tone for speech, and a
transcriber that "hears" a fixed sentence (VOICE_FAKE_TEXT) once enough audio has arrived."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import numpy as np


class FakeTTS:
    name = "fake"
    rate = 24_000
    SECONDS_PER_CHAR = 0.03
    CHUNK_S = 0.25

    def warmup(self) -> None:
        pass

    def stream(self, text: str, voice: str, speed: float) -> Iterator[tuple[np.ndarray, int]]:
        total = max(0.2, len(text) * self.SECONDS_PER_CHAR / max(speed, 0.1))
        t = np.arange(int(total * self.rate)) / self.rate
        wave = (0.2 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
        step = int(self.CHUNK_S * self.rate)
        for i in range(0, len(wave), step):
            yield wave[i:i + step], self.rate


class FakeTurn:
    def __init__(self, stop_word: str, rate: int, text: str, after_s: float):
        self.stop_word, self.rate, self.text, self.after_s = stop_word, rate, text, after_s
        self.samples = 0
        self.t0 = time.monotonic()
        self.partials = 0

    def feed(self, pcm: np.ndarray) -> list[dict[str, Any]]:
        """A caption grows with the audio heard; the final comes once `after_s` of it has arrived. Audio that
        arrives in one big piece (frames pile up while the model thread is busy) still gets a caption first."""
        self.samples += len(pcm)
        heard = self.samples / self.rate
        words = self.text.split()
        n = min(len(words), max(1, int(len(words) * heard / self.after_s)))
        events: list[dict[str, Any]] = []
        if n > self.partials:
            self.partials = n
            events.append({"op": "stt.partial", "text": " ".join(words[:n])})
        if heard >= self.after_s:
            events.append(self._final(stop_word=True))
        return events

    def finish(self) -> dict[str, Any]:
        return self._final(stop_word=False)

    def _final(self, stop_word: bool) -> dict[str, Any]:
        return {"op": "stt.final", "text": self.text, "stop_word": stop_word,
                "audio_s": round(self.samples / self.rate, 2), "ms": round((time.monotonic() - self.t0) * 1000)}


class FakeSTT:
    name = "fake"

    def __init__(self, text: str | None = None, after_s: float | None = None):
        self.text = text or os.environ.get("VOICE_FAKE_TEXT", "play again")
        self.after_s = after_s or float(os.environ.get("VOICE_FAKE_AFTER_S", "1.0"))

    def warmup(self) -> None:
        pass

    def turn(self, stop_word: str, rate: int) -> FakeTurn:
        return FakeTurn(stop_word, rate, self.text, self.after_s)
