"""File hashing.

BLAKE3 over the whole file. Read in 1 MB chunks so a 500 MB WAV never lands in
memory all at once.
"""

from __future__ import annotations

from pathlib import Path

from blake3 import blake3

CHUNK_BYTES = 1 << 20  # 1 MB


def hash_file(path: Path, *, chunk_bytes: int = CHUNK_BYTES) -> str:
    """Return the BLAKE3 hex digest of the file's bytes.

    The file is opened read-only. Nothing is written, moved, or touched.
    """
    hasher = blake3()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_bytes)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Return the BLAKE3 hex digest of a bytes object. Used by tests."""
    return blake3(data).hexdigest()
