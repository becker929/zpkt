"""Synthetic audio for the characterization tests: deterministic, a few seconds long, with known structure."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from mlab import dsp, siggen
from mlab.util import lin

SR = 44100
BEAT_S = 0.375  # 160 BPM; the target windows below use one beat as their "bar" to keep files short


def mix(seconds: float = 12.0) -> np.ndarray:
    """A stereo 'mix': a 160 BPM kick loop over a decorrelated pink bed, the first half 4 dB quieter."""
    kick = siggen.kick_loop(SR, bpm=160, bars=int(seconds / 1.5))
    bed = siggen.pink(seconds, SR, ch=2, seed=3, rms_dbfs=-28)
    x = kick[: len(bed)] + bed
    x[: len(x) // 2] *= lin(-4.0)
    return x


def reference(shelf_db: float) -> np.ndarray:
    """The mix through a high shelf: a brighter or darker 'reference' with the same structure."""
    return dsp.eq(mix(), SR, [{"type": "highshelf", "f": 4000, "gain_db": shelf_db, "q": 0.707}])


def write(path: Path, x: np.ndarray, sr: int = SR, subtype: str = "FLOAT") -> Path:
    sf.write(path, x, sr, subtype=subtype)
    return path


def refs_json(folder: Path, entries: list[dict]) -> Path:
    path = folder / "refs.json"
    path.write_text(json.dumps({"refs": entries}))
    return path
