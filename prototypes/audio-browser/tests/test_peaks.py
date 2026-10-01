from __future__ import annotations

import array
import sqlite3
from pathlib import Path

import pytest

from audio_browser.config import Root
from audio_browser.peaks import (
    BUCKETS,
    PeaksError,
    _PeakAccumulator,
    _scale,
    compute_peaks,
    decode_peaks,
    ensure_peaks,
    load_peaks,
)
from audio_browser.scan import scan_roots
from conftest import needs_ffmpeg, write_wav


def quiet(_: str) -> None:
    return None


def test_scale_maps_int16_onto_int8() -> None:
    assert _scale(32767) == 127
    assert _scale(-32768) == -128
    assert _scale(0) == 0
    assert -128 <= _scale(-1) <= 0


def test_accumulator_output_is_two_bytes_per_bucket() -> None:
    acc = _PeakAccumulator(buckets=BUCKETS)
    acc.feed(array.array("h", [1000, -1000] * 5000))
    blob = acc.result()
    assert len(blob) == 2 * BUCKETS


def test_accumulator_finds_the_extremes() -> None:
    acc = _PeakAccumulator(buckets=4)
    acc.feed(array.array("h", [0, 0, 32767, -32768, 0, 0, 100, -100]))
    pairs = decode_peaks(acc.result())
    assert len(pairs) == 4
    assert pairs[1] == (-128, 127)
    assert all(lo <= hi for lo, hi in pairs)


def test_accumulator_handles_silence() -> None:
    acc = _PeakAccumulator(buckets=8)
    acc.feed(array.array("h", [0] * 800))
    assert decode_peaks(acc.result()) == [(0, 0)] * 8


def test_accumulator_handles_no_samples() -> None:
    assert _PeakAccumulator(buckets=8).result() == bytes(16)


def test_accumulator_handles_fewer_samples_than_buckets() -> None:
    acc = _PeakAccumulator(buckets=10)
    acc.feed(array.array("h", [20000, -20000]))
    pairs = decode_peaks(acc.result())
    assert len(pairs) == 10
    assert any(hi > 0 for _, hi in pairs)


def test_accumulator_streams_in_chunks() -> None:
    samples = [(i % 1000) * 30 - 15000 for i in range(20_000)]
    whole = _PeakAccumulator(buckets=50)
    whole.feed(array.array("h", samples))
    piecewise = _PeakAccumulator(buckets=50)
    for start in range(0, len(samples), 997):
        piecewise.feed(array.array("h", samples[start : start + 997]))
    assert whole.result() == piecewise.result()


def test_decode_peaks_rejects_an_odd_blob() -> None:
    with pytest.raises(ValueError):
        decode_peaks(b"\x00\x01\x02")


@needs_ffmpeg
def test_compute_peaks_on_a_real_wav(tmp_path: Path) -> None:
    path = write_wav(tmp_path / "tone.wav", seconds=1.0, freq=200, amplitude=0.9)
    blob = compute_peaks(path)
    assert len(blob) == 2 * BUCKETS
    pairs = decode_peaks(blob)
    assert all(lo <= hi for lo, hi in pairs)
    assert max(hi for _, hi in pairs) > 80  # a loud tone reaches near full scale
    assert min(lo for lo, _ in pairs) < -80


@needs_ffmpeg
def test_compute_peaks_rejects_a_non_audio_file(tmp_path: Path) -> None:
    junk = tmp_path / "junk.wav"
    junk.write_bytes(b"this is not audio")
    with pytest.raises(PeaksError):
        compute_peaks(junk)


@needs_ffmpeg
def test_ensure_peaks_caches_in_the_database(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    root = tmp_path / "lib"
    write_wav(root / "tone.wav", seconds=0.5, freq=300)
    scan_roots(
        conn, [Root(name="lib", path=root.resolve())], probe=False, log=quiet
    )
    digest = conn.execute("SELECT hash FROM blob").fetchone()["hash"]
    assert load_peaks(conn, digest) is None
    blob = ensure_peaks(conn, digest)
    assert load_peaks(conn, digest) == blob
    assert ensure_peaks(conn, digest) == blob  # served from cache


def test_ensure_peaks_without_an_alias_fails(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO blob (hash, size_bytes) VALUES ('h', 1)")
    with pytest.raises(PeaksError):
        ensure_peaks(conn, "h")
