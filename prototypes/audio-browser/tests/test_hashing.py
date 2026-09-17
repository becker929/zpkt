from __future__ import annotations

from pathlib import Path

from audio_browser.hashing import hash_bytes, hash_file
from conftest import write_wav


def test_same_bytes_same_hash(tmp_path: Path) -> None:
    a = write_wav(tmp_path / "a.wav", freq=100)
    b = write_wav(tmp_path / "b.wav", freq=100)
    assert hash_file(a) == hash_file(b)


def test_different_bytes_different_hash(tmp_path: Path) -> None:
    a = write_wav(tmp_path / "a.wav", freq=100)
    b = write_wav(tmp_path / "b.wav", freq=200)
    assert hash_file(a) != hash_file(b)


def test_hash_is_blake3_of_contents(tmp_path: Path) -> None:
    path = tmp_path / "raw.bin"
    payload = b"0123456789" * 1000
    path.write_bytes(payload)
    assert hash_file(path) == hash_bytes(payload)


def test_chunking_does_not_change_the_digest(tmp_path: Path) -> None:
    path = tmp_path / "raw.bin"
    payload = bytes(range(256)) * 900  # larger than the tiny chunk below
    path.write_bytes(payload)
    assert hash_file(path, chunk_bytes=7) == hash_file(path, chunk_bytes=1 << 20)


def test_empty_file_hashes(tmp_path: Path) -> None:
    path = tmp_path / "empty.wav"
    path.write_bytes(b"")
    assert hash_file(path) == hash_bytes(b"")
