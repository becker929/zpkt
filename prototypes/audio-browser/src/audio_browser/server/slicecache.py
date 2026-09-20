"""Encoded slices, kept beside the index.

Encoding a span costs a decode and an encode, and a looping transport asks for
the same spans again on every pass. The answer is kept so the second ask is a
file read.

**Where.** Beside the index file, never inside a collection root. The roots are
read-only and irreplaceable; the index directory is the one place this
application already writes.

**The key is the cut, not the rate.** A slice is always served at 1x — stretch
is `playbackRate` in the browser — so hash, start and end name the bytes
completely.

**The bound.** :data:`DEFAULT_LIMIT_BYTES` of encoded audio, evicted
least-recently-used. At 96 kbps that is about six hours of sound: far more than
any one collage (the first real project is twenty-five minutes of material)
and small beside the index it sits next to, let alone the sources it is cut
from. The cache is a convenience and never the only copy of anything, so the
bound is chosen to be generous and forgettable rather than tuned.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import struct
import tempfile
import threading
from pathlib import Path

from .streaming import EncodedSlice, slice_to_opus

DIR_NAME = "slice-cache"
"""The directory made beside the index file."""

DEFAULT_LIMIT_BYTES = 256 * 1024 * 1024

SUFFIX = ".slice"
"""One file per cut. The sample count is an eight-byte head on the bytes."""

_HEAD = struct.Struct("<Q")

# How far under the bound a prune goes, so a full cache does not prune on
# every single write.
_PRUNE_TO = 0.9


class SliceCache:
    """Encoded slices on disk, bounded and least-recently-used.

    Thread-safe. Routes run in Starlette's worker pool, so two requests for the
    same cut can arrive together: one encodes and the other waits on the same
    key's lock rather than running a second ffmpeg over the same span.
    """

    def __init__(
        self, directory: Path, *, limit_bytes: int = DEFAULT_LIMIT_BYTES
    ) -> None:
        self.directory = directory
        self.limit_bytes = limit_bytes
        self._lock = threading.Lock()
        self._keys: dict[str, threading.Lock] = {}
        self._bytes = 0
        self._ready = False

    # -- the one thing this is for ------------------------------------------

    def get(
        self, path: Path, file_hash: str, start_s: float, end_s: float
    ) -> EncodedSlice:
        """The encoded span, from disk if it is there and from ffmpeg if not."""
        name = _name(file_hash, start_s, end_s)
        found = self._read(name)
        if found is not None:
            return found
        with self._key_lock(name):
            # Another thread may have encoded it while this one waited.
            found = self._read(name)
            if found is not None:
                return found
            made = slice_to_opus(path, start_s, end_s)
            self._write(name, made)
            return made

    # -- disk ----------------------------------------------------------------

    def _read(self, name: str) -> EncodedSlice | None:
        file = self.directory / name
        try:
            raw = file.read_bytes()
        except OSError:
            return None
        if len(raw) <= _HEAD.size:
            return None
        # Touch it, so least-recently-used means what it says.
        with contextlib.suppress(OSError):
            os.utime(file)
        (frames,) = _HEAD.unpack_from(raw)
        return EncodedSlice(body=raw[_HEAD.size :], frames=int(frames))

    def _write(self, name: str, made: EncodedSlice) -> None:
        raw = _HEAD.pack(made.frames) + made.body
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Written whole and moved into place, so a reader never sees half
            # a file and a crash mid-write leaves the temporary one behind
            # rather than a cache entry that decodes to nothing.
            handle, temporary = tempfile.mkstemp(dir=self.directory, suffix=".part")
            try:
                with os.fdopen(handle, "wb") as fh:
                    fh.write(raw)
                os.replace(temporary, self.directory / name)
            except OSError:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
                raise
        except OSError:
            # A cache that cannot be written is a cache that is not used. The
            # slice was still encoded and the request still answers.
            return
        with self._lock:
            self._measure()
            self._bytes += len(raw)
            over = self._bytes > self.limit_bytes
        if over:
            self._prune()

    def _measure(self) -> None:
        """Add up what is already there, once, on the first write."""
        if self._ready:
            return
        self._ready = True
        total = 0
        with contextlib.suppress(OSError):
            for entry in os.scandir(self.directory):
                if entry.name.endswith(SUFFIX):
                    with contextlib.suppress(OSError):
                        total += entry.stat().st_size
        self._bytes = total

    def _prune(self) -> None:
        """Drop the least recently used until the cache is under its bound.

        This removes encoded copies and nothing else. No audio in a collection
        root is ever named here: the only paths this class opens are inside its
        own directory.
        """
        with self._lock:
            entries: list[tuple[float, int, Path]] = []
            with contextlib.suppress(OSError):
                for entry in os.scandir(self.directory):
                    if not entry.name.endswith(SUFFIX):
                        continue
                    with contextlib.suppress(OSError):
                        stat = entry.stat()
                        entries.append((stat.st_mtime, stat.st_size, Path(entry.path)))
            total = sum(size for _, size, _ in entries)
            target = int(self.limit_bytes * _PRUNE_TO)
            for _, size, file in sorted(entries):
                if total <= target:
                    break
                try:
                    file.unlink()
                except OSError:
                    continue
                total -= size
            self._bytes = total

    # -- locks ---------------------------------------------------------------

    def _key_lock(self, name: str) -> threading.Lock:
        with self._lock:
            lock = self._keys.get(name)
            if lock is None:
                lock = threading.Lock()
                self._keys[name] = lock
            return lock


def _name(file_hash: str, start_s: float, end_s: float) -> str:
    """A filename for one cut.

    The hash is already 64 hex characters and the span is two numbers, so the
    key is digested rather than spelled out: a filename stays short, and a
    float's text can hold a dot, a minus and an exponent.
    """
    key = f"{file_hash}:{start_s:.6f}:{end_s:.6f}".encode()
    return hashlib.sha256(key).hexdigest() + SUFFIX
