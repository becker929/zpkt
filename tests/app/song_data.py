"""Made-up arranger data for the Song's tests: loops.json, fx.json, an arrangement and tiny silent audio files.

The shapes come from contrib/arranger/tests/samples.py, so the Song is tested on the data the arranger's own tests use.
Nothing here is real data.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
import soundfile

from zpkt.app import song


def samples() -> ModuleType:
    """The arranger's own test data module, loaded by path."""
    path = song.arranger_dir() / "tests" / "samples.py"
    spec = importlib.util.spec_from_file_location("arranger_samples", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def silent(path: Path, seconds: float = 0.5) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(str(path), np.zeros((int(44100 * seconds), 2), dtype="float32"), 44100, subtype="PCM_16")


def write_song_data(data: Path) -> Path:
    """A data folder the Song can read and build from: loops.json, fx/fx.json, arrangements/short-8d2a2.json and
    every audio file they name."""
    s = samples()
    s.write_data(data)
    for clip in s.LOOPS["clips"]:
        silent(data / "audio" / clip["file"])
        if clip.get("tail"):
            silent(data / "audio" / clip["tail"])
    for cand in s.FX["candidates"]:
        silent(data / "fx" / "audio" / cand["file"])
    silent(data / "kickfuzz" / s.ARRANGEMENT["kickFuzz"]["loop"])
    (data / "arrangements" / "other.json").write_text(json.dumps({"name": "Other", "regions": [], "saved": 5.0}))
    return data
