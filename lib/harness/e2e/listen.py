"""What the speakers said: the ear's recording, transcribed by the studio's own Parakeet (the worker of the run)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "ui"))
from heard import resample  # noqa: E402

STT_RATE = 16_000


async def transcribe(worker, samples: np.ndarray, rate: int) -> str:
    pcm = (np.clip(resample(samples, rate, STT_RATE), -1, 1) * 32767).astype("<i2").tobytes()
    stt = worker.transcription("tomato", STT_RATE)
    for i in range(0, len(pcm), 6400):                 # 200 ms at a time, as the mic sends it
        stt.feed(pcm[i:i + 6400])
    stt.end()
    text = ""
    async for event in stt.events():
        if event["op"] == "stt.final":
            text = event["text"]
    return text


def ear_at(ears: list[Any], t: float):
    """The recording of the audio context whose clock covers `t`."""
    for ear in ears:
        if len(ear.samples) and ear.t0 <= t <= ear.time(len(ear.samples)):
            return ear
    return None


async def intros(engine: list[dict[str, Any]], ears: list[Any], worker) -> list[dict[str, Any]]:
    """For every render the Mac played: the speech item that ended right before it (its intro), what it said, and
    the silence between its last sound and the music's first sample."""
    out = []
    for i, item in enumerate(engine):
        if item.get("kind") != "music" or not item.get("counted") or item.get("t0") is None:
            continue
        prev = engine[i - 1] if i else None
        found: dict[str, Any] = {"seq": item["seq"], "intro_seq": None, "text": "", "gap_s": None}
        ear = ear_at(ears, item["t0"])
        if prev and prev.get("kind") == "speech" and prev.get("t0") is not None and ear is not None:
            found["intro_seq"] = prev["seq"]
            said = ear.between(prev["t0"], item["t0"])
            found["text"] = await transcribe(worker, said, ear.rate)
            loud = [b for a, b in ear.loud(hold=0.02) if prev["t0"] <= b <= item["t0"] + 0.005]
            found["gap_s"] = round(item["t0"] - loud[-1], 3) if loud else None
        out.append(found)
    return out
