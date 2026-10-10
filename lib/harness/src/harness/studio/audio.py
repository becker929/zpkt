"""ffmpeg for the chat's audio: MP3 replays of speech, FLAC for music (lossless and gapless, so loops are exact)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class AudioError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioInfo:
    duration: float
    rate: int
    channels: int


async def _run(*args: str, stdin: bytes | None = None, timeout: float = 120) -> bytes:
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise AudioError(f"{args[0]} took more than {timeout:.0f} s") from None
    if proc.returncode != 0:
        raise AudioError(f"{args[0]} failed: {err.decode(errors='replace')[-500:]}")
    return out


async def pcm_to_mp3(pcm: bytes, rate: int, kbps: int = 48) -> bytes:
    """Mono s16le PCM to an MP3 for replay."""
    return await _run(FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(rate), "-ac", "1",
                      "-i", "pipe:0", "-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-f", "mp3", "pipe:1", stdin=pcm)


async def probe(path: Path) -> AudioInfo:
    out = await _run(FFPROBE, "-v", "error", "-select_streams", "a:0", "-show_entries",
                     "stream=sample_rate,channels:format=duration", "-of", "json", str(path), timeout=30)
    info = json.loads(out)
    stream = (info.get("streams") or [{}])[0]
    try:
        return AudioInfo(duration=float(info["format"]["duration"]), rate=int(stream["sample_rate"]),
                         channels=int(stream["channels"]))
    except (KeyError, ValueError) as exc:
        raise AudioError(f"{path.name} has no readable audio stream") from exc


async def to_flac(path: Path) -> tuple[bytes, AudioInfo]:
    """Any audio file to 16-bit FLAC at its own sample rate (dithered when it had more bits)."""
    info = await probe(path)
    data = await _run(FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
                      "-af", "aresample=dither_method=triangular", "-sample_fmt", "s16", "-c:a", "flac",
                      "-compression_level", "5", "-f", "flac", "pipe:1")
    return data, info
