"""Audio file I/O.

Every instrument works on float64 arrays shaped (samples, channels).
`load` keeps the file's format facts next to the samples, because the
Ch.15 tools need to know what the container held, not just the values.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, asdict

import numpy as np
import soundfile as sf

LOSSY_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm"}


@dataclass
class Audio:
    x: np.ndarray          # (n, ch) float64, full scale = 1.0
    sr: int
    path: str = ""
    subtype: str = ""      # e.g. PCM_16, PCM_24, FLOAT, or "lossy:mp3"
    fmt: str = ""          # WAV, AIFF, FLAC, MP3 ...
    info: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return self.x.shape[0]

    @property
    def ch(self) -> int:
        return self.x.shape[1]

    @property
    def duration(self) -> float:
        return self.n / self.sr

    @property
    def lossy(self) -> bool:
        return self.subtype.startswith("lossy")

    def meta(self) -> dict:
        return {"path": self.path, "sr": self.sr, "channels": self.ch,
                "duration_s": round(self.duration, 3), "subtype": self.subtype,
                "format": self.fmt, "lossy": self.lossy}


def _as2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x[:, None] if x.ndim == 1 else x


def load(path: str) -> Audio:
    """Read WAV/AIFF/FLAC natively; decode lossy formats through ffmpeg."""
    ext = os.path.splitext(path)[1].lower()
    if ext in LOSSY_EXT:
        return _load_ffmpeg(path, ext)
    x, sr = sf.read(path, dtype="float64", always_2d=True)
    inf = sf.info(path)
    return Audio(x, sr, path, inf.subtype, inf.format)


def _load_ffmpeg(path: str, ext: str) -> Audio:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is needed to read " + ext)
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "dec.wav")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path,
                        "-c:a", "pcm_f32le", out], check=True)
        x, sr = sf.read(out, dtype="float64", always_2d=True)
    return Audio(x, sr, path, "lossy:" + ext[1:], ext[1:].upper(), {"decoder": "ffmpeg"})


def save(path: str, x: np.ndarray, sr: int, subtype: str = "FLOAT") -> str:
    """Write audio. Default 32-bit float so nothing clips or truncates silently."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    sf.write(path, _as2d(x), sr, subtype=subtype)
    return path


def from_array(x: np.ndarray, sr: int, name: str = "<array>") -> Audio:
    return Audio(_as2d(x), sr, name, "FLOAT", "ARRAY")


def dump_json(obj, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2, default=_json_default)
    return path


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "__dataclass_fields__"):
        return asdict(o)
    return str(o)
