"""ffmpeg for the chat's audio: MP3 for everything, replays of speech and music alike.

Music used to be FLAC, which iPhone Safari's Web Audio cannot decode ("EncodingError: Decoding failed"). MP3 at
LAME's V0 is transparent, a fifth of a WAV's size, and gapless: LAME's header gives the encoder delay and padding,
and both WebKit and Chromium trim them, so a decoded render has exactly its source's samples and loops are exact
(AAC in MP4 left 208 extra samples in WebKit).
"""

from __future__ import annotations

import asyncio
import json
import tempfile
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
    except BaseException as exc:             # timed out, or the turn was cancelled: never leave it running
        proc.kill()
        await asyncio.shield(proc.wait())
        if isinstance(exc, TimeoutError):
            raise AudioError(f"{args[0]} took more than {timeout:.0f} s") from None
        raise
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
        rate, channels = int(stream["sample_rate"]), int(stream["channels"])
    except (KeyError, ValueError) as exc:
        raise AudioError(f"{path.name} has no readable audio stream") from exc
    try:
        duration = float(info["format"]["duration"])
    except (KeyError, ValueError):
        duration = await _decoded_seconds(path, rate, channels)
    return AudioInfo(duration=duration, rate=rate, channels=channels)


async def _decoded_seconds(path: Path, rate: int, channels: int) -> float:
    """How long a file is, by decoding it: a FLAC written to a pipe has no length in its header (the old music)."""
    pcm = await _run(FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
                     "-f", "s16le", "-ac", str(channels), "-ar", str(rate), "pipe:1")
    if not pcm:
        raise AudioError(f"{path.name} has no readable audio stream")
    return len(pcm) / (2 * channels * rate)


async def to_mp3(path: Path) -> tuple[bytes, AudioInfo]:
    """A render to a V0 MP3 at its own sample rate, with LAME's gapless header. It is written to a file: on a pipe
    ffmpeg cannot go back to fill in that header, and without it each loop comes out 1536 samples long."""
    info = await probe(path)
    with tempfile.TemporaryDirectory(prefix="studio-mp3-") as tmp:
        out = Path(tmp) / "render.mp3"
        await _run(FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
                   "-map_metadata", "-1", "-c:a", "libmp3lame", "-q:a", "0", str(out))
        data = out.read_bytes()
    return data, info
