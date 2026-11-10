"""Samples: audio files the bot gives the booth (POST /v1/samples) for a score to play in Live.

A friend shares a video or an audio link with the bot; the bot fetches its sound and uploads the file here. The booth
keeps it under its own folder (BOOTH_HOME/samples/<id>.wav), named by a hash of the bytes it was sent, so a score
names a sample only by that id and never by a path (docs/design/bluesky-bot.md, "The one rule"). Every file is converted to
WAV at the booth's sample rate by ffmpeg, with its demuxer forced to the format the magic bytes say, so ffmpeg never
guesses at a stranger's file (a playlist that fetches URLs, say). Then it is measured: length, peak, loudness, and
where its hits start, for the composer to cut slices at.

The booth only puts samples into Live; it never mixes, effects or edits them outside it. The loudness becomes the
part's starting fader level (`trim_db`), as an instrument's does.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from . import HOME

DIR = HOME / "samples"
SAMPLE_RATE = 44100          # what liveops.export renders at, so Live never resamples a sample
MAX_BYTES = 20 * 1024 * 1024
MAX_S = 60.0
MIN_S = 0.05
MAX_TOTAL_BYTES = 4 * 1024 ** 3   # all the converted files together; past it uploads are refused until some go
REF_LUFS = -23.0             # where the palette's instruments sit once trimmed: the median of 2026-12's survey
TRIM_DB = (-30.0, 12.0)
MAX_ONSETS = 32
ID = re.compile(r"^[0-9a-f]{16}$")
CONVERT_S = 60               # ffmpeg's time limit for one file


class SampleError(ValueError):
    """A file the booth won't take: `code` is stable for the bot, `status` is the HTTP answer."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def sniff(head: bytes) -> str | None:
    """The format the file's first bytes say ('wav', 'aiff', 'flac', 'mp3'), else None. Only these four."""
    if len(head) >= 12 and head[:4] in (b"RIFF", b"RF64") and head[8:12] == b"WAVE":
        return "wav"
    if len(head) >= 12 and head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    if head[:4] == b"fLaC":
        return "flac"
    if head[:3] == b"ID3":
        return "mp3"
    # an MPEG audio frame: 11 sync bits, then a layer that isn't 00 (00 is AAC's ADTS, not MP3)
    if len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0 and head[1] & 0x06:
        return "mp3"
    return None


def path(sid: str) -> Path:
    if not ID.fullmatch(sid):
        raise KeyError(sid)
    return DIR / f"{sid}.wav"


def info(sid: str) -> dict | None:
    """The sample's measurements, or None if the booth doesn't have it."""
    if not isinstance(sid, str) or not ID.fullmatch(sid):
        return None
    meta = DIR / f"{sid}.json"
    if not meta.is_file() or not (DIR / f"{sid}.wav").is_file():
        return None
    return json.loads(meta.read_text())


def public(meta: dict) -> dict:
    """What the bot sees of a sample."""
    keys = ("sample", "seconds", "channels", "sample_rate", "peak_db", "lufs", "onsets_s", "format")
    return {k: meta[k] for k in keys if k in meta}


def onsets(y: np.ndarray, sr: int, limit: int = MAX_ONSETS) -> list[float]:
    """Where hits start, in seconds: peaks of the rise in a short-time energy envelope, at least 60 ms apart. A guide
    for slicing, not a beat tracker."""
    mono = y.mean(axis=1) if y.ndim > 1 else y
    hop, win = 256, 1024
    if len(mono) < win:
        return [0.0]
    frames = np.lib.stride_tricks.sliding_window_view(mono, win)[::hop]
    env = np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    rise = np.maximum(0.0, np.diff(env, prepend=env[0]))
    thresh = max(0.3, float(np.median(rise) + 3 * np.std(rise)))
    gap = max(1, int(0.06 * sr / hop))
    out: list[int] = []
    for i in range(1, len(rise) - 1):
        if rise[i] >= thresh and rise[i] >= rise[i - 1] and rise[i] >= rise[i + 1] and (not out or i - out[-1] >= gap):
            out.append(i)
    strongest = sorted(sorted(out, key=lambda i: -rise[i])[:limit - 1])
    # a frame's energy jumps as soon as a hit enters its end, a window ahead of the hit: put it back, less a few ms,
    # so a slice cut here keeps its attack
    lead = (win - 2 * hop) / sr
    times = [0.0] + [round(i * hop / sr + lead, 3) for i in strongest if i * hop / sr + lead > 0.03]
    return times[:limit]


def _measure(wav: Path) -> dict:
    y, sr = sf.read(str(wav), always_2d=True)
    seconds = len(y) / sr
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak < 10 ** (-60 / 20):
        raise SampleError("silent", "the sample is silent (its peak is under -60 dBFS)")
    # BS.1770 needs 400 ms blocks: a one-shot is measured as itself repeated to a second, like a hit played in time
    reps = int(np.ceil(1.0 / seconds)) if seconds < 1.0 else 1
    lufs = float(pyln.Meter(sr).integrated_loudness(np.tile(y, (reps, 1))))
    lufs = lufs if np.isfinite(lufs) else -70.0
    return {"seconds": round(seconds, 4), "frames": len(y), "sample_rate": sr, "channels": y.shape[1],
            "peak_db": round(20 * np.log10(peak), 1), "lufs": round(lufs, 1),
            "trim_db": round(min(TRIM_DB[1], max(TRIM_DB[0], REF_LUFS - lufs)), 1), "onsets_s": onsets(y, sr)}


def _probe(src: Path, fmt: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-f", fmt, "-select_streams", "a:0",
                          "-show_entries", "stream=channels,sample_rate:format=duration", "-of", "json", str(src)],
                         capture_output=True, text=True, timeout=CONVERT_S)
    try:
        data = json.loads(out.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    if out.returncode or not data.get("streams"):
        raise SampleError("unreadable", f"ffprobe could not read it as {fmt}")
    return data


def _convert(src: Path, fmt: str, channels: int, dst: Path) -> None:
    """WAV, 24-bit, SAMPLE_RATE, mono or stereo, the first audio stream only, at most a little over MAX_S decoded."""
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-protocol_whitelist", "file", "-f", fmt, "-i", str(src),
                        "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1", "-t", f"{MAX_S + 1:.0f}",
                        "-ac", str(min(2, max(1, channels))), "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s24le", "-f", "wav", str(dst)],
                       check=True, capture_output=True, timeout=CONVERT_S)
    except subprocess.TimeoutExpired:
        raise SampleError("unreadable", f"ffmpeg took over {CONVERT_S} s") from None
    except subprocess.CalledProcessError as exc:
        raise SampleError("unreadable", f"ffmpeg could not convert it: {exc.stderr.decode(errors='ignore')[-200:].strip()}") from None


def _used() -> int:
    return sum(p.stat().st_size for p in DIR.glob("*.wav")) if DIR.is_dir() else 0


def add(data: bytes) -> tuple[dict, bool]:
    """Keep a sample: (its measurements, whether it is new). The same bytes always answer the same id. Raises
    SampleError for anything the booth won't take."""
    if len(data) > MAX_BYTES:
        raise SampleError("too_large", f"{len(data)} bytes; at most {MAX_BYTES}", 413)
    fmt = sniff(data[:16])
    if not fmt:
        raise SampleError("bad_format", "not a WAV, AIFF, FLAC or MP3 file (by its first bytes)", 415)
    sid = hashlib.sha256(data).hexdigest()[:16]
    old = info(sid)
    if old:
        return old, False
    if _used() + len(data) * 4 > MAX_TOTAL_BYTES:
        raise SampleError("storage_full", "the booth's sample folder is full", 507)
    DIR.mkdir(parents=True, exist_ok=True)
    work = DIR / f".in-{secrets.token_hex(6)}"
    work.mkdir()
    try:
        src = work / f"in.{fmt}"
        src.write_bytes(data)
        probe = _probe(src, fmt)
        duration = float(probe.get("format", {}).get("duration") or 0)
        if duration > MAX_S + 0.5:
            raise SampleError("too_long", f"{duration:.1f} s; at most {MAX_S:g} s")
        wav = work / "out.wav"
        _convert(src, fmt, int(probe["streams"][0].get("channels") or 2), wav)
        meta = _measure(wav)
        if meta["seconds"] > MAX_S + 0.01:            # the header lied: what decoded is what counts
            raise SampleError("too_long", f"over {MAX_S:g} s once decoded")
        if meta["seconds"] < MIN_S:
            raise SampleError("too_short", f"{meta['seconds']:.3f} s; at least {MIN_S:g} s")
        meta.update(sample=sid, format=fmt, bytes=len(data), added=round(time.time()))
        os.replace(wav, DIR / f"{sid}.wav")
        tmp = work / "meta.json"
        tmp.write_text(json.dumps(meta, indent=2) + "\n")
        os.replace(tmp, DIR / f"{sid}.json")           # last: a sample exists once its measurements do
        return meta, True
    finally:
        shutil.rmtree(work, ignore_errors=True)
