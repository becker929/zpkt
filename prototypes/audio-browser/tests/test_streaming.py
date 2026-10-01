from __future__ import annotations

from pathlib import Path

import pytest

from audio_browser.server.streaming import (
    RangeNotSatisfiable,
    content_disposition,
    media_type_for,
    needs_transcode,
    parse_range,
    read_range,
)


def test_no_header_means_whole_file() -> None:
    assert parse_range(None, 100) is None
    assert parse_range("", 100) is None


def test_open_ended_range() -> None:
    assert parse_range("bytes=10-", 100) == (10, 99)


def test_closed_range() -> None:
    assert parse_range("bytes=10-19", 100) == (10, 19)


def test_range_past_the_end_is_clamped() -> None:
    assert parse_range("bytes=90-500", 100) == (90, 99)


def test_suffix_range_counts_back_from_the_end() -> None:
    assert parse_range("bytes=-30", 100) == (70, 99)


def test_suffix_longer_than_the_file_starts_at_zero() -> None:
    assert parse_range("bytes=-500", 100) == (0, 99)


def test_only_the_first_range_of_a_multi_range_is_used() -> None:
    assert parse_range("bytes=0-9,20-29", 100) == (0, 9)


def test_start_past_the_end_is_not_satisfiable() -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=100-", 100)


def test_zero_length_suffix_is_not_satisfiable() -> None:
    with pytest.raises(RangeNotSatisfiable):
        parse_range("bytes=-0", 100)


def test_unparseable_header_falls_back_to_the_whole_file() -> None:
    assert parse_range("items=0-10", 100) is None
    assert parse_range("bytes=abc", 100) is None


def test_empty_file_has_no_range() -> None:
    assert parse_range("bytes=0-", 0) is None


def test_read_range_returns_exactly_those_bytes(tmp_path: Path) -> None:
    path = tmp_path / "blob.bin"
    path.write_bytes(bytes(range(256)))
    assert b"".join(read_range(path, 10, 19, chunk_size=3)) == bytes(range(10, 20))


def test_read_range_opens_read_only(tmp_path: Path) -> None:
    """A source tree is read-only. Reading must not need write permission."""
    path = tmp_path / "blob.bin"
    path.write_bytes(b"0123456789")
    path.chmod(0o444)
    assert b"".join(read_range(path, 0, 9)) == b"0123456789"


def test_media_types() -> None:
    assert media_type_for(".wav") == "audio/wav"
    assert media_type_for(".MP3") == "audio/mpeg"
    assert media_type_for(".m4a") == "audio/mp4"
    assert media_type_for(".flac") == "audio/flac"
    # AIFF is transcoded, so what the client receives is WAV.
    assert media_type_for(".aif") == "audio/wav"
    assert media_type_for(".xyz") == "application/octet-stream"


def test_needs_transcode_only_for_aiff() -> None:
    assert needs_transcode(".aif")
    assert needs_transcode(".AIFF")
    assert not needs_transcode(".wav")
    assert not needs_transcode(".mp3")


def test_content_disposition_survives_non_ascii_and_quotes() -> None:
    header = content_disposition('kick "loud" ü.wav')
    assert header.startswith("inline; ")
    assert '"' in header
    assert "filename*=UTF-8''" in header
    assert "\n" not in header and "\r" not in header
