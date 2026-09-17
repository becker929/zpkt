"""Silence: parsing a measurement, storing it, and reading it at a floor.

The parsing tests take a real ffmpeg log as a string, so they run without
ffmpeg. The one test that actually decodes is marked and skipped when ffmpeg is
not on PATH.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from audio_browser import silence
from audio_browser.db import open_db

from conftest import Fixture, needs_ffmpeg, tree_snapshot, write_wav

# A real ffmpeg log, cut down to the lines the parser reads.
LOG = """
[silencedetect @ 0x14f] silence_start: 0
[silencedetect @ 0x14f] silence_end: 10.0512 | silence_duration: 10.0512
[silencedetect @ 0x14f] silence_start: 12.2
[silencedetect @ 0x14f] silence_end: 13.1 | silence_duration: 0.9
[Parsed_volumedetect_1 @ 0x15a] mean_volume: -31.4 dB
[Parsed_volumedetect_1 @ 0x15a] max_volume: -2.1 dB
frame= 1 fps=0.0 q=-0.0 Lsize=N/A time=00:00:30.00 bitrate=N/A speed=99x
"""

# The same, but the file ends inside a gap: a start with no end.
TRAILING_LOG = """
[silencedetect @ 0x14f] silence_start: 20.5
frame= 1 fps=0.0 q=-0.0 Lsize=N/A time=00:00:30.00 bitrate=N/A speed=99x
"""


def test_the_parser_reads_every_gap_and_both_levels() -> None:
    measured = silence.parse(LOG)
    assert [(i.start_s, i.end_s) for i in measured.intervals] == [
        (0.0, 10.0512),
        (12.2, 13.1),
    ]
    assert measured.max_db == -2.1 and measured.mean_db == -31.4
    assert measured.duration_s == pytest.approx(30.0)
    assert measured.silent_s == pytest.approx(10.9512)


def test_a_gap_that_runs_off_the_end_is_closed_at_the_end() -> None:
    """Trailing silence is where most of the eleven hours are. Do not lose it."""
    measured = silence.parse(TRAILING_LOG)
    assert [(i.start_s, i.end_s) for i in measured.intervals] == [(20.5, 30.0)]


def test_an_empty_log_measures_nothing_rather_than_failing() -> None:
    measured = silence.parse("")
    assert measured.intervals == () and measured.duration_s is None
    assert measured.silent_frac == 0.0


# ------------------------------------------------------------- the 2s floor


def test_the_floor_is_applied_when_the_gaps_are_read_not_when_stored() -> None:
    """Store everything down to 0.4 s; filter here. The floor is a setting."""
    raw = [
        silence.Interval(0.0, 0.5),
        silence.Interval(2.0, 5.0),
        silence.Interval(9.0, 10.0),
    ]
    assert len(silence.merged(raw, min_gap_s=2.0)) == 1
    assert len(silence.merged(raw, min_gap_s=0.4)) == 3
    assert len(silence.merged(raw, min_gap_s=10.0)) == 0


def test_overlapping_gaps_are_merged_so_the_arithmetic_stays_honest() -> None:
    raw = [silence.Interval(0.0, 5.0), silence.Interval(3.0, 9.0)]
    assert [(i.start_s, i.end_s) for i in silence.merged(raw)] == [(0.0, 9.0)]
    assert silence.silent_seconds(silence.merged(raw)) == pytest.approx(9.0)


def test_a_gap_is_clamped_to_the_length_of_the_sound() -> None:
    raw = [silence.Interval(0.0, 99.0)]
    assert silence.merged(raw, duration_s=30.0)[0].end_s == 30.0


def test_sounding_is_null_when_the_wall_duration_is_unknown() -> None:
    """A sounding length derived from nothing is worse than no number at all."""
    assert silence.sounding_seconds(None, []) is None
    assert silence.sounding_seconds(30.0, [silence.Interval(0.0, 10.0)]) == pytest.approx(20.0)


# ------------------------------------------------------------------ storage


def measure_fixture(conn: sqlite3.Connection, file_hash: str) -> None:
    """One sound with three gaps, one of which is under the floor."""
    conn.execute(
        "INSERT INTO silence (hash, max_db, mean_db, silent_s, duration_s,"
        " silent_frac, measured_at) VALUES (?, -2.1, -31.4, 21.0, 30.0, 0.7,"
        " '2026-09-17T00:00:00Z')",
        (file_hash,),
    )
    conn.executemany(
        "INSERT INTO silence_interval (hash, start_s, end_s) VALUES (?, ?, ?)",
        [(file_hash, 0.0, 10.0), (file_hash, 12.0, 13.0), (file_hash, 20.0, 30.0)],
    )
    conn.commit()


def test_a_measurement_replaces_the_one_before_it(tmp_path: Path) -> None:
    conn = open_db(tmp_path / "index.db")
    digest = "a" * 64
    first = silence.Measurement(
        max_db=-1.0, mean_db=-20.0, duration_s=10.0,
        intervals=(silence.Interval(0.0, 5.0), silence.Interval(6.0, 7.0)),
    )
    assert silence.write(conn, digest, first, at="2026-09-17T00:00:00Z") == 2

    second = silence.Measurement(
        max_db=-1.0, mean_db=-20.0, duration_s=10.0,
        intervals=(silence.Interval(0.0, 1.0),),
    )
    assert silence.write(conn, digest, second, at="2026-09-17T01:00:00Z") == 1
    rows = conn.execute(
        "SELECT start_s FROM silence_interval WHERE hash = ?", (digest,)
    ).fetchall()
    assert len(rows) == 1, "re-measuring replaces rather than doubles"
    conn.close()


def test_unmeasured_skips_what_is_already_done_so_the_run_restarts(
    tmp_path: Path,
) -> None:
    from audio_browser.config import Root
    from audio_browser.scan import scan_roots

    source = tmp_path / "source"
    write_wav(source / "one.wav")
    write_wav(source / "two.wav", freq=880)
    conn = open_db(tmp_path / "index.db")
    scan_roots(conn, [Root("source", source.resolve())], workers=1, probe=False,
               log=lambda _: None)

    assert len(silence.unmeasured(conn)) == 2
    first = silence.unmeasured(conn)[0][0]
    silence.write(
        conn,
        first,
        silence.Measurement(max_db=None, mean_db=None, duration_s=1.0, intervals=()),
        at="2026-09-17T00:00:00Z",
    )
    remaining = silence.unmeasured(conn)
    assert len(remaining) == 1 and remaining[0][0] != first
    conn.close()


def test_a_discarded_sound_is_left_out_unless_asked_for(tmp_path: Path) -> None:
    from audio_browser.config import Root
    from audio_browser.scan import scan_roots

    source = tmp_path / "source"
    write_wav(source / "one.wav")
    conn = open_db(tmp_path / "index.db")
    scan_roots(conn, [Root("source", source.resolve())], workers=1, probe=False,
               log=lambda _: None)
    digest = silence.unmeasured(conn)[0][0]
    conn.execute(
        "INSERT INTO soft_delete (hash, deleted_at) VALUES (?, '2026-09-17T00:00:00Z')",
        (digest,),
    )
    conn.commit()

    assert silence.unmeasured(conn) == []
    assert len(silence.unmeasured(conn, include_discarded=True)) == 1
    conn.close()


# -------------------------------------------------------------------- route


def test_the_route_reports_intervals_and_a_sounding_length(api: Fixture) -> None:
    loop = api.hash_of("loop.mp3")  # 30 s wall
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    conn.close()

    body = api.client.get(f"/api/files/{loop}/silence").json()
    assert body["measured"] is True
    assert body["min_gap"] == 2.0
    # The 1 second gap is under the floor and is not reported or subtracted.
    assert [(i["start_s"], i["end_s"]) for i in body["intervals"]] == [
        (0.0, 10.0),
        (20.0, 30.0),
    ]
    assert body["silent_s"] == pytest.approx(20.0)
    assert body["sounding_s"] == pytest.approx(10.0)
    assert body["max_db"] == -2.1


def test_the_floor_can_be_lowered_without_re_measuring(api: Fixture) -> None:
    loop = api.hash_of("loop.mp3")
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    conn.close()

    body = api.client.get(f"/api/files/{loop}/silence?min_gap=0.4").json()
    assert len(body["intervals"]) == 3
    assert body["sounding_s"] == pytest.approx(9.0)


def test_an_unmeasured_sound_answers_200_and_says_so(api: Fixture) -> None:
    """Measured-and-silent-nowhere and never-measured mean opposite things."""
    body = api.client.get(f"/api/files/{api.hash_of('kick.wav')}/silence").json()
    assert body["measured"] is False
    assert body["intervals"] == []
    assert body["sounding_s"] is None, "no evidence is not evidence of no silence"


def test_an_unknown_hash_is_a_404(api: Fixture) -> None:
    assert api.client.get(f"/api/files/{'b' * 64}/silence").status_code == 404


def test_a_negative_floor_is_refused(api: Fixture) -> None:
    response = api.client.get(f"/api/files/{api.hash_of('kick.wav')}/silence?min_gap=-1")
    assert response.status_code == 422


def test_the_route_rewrites_nothing_on_disk(api: Fixture) -> None:
    """Skipping changes playback only. It never rewrites a file."""
    before = {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")}
    for name in api.hashes:
        api.client.get(f"/api/files/{api.hash_of(name)}/silence")
    assert {root: tree_snapshot(api.tmp_path / root) for root in ("source", "copy")} == before


# ------------------------------------------------ sounding in the list views


def test_a_list_row_carries_its_sounding_length(api: Fixture) -> None:
    loop = api.hash_of("loop.mp3")
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    conn.close()

    rows = {r["hash"]: r for r in api.client.get("/api/files").json()["items"]}
    assert rows[loop]["duration_s"] == pytest.approx(30.0)
    assert rows[loop]["sounding_s"] == pytest.approx(10.0)
    # Unmeasured sounds say nothing rather than repeating their wall duration.
    assert rows[api.hash_of("kick.wav")]["sounding_s"] is None


def test_files_can_be_sorted_by_sounding_length(api: Fixture) -> None:
    """The frontend asks for this and currently retries after a 422."""
    loop = api.hash_of("loop.mp3")
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    # kick is 1.5 s wall and sounds all the way through.
    conn.execute(
        "INSERT INTO silence (hash, silent_s, duration_s, silent_frac, measured_at)"
        " VALUES (?, 0.0, 1.5, 0.0, '2026-09-17T00:00:00Z')",
        (api.hash_of("kick.wav"),),
    )
    conn.commit()
    conn.close()

    response = api.client.get("/api/files?sort=sounding&order=desc")
    assert response.status_code == 200
    order = [row["hash"] for row in response.json()["items"]]
    # loop sounds for 10 s and kick for 1.5 s, so loop comes first even though
    # both are shorter than loop's 30 s wall duration would suggest.
    assert order[0] == loop and order[1] == api.hash_of("kick.wav")
    # The unmeasured sound has no sounding length, so it sits at the end.
    assert order[2] == api.hash_of("hat.wav")


def test_the_detail_view_carries_a_sounding_length(api: Fixture) -> None:
    loop = api.hash_of("loop.mp3")
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    conn.close()
    assert api.client.get(f"/api/files/{loop}").json()["sounding_s"] == pytest.approx(10.0)


def test_stats_report_sounding_time_and_how_much_is_measured(api: Fixture) -> None:
    loop = api.hash_of("loop.mp3")
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    conn.close()

    body = api.client.get("/api/stats").json()
    # 30 + 1.5 + 0.25 wall, of which 20 seconds of loop is dead air.
    assert body["total_duration_s"] == pytest.approx(31.75)
    assert body["total_sounding_s"] == pytest.approx(11.75)
    assert body["measured_blobs"] == 1


def test_a_project_reports_its_sounding_time(api: Fixture) -> None:
    """A board card shows playing time. The dead air is not work to be done."""
    loop = api.hash_of("loop.mp3")
    conn = sqlite3.connect(api.db_path)
    measure_fixture(conn, loop)
    conn.close()

    project_id = api.project_id("a set")
    api.client.put(f"/api/projects/{project_id}/sounds/{loop}")
    body = api.client.get(f"/api/projects/{project_id}").json()["summary"]
    assert body["duration_s"] == pytest.approx(30.0)
    assert body["sounding_s"] == pytest.approx(10.0)


# -------------------------------------------------------------- with ffmpeg


@needs_ffmpeg
def test_measuring_a_real_file_finds_its_leading_silence(tmp_path: Path) -> None:
    """One decode, and the file is exactly as it was afterwards."""
    import struct
    import wave

    path = tmp_path / "quiet-then-loud.wav"
    rate = 8000
    frames = bytearray()
    frames += struct.pack("<h", 0) * (rate * 3)  # 3 seconds of digital silence
    for i in range(rate * 2):
        frames += struct.pack("<h", int(16000 * ((i % 100) / 100 - 0.5)))
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes(bytes(frames))
    before = path.stat()

    measured = silence.measure(path)
    assert measured.intervals, "three seconds of digital silence is a gap"
    assert measured.intervals[0].start_s == pytest.approx(0.0, abs=0.1)
    assert measured.intervals[0].end_s == pytest.approx(3.0, abs=0.2)
    after = path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


@needs_ffmpeg
def test_measuring_a_file_ffmpeg_cannot_read_is_an_error(tmp_path: Path) -> None:
    bad = tmp_path / "not-audio.wav"
    bad.write_text("this is not a wav file")
    with pytest.raises(silence.SilenceError):
        silence.measure(bad)
