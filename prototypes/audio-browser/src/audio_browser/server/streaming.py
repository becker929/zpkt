"""Byte delivery: HTTP ranges for native formats, ffmpeg for AIFF.

Files are opened ``"rb"`` and nothing else. The source trees are read-only at
the filesystem level, so any write would fail with EACCES; this module gives it
no chance to try.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

CHUNK_SIZE = 1 << 18  # 256 KB

MAX_SLICE_S = 120.0
"""The longest span one slice request may ask for.

A region is a phrase cut from a source, not the source itself. Two minutes is
23 MB of decoded PCM, which is the most the server will hold in memory while it
encodes one request, and 1.4 MB once encoded.
"""

SLICE_RATE = 48_000
SLICE_CHANNELS = 2
SLICE_SAMPLE_BYTES = 2
"""The one shape every slice comes back in: 48 kHz, stereo.

Sources mix 44.1 kHz and 48 kHz, mono and stereo. Cutting them into one shape
here means the client decodes one kind of thing and never has to resample or
match channels itself.
"""

SLICE_BITRATE = "96k"
"""What a slice is encoded at, in an Ogg container: Opus at 96 kbps.

PCM at the shape above is 192 KB per second of audio, and the browser is an
audition surface rather than a mastering one: what goes to a phone only has to
be good enough to judge an arrangement by ear. The originals never move.

Opus and not AAC or MP3 because those add encoder priming — measured at 896
samples for AAC — which would shift every region and break the sample-exact
seam a region's repeats are joined at. Opus decodes to exactly the sample count
it was given, in Chromium and in WebKit. Measured on this collection's own
material, a fifteen-second slice goes from 2,880,044 bytes to about 191,000.
"""

SLICE_MEDIA_TYPE = "audio/ogg"
SLICE_FILE_EXT = ".opus"

SLICE_TIMEOUT_S = 60.0

# Browsers play these directly, so the bytes go out untouched with range support.
MEDIA_TYPES: dict[str, str] = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
}

# AIFF support is uneven across browsers, so these are transcoded to WAV.
TRANSCODE_EXTS = frozenset({".aif", ".aiff"})
TRANSCODE_MEDIA_TYPE = "audio/wav"

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)", re.IGNORECASE)


class RangeNotSatisfiable(Exception):
    """The requested range lies outside the file."""


class TranscodeError(Exception):
    """ffmpeg could not decode the file."""


def media_type_for(ext: str) -> str:
    """The Content-Type to send for an extension, after any transcoding."""
    lower = ext.lower()
    if lower in TRANSCODE_EXTS:
        return TRANSCODE_MEDIA_TYPE
    return MEDIA_TYPES.get(lower, "application/octet-stream")


def needs_transcode(ext: str) -> bool:
    """True when the extension must go through ffmpeg before a browser sees it."""
    return ext.lower() in TRANSCODE_EXTS


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Turn a ``Range`` header into inclusive ``(start, end)`` offsets.

    Returns None when there is no usable range and the whole file should be
    sent. Only the first range of a multi-range request is honoured, which is
    what audio elements ask for anyway.

    Raises :class:`RangeNotSatisfiable` when the range starts past the end.
    """
    if not header or size <= 0:
        return None
    match = _RANGE_RE.match(header.strip())
    if match is None:
        return None  # a malformed or non-byte unit means "send the whole thing"

    raw_start, raw_end = match.group(1), match.group(2)
    if not raw_start and not raw_end:
        return None

    if not raw_start:
        # "bytes=-500" means the last 500 bytes.
        length = int(raw_end)
        if length <= 0:
            raise RangeNotSatisfiable("suffix range of zero bytes")
        start = max(size - length, 0)
        end = size - 1
    else:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1

    if start >= size:
        raise RangeNotSatisfiable(f"range starts at {start}, file is {size} bytes")
    end = min(end, size - 1)
    if end < start:
        raise RangeNotSatisfiable(f"range {start}-{end} is empty")
    return start, end


def read_range(
    path: Path, start: int, end: int, *, chunk_size: int = CHUNK_SIZE
) -> Iterator[bytes]:
    """Yield bytes ``start..end`` inclusive. Read-only, never buffered whole."""
    remaining = end - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def transcode_to_wav(
    path: Path, *, chunk_size: int = CHUNK_SIZE
) -> Iterator[bytes]:
    """Decode a file to WAV with ffmpeg and yield the result as it appears.

    The response cannot be seeked: ffmpeg writes a streaming WAV header with an
    unknown length. That is acceptable for a first version.

    The first chunk is read before the iterator is returned, so a file ffmpeg
    cannot open raises :class:`TranscodeError` instead of producing a truncated
    200 response.
    """
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-map",
        "a:0",
        "-f",
        "wav",
        "-acodec",
        "pcm_s16le",
        "-",
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:  # pragma: no cover - ffmpeg is a hard dep
        raise TranscodeError("ffmpeg not found on PATH") from exc

    assert proc.stdout is not None
    first = proc.stdout.read(chunk_size)
    if not first:
        _fail(proc)

    return _pump(proc, first, chunk_size)


def _pump(
    proc: subprocess.Popen[bytes], first: bytes, chunk_size: int
) -> Iterator[bytes]:
    assert proc.stdout is not None
    try:
        yield first
        while True:
            chunk = proc.stdout.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        # A client that closes the connection mid-track closes this generator.
        # Kill ffmpeg rather than leaving it writing into a dead pipe.
        if proc.poll() is None:
            proc.kill()
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
        proc.wait()


def _fail(proc: subprocess.Popen[bytes]) -> None:
    detail = b""
    if proc.stderr is not None:
        detail = proc.stderr.read()
        proc.stderr.close()
    if proc.stdout is not None:
        proc.stdout.close()
    code = proc.wait()
    message = detail.decode("utf-8", "replace").strip() or f"ffmpeg exited {code}"
    raise TranscodeError(message)


@dataclass(frozen=True, slots=True)
class EncodedSlice:
    """One span of a source, encoded, with the sample count it holds.

    ``frames`` is samples per channel, counted off the decoded PCM before it
    was encoded. It is the number the browser's decode must come back with,
    and the route sends it as a header so the player can check rather than
    assume. A span that runs past the end of a sound is shorter than it asked
    for, which is why the count is measured and not worked out from the span.
    """

    body: bytes
    frames: int


def slice_pcm(path: Path, start_s: float, end_s: float) -> bytes:
    """Cut ``start_s..end_s`` out of a source as raw PCM.

    ffmpeg seeks to ``start_s`` on the input side, which decodes from the
    nearest frame it can and discards up to the instant asked for, so the cut
    is sample-accurate for PCM and frame-accurate for MP3 and AAC. It writes
    raw PCM at :data:`SLICE_RATE` and :data:`SLICE_CHANNELS`, so the sample
    count is the byte count divided by the frame size and nothing has to be
    parsed to know it.

    The whole span is held in memory, which :data:`MAX_SLICE_S` bounds. The
    source is only ever read.

    Raises :class:`TranscodeError` when ffmpeg cannot open the file or when the
    span lies past the end of it, so the route can answer 422 rather than
    return a sound with nothing in it.
    """
    if end_s <= start_s:
        raise TranscodeError("the span ends before it starts")
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{start_s:.6f}",
        "-i",
        str(path),
        "-t",
        f"{end_s - start_s:.6f}",
        "-map",
        "a:0",
        "-ar",
        str(SLICE_RATE),
        "-ac",
        str(SLICE_CHANNELS),
        "-acodec",
        "pcm_s16le",
        "-f",
        "s16le",
        "-",
    ]
    done = _run(cmd, b"", "cut the span")
    frame = SLICE_CHANNELS * SLICE_SAMPLE_BYTES
    pcm = done[: len(done) - len(done) % frame]
    if not pcm:
        raise TranscodeError("the span lies past the end of the sound")
    return pcm


def encode_opus(pcm: bytes) -> bytes:
    """Encode raw PCM to Opus in an Ogg container at :data:`SLICE_BITRATE`.

    The Ogg Opus header carries the encoder's pre-skip and the last page's
    granule position carries the end trim, so a decoder hands back exactly the
    samples that went in. That is what lets a region's repeats meet without a
    seam: nothing is added at either end.
    """
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-f",
        "s16le",
        "-ar",
        str(SLICE_RATE),
        "-ac",
        str(SLICE_CHANNELS),
        "-i",
        "pipe:0",
        "-c:a",
        "libopus",
        "-b:a",
        SLICE_BITRATE,
        "-ar",
        str(SLICE_RATE),
        "-ac",
        str(SLICE_CHANNELS),
        "-f",
        "ogg",
        "pipe:1",
    ]
    body = _run(cmd, pcm, "encode the span")
    if not body:
        raise TranscodeError("the encoder produced nothing")
    return body


def slice_to_opus(path: Path, start_s: float, end_s: float) -> EncodedSlice:
    """One span of a source, decoded to the slice shape and encoded to Opus."""
    pcm = slice_pcm(path, start_s, end_s)
    frames = len(pcm) // (SLICE_CHANNELS * SLICE_SAMPLE_BYTES)
    return EncodedSlice(body=encode_opus(pcm), frames=frames)


def _run(cmd: list[str], stdin: bytes, what: str) -> bytes:
    """Run ffmpeg over a bounded input and give back its stdout."""
    try:
        done = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            timeout=SLICE_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - ffmpeg is a hard dep
        raise TranscodeError("ffmpeg not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f"ffmpeg took too long to {what}") from exc
    if done.returncode != 0:
        message = done.stderr.decode("utf-8", "replace").strip()
        raise TranscodeError(message or f"ffmpeg exited {done.returncode}")
    return done.stdout


def content_disposition(filename: str) -> str:
    """An inline disposition that survives non-ASCII filenames.

    The plain ``filename`` is stripped to ASCII for old clients; the RFC 5987
    ``filename*`` carries the real name.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    safe = (
        ascii_name.replace('"', "'")
        .replace("\\", "_")
        .replace("\r", "")
        .replace("\n", "")
    )
    return f"inline; filename=\"{safe}\"; filename*=UTF-8''{quote(filename)}"
