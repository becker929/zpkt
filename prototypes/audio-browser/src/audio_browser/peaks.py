"""Waveform peaks.

Format: ``BUCKETS`` buckets, 2 bytes each, minimum then maximum, both signed
8-bit. 1,000 buckets is 2,000 bytes per file, so the whole collection stays
under 10 MB.

Audio is decoded with ffmpeg to mono 22.05 kHz signed 16-bit and reduced to
buckets. Peaks are computed on demand, never during the initial scan: decoding
4,600 files up front would take hours and proves nothing about the index.
"""

from __future__ import annotations

import array
import shutil
import subprocess
import sqlite3
import sys
import threading
from pathlib import Path

BUCKETS = 1000
SAMPLE_RATE = 22_050
PEAKS_TIMEOUT_S = 300

# Below this many samples (about 12 minutes of mono 22.05 kHz audio) the
# reduction uses every sample. Above it, samples are folded into fixed windows
# first so a long DJ mix cannot fill memory.
_EXACT_SAMPLE_LIMIT = 16_777_216
_WINDOW = 512

_PCM_CHUNK = 1 << 18  # 256 KB of PCM per read


class PeaksError(Exception):
    """Raised when audio could not be decoded."""


def ffmpeg_available() -> bool:
    """True when ffmpeg is on PATH."""
    return shutil.which("ffmpeg") is not None


def compute_peaks(
    path: Path, *, buckets: int = BUCKETS, timeout_s: int = PEAKS_TIMEOUT_S
) -> bytes:
    """Decode one file and return its packed peaks blob.

    The file is opened by ffmpeg for reading only.
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
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
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
    except FileNotFoundError as exc:
        raise PeaksError("ffmpeg not found on PATH") from exc

    stderr_chunks: list[bytes] = []

    def drain_stderr() -> None:
        assert proc.stderr is not None
        stderr_chunks.append(proc.stderr.read())

    # ffmpeg blocks if its stderr pipe fills, so drain it on its own thread.
    drainer = threading.Thread(target=drain_stderr, daemon=True)
    drainer.start()

    acc = _PeakAccumulator(buckets=buckets)
    leftover = b""
    assert proc.stdout is not None
    try:
        while True:
            chunk = proc.stdout.read(_PCM_CHUNK)
            if not chunk:
                break
            if leftover:
                chunk = leftover + chunk
                leftover = b""
            extra = len(chunk) % 2
            if extra:
                leftover = chunk[-extra:]
                chunk = chunk[:-extra]
            acc.feed(_to_int16(chunk))
        proc.stdout.close()
        returncode = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        raise PeaksError(f"ffmpeg timed out after {timeout_s}s") from exc
    finally:
        drainer.join(timeout=5)

    if returncode != 0:
        detail = b"".join(stderr_chunks).decode("utf-8", "replace").strip()
        raise PeaksError(detail or f"ffmpeg exited {returncode}")

    return acc.result()


def decode_peaks(blob: bytes) -> list[tuple[int, int]]:
    """Unpack a peaks blob into (minimum, maximum) pairs of int8 values."""
    if len(blob) % 2:
        raise ValueError("peaks blob has an odd length")
    values = array.array("b")
    values.frombytes(blob)
    return [(values[i], values[i + 1]) for i in range(0, len(values), 2)]


def store_peaks(conn: sqlite3.Connection, file_hash: str, blob: bytes) -> None:
    """Save a peaks blob against a hash."""
    conn.execute("UPDATE blob SET peaks = ? WHERE hash = ?", (blob, file_hash))
    conn.commit()


def load_peaks(conn: sqlite3.Connection, file_hash: str) -> bytes | None:
    """Return the stored peaks blob for a hash, or None."""
    row = conn.execute(
        "SELECT peaks FROM blob WHERE hash = ?", (file_hash,)
    ).fetchone()
    if row is None or row["peaks"] is None:
        return None
    return bytes(row["peaks"])


def ensure_peaks(conn: sqlite3.Connection, file_hash: str) -> bytes:
    """Return the peaks for a hash, computing and caching them if needed.

    Any alias of the hash will do, since all aliases have identical bytes. The
    first readable one wins.
    """
    cached = load_peaks(conn, file_hash)
    if cached is not None:
        return cached

    rows = conn.execute(
        "SELECT path FROM alias WHERE hash = ? ORDER BY id", (file_hash,)
    ).fetchall()
    if not rows:
        raise PeaksError(f"no alias on disk for hash {file_hash}")

    last_error: str = "no readable alias"
    for row in rows:
        path = Path(row["path"])
        if not path.exists():
            last_error = f"missing file {path}"
            continue
        try:
            blob = compute_peaks(path)
        except PeaksError as exc:
            last_error = str(exc)
            continue
        store_peaks(conn, file_hash, blob)
        return blob
    raise PeaksError(last_error)


def _to_int16(raw: bytes) -> "array.array[int]":
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":
        samples.byteswap()  # the stream is little-endian
    return samples


def _scale(value: int) -> int:
    """int16 to int8. Floor division maps -32768..32767 onto -128..127."""
    return value // 256


class _PeakAccumulator:
    """Reduces a stream of int16 samples to bucket minima and maxima."""

    def __init__(self, *, buckets: int = BUCKETS) -> None:
        if buckets < 1:
            raise ValueError("buckets must be positive")
        self._buckets = buckets
        self._buf = array.array("h")
        self._win_min: list[int] = []
        self._win_max: list[int] = []
        self._coarse = False

    def feed(self, samples: "array.array[int]") -> None:
        if not samples:
            return
        self._buf.extend(samples)
        if self._coarse or len(self._buf) >= _EXACT_SAMPLE_LIMIT:
            self._coarse = True
            self._drain_windows()

    def result(self) -> bytes:
        if not self._coarse:
            samples = self._buf.tolist()
            return self._reduce(samples, samples)
        if self._buf:
            self._win_min.append(min(self._buf))
            self._win_max.append(max(self._buf))
            del self._buf[:]
        return self._reduce(self._win_min, self._win_max)

    def _drain_windows(self) -> None:
        whole = len(self._buf) - (len(self._buf) % _WINDOW)
        for start in range(0, whole, _WINDOW):
            window = self._buf[start : start + _WINDOW]
            self._win_min.append(min(window))
            self._win_max.append(max(window))
        del self._buf[:whole]

    def _reduce(self, mins: list[int], maxs: list[int]) -> bytes:
        out = array.array("b", bytes(2 * self._buckets))
        n = len(mins)
        if n == 0:
            return out.tobytes()
        for b in range(self._buckets):
            start = b * n // self._buckets
            end = (b + 1) * n // self._buckets
            if end <= start:
                end = min(start + 1, n)
            lo = _scale(min(mins[start:end]))
            hi = _scale(max(maxs[start:end]))
            out[2 * b] = lo
            out[2 * b + 1] = hi
        return out.tobytes()
