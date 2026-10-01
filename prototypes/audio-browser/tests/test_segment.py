"""Stage 3's effectful edges: decoding, the run loop, and the comparison.

No model is loaded here. The run loop is exercised with a fake classifier that
returns whatever the test tells it to, which is the only way to test the parts
that matter — restarting, failure handling, replacement — without an hour of
GPU time per assertion.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from audio_browser.db import open_db
from audio_browser.segment.audio import DecodeError, decode_all, decode_blocks
from audio_browser.segment.audioset import MUSIC, OTHER, SPEECH
from audio_browser.segment.compare import (
    all_pairs,
    compare_pair,
    folder_proxy,
    method_summary,
)
from audio_browser.segment.runner import (
    METHODS,
    RunSummary,
    build_segmenter,
    peak_rss_bytes,
    run_method,
)
from audio_browser.segment.spans import Span
from audio_browser.segment.store import (
    STATUS_FAILED,
    STATUS_OK,
    RunRecord,
    candidates,
    done_hashes,
    load_spans,
    methods_present,
    record_run,
    replace_spans,
    run_totals,
)

from conftest import needs_ffmpeg, write_wav


# ------------------------------------------------------------------ decoding


@needs_ffmpeg
def test_a_file_decodes_to_the_number_of_samples_its_length_implies(
    tmp_path: Path,
) -> None:
    write_wav(tmp_path / "a.wav", seconds=1.0, sample_rate=8000)
    samples = decode_all(tmp_path / "a.wav", sample_rate=16_000)
    assert 15_500 <= len(samples) <= 16_500


@needs_ffmpeg
def test_blocks_tile_the_file_when_nothing_overlaps(tmp_path: Path) -> None:
    write_wav(tmp_path / "a.wav", seconds=2.0, sample_rate=8000)
    blocks = list(
        decode_blocks(tmp_path / "a.wav", sample_rate=16_000, block_samples=16_000)
    )
    assert [start for start, _ in blocks] == [0, 16_000]
    assert sum(len(b) for _, b in blocks) >= 31_000


@needs_ffmpeg
def test_overlapping_blocks_advance_by_the_hop_not_the_window(
    tmp_path: Path,
) -> None:
    write_wav(tmp_path / "a.wav", seconds=3.0, sample_rate=8000)
    blocks = list(
        decode_blocks(
            tmp_path / "a.wav",
            sample_rate=16_000,
            block_samples=16_000,
            overlap_samples=8_000,
        )
    )
    starts = [start for start, _ in blocks]
    assert starts[:3] == [0, 8_000, 16_000]


@needs_ffmpeg
def test_overlapping_blocks_carry_the_same_samples_across_the_seam(
    tmp_path: Path,
) -> None:
    """The tail of one block must be the head of the next, sample for sample."""
    import numpy as np

    write_wav(tmp_path / "a.wav", seconds=2.0, sample_rate=16_000, freq=200.0)
    blocks = list(
        decode_blocks(
            tmp_path / "a.wav",
            sample_rate=16_000,
            block_samples=8_000,
            overlap_samples=2_000,
        )
    )
    first, second = blocks[0][1], blocks[1][1]
    assert np.allclose(first[-2_000:], second[:2_000])


@needs_ffmpeg
def test_a_sound_shorter_than_one_block_still_yields_it(tmp_path: Path) -> None:
    write_wav(tmp_path / "tiny.wav", seconds=0.05, sample_rate=8000)
    blocks = list(
        decode_blocks(
            tmp_path / "tiny.wav", sample_rate=16_000, block_samples=16_000
        )
    )
    assert len(blocks) == 1
    assert 0 < len(blocks[0][1]) < 16_000


@needs_ffmpeg
def test_a_file_that_is_not_audio_raises(tmp_path: Path) -> None:
    (tmp_path / "not-audio.wav").write_bytes(b"this is not a wav file")
    with pytest.raises(DecodeError):
        decode_all(tmp_path / "not-audio.wav", sample_rate=16_000)


def test_a_block_of_zero_samples_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="block_samples"):
        list(decode_blocks(tmp_path / "x.wav", sample_rate=16_000, block_samples=0))


def test_an_overlap_as_wide_as_the_block_is_rejected(tmp_path: Path) -> None:
    """It would mean never advancing, so it is a mistake rather than a slow run."""
    with pytest.raises(ValueError, match="overlap_samples"):
        list(
            decode_blocks(
                tmp_path / "x.wav",
                sample_rate=16_000,
                block_samples=100,
                overlap_samples=100,
            )
        )


# --------------------------------------------------------------------- store


@pytest.fixture
def indexed(tmp_path: Path) -> sqlite3.Connection:
    """Three blobs with aliases, one of them discarded."""
    conn = open_db(tmp_path / "i.db")
    for index, digest in enumerate(("a" * 64, "b" * 64, "c" * 64)):
        conn.execute(
            "INSERT INTO blob (hash, size_bytes, duration_s) VALUES (?, ?, ?)",
            (digest, 1000, float(10 * (index + 1))),
        )
        conn.execute(
            "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
            "VALUES (?, ?, 'r', ?, '.wav', 0, '2026-01-01T00:00:00+00:00')",
            (digest, f"/tmp/{digest[:1]}.wav", f"{digest[:1]}.wav"),
        )
    conn.execute(
        "INSERT INTO soft_delete (hash, deleted_at) VALUES (?, ?)",
        ("c" * 64, "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    yield conn
    conn.close()


def test_discarded_sounds_are_not_candidates(indexed: sqlite3.Connection) -> None:
    """The user rejected them, so classifying them would be hours wasted."""
    assert [c.hash for c in candidates(indexed)] == ["b" * 64, "a" * 64]


def test_discarded_sounds_can_be_asked_for_explicitly(
    indexed: sqlite3.Connection,
) -> None:
    assert len(candidates(indexed, include_discarded=True)) == 3


def test_candidates_come_longest_first(indexed: sqlite3.Connection) -> None:
    """The slowest files first, so a run that is too slow says so early."""
    durations = [c.duration_s for c in candidates(indexed, include_discarded=True)]
    assert durations == sorted(durations, reverse=True)


def test_a_duration_ceiling_leaves_the_long_ones_out(
    indexed: sqlite3.Connection,
) -> None:
    assert [c.hash for c in candidates(indexed, max_duration_s=15.0)] == ["a" * 64]


def test_a_blob_with_no_alias_is_not_a_candidate(
    indexed: sqlite3.Connection,
) -> None:
    indexed.execute("DELETE FROM alias WHERE hash = ?", ("a" * 64,))
    assert [c.hash for c in candidates(indexed)] == ["b" * 64]


def test_writing_spans_twice_replaces_rather_than_doubles(
    indexed: sqlite3.Connection,
) -> None:
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 5.0, MUSIC, 0.9)])
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 9.0, SPEECH, 0.8)])
    stored = load_spans(indexed, "a" * 64, "yamnet")
    assert [(s.start_s, s.end_s, s.label) for s in stored] == [(0.0, 9.0, SPEECH)]


def test_replacing_one_method_leaves_the_others_alone(
    indexed: sqlite3.Connection,
) -> None:
    """Keeping every method's spans side by side is the point of the table."""
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 5.0, MUSIC, 0.9)])
    replace_spans(indexed, "a" * 64, "clap", [Span(0.0, 5.0, SPEECH, 0.7)])
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 5.0, OTHER, 0.5)])
    assert load_spans(indexed, "a" * 64, "clap")[0].label == SPEECH
    assert load_spans(indexed, "a" * 64, "yamnet")[0].label == OTHER


def test_methods_present_lists_what_has_actually_run(
    indexed: sqlite3.Connection,
) -> None:
    assert methods_present(indexed) == []
    replace_spans(indexed, "a" * 64, "clap", [Span(0.0, 1.0, MUSIC, 0.5)])
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 1.0, MUSIC, 0.5)])
    assert methods_present(indexed) == ["clap", "yamnet"]


def test_a_recorded_failure_counts_as_done(indexed: sqlite3.Connection) -> None:
    """A file ffmpeg cannot open will not open on the next pass either."""
    record_run(
        indexed,
        RunRecord("a" * 64, "yamnet", STATUS_FAILED, 0, 10.0, 0.1, None, "boom"),
    )
    assert done_hashes(indexed, "yamnet") == {"a" * 64}
    assert done_hashes(indexed, "clap") == set()


def test_run_totals_add_up_across_files(indexed: sqlite3.Connection) -> None:
    record_run(
        indexed, RunRecord("a" * 64, "yamnet", STATUS_OK, 3, 10.0, 1.0, 1 << 20, None)
    )
    record_run(
        indexed, RunRecord("b" * 64, "yamnet", STATUS_OK, 2, 20.0, 2.0, 2 << 20, None)
    )
    totals = run_totals(indexed, "yamnet")
    assert totals["files"] == 2
    assert totals["audio_s"] == 30.0
    assert totals["elapsed_s"] == 3.0
    assert totals["peak_rss_b"] == float(2 << 20)


# ----------------------------------------------------------------- run loop


class FakeSegmenter:
    """A classifier that returns canned spans, or raises when told to."""

    def __init__(self, method: str = "fake", *, explode_on: str | None = None) -> None:
        self.method = method
        self.seen: list[Path] = []
        self._explode_on = explode_on

    def describe(self) -> str:
        return f"fake segmenter ({self.method})"

    def segment(self, path: Path, duration_s: float | None = None) -> list[Span]:
        self.seen.append(path)
        if self._explode_on and self._explode_on in str(path):
            raise RuntimeError("cannot read this one")
        end = duration_s if duration_s is not None else 1.0
        return [Span(0.0, end / 2, SPEECH, 0.9), Span(end / 2, end, MUSIC, 0.8)]


def test_a_run_writes_spans_for_every_undiscarded_sound(
    indexed: sqlite3.Connection,
) -> None:
    summary = run_method(indexed, FakeSegmenter())
    assert summary.succeeded == 2
    assert summary.spans_written == 4
    assert load_spans(indexed, "c" * 64, "fake") == []


def test_a_second_run_skips_what_the_first_finished(
    indexed: sqlite3.Connection,
) -> None:
    run_method(indexed, FakeSegmenter())
    again = FakeSegmenter()
    summary = run_method(indexed, again)
    assert summary.attempted == 0
    assert summary.skipped == 2
    assert again.seen == []


def test_force_makes_the_second_run_do_the_work_again(
    indexed: sqlite3.Connection,
) -> None:
    run_method(indexed, FakeSegmenter())
    summary = run_method(indexed, FakeSegmenter(), force=True)
    assert summary.attempted == 2


def test_one_unreadable_file_does_not_end_the_run(
    indexed: sqlite3.Connection,
) -> None:
    summary = run_method(indexed, FakeSegmenter(explode_on="/tmp/a.wav"))
    assert summary.failed == 1
    assert summary.succeeded == 1
    assert summary.errors[0][1].startswith("RuntimeError")


def test_a_failure_is_recorded_so_a_restart_does_not_retry_it(
    indexed: sqlite3.Connection,
) -> None:
    run_method(indexed, FakeSegmenter(explode_on="/tmp/a.wav"))
    assert done_hashes(indexed, "fake") == {"a" * 64, "b" * 64}


def test_a_limit_stops_the_run_early(indexed: sqlite3.Connection) -> None:
    summary = run_method(indexed, FakeSegmenter(), limit=1)
    assert summary.attempted == 1


def test_the_run_logs_progress_when_asked(indexed: sqlite3.Connection) -> None:
    lines: list[str] = []
    run_method(indexed, FakeSegmenter(), log=lines.append)
    assert any("fake segmenter" in line for line in lines)
    assert any("[1/2]" in line for line in lines)


def test_the_summary_reports_speed_per_audio_minute() -> None:
    summary = RunSummary(method="m", audio_s=120.0, elapsed_s=60.0)
    assert summary.seconds_per_audio_minute == pytest.approx(30.0)
    assert summary.realtime_factor == pytest.approx(2.0)


def test_speed_of_an_empty_run_is_zero_rather_than_an_error() -> None:
    summary = RunSummary(method="m")
    assert summary.seconds_per_audio_minute == 0.0
    assert summary.realtime_factor == 0.0


def test_peak_memory_is_a_positive_number_of_bytes() -> None:
    assert peak_rss_bytes() > 1 << 20


def test_an_unknown_method_is_refused_by_name(indexed: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="unknown method"):
        build_segmenter("telepathy")


def test_the_three_methods_are_the_ones_the_cli_offers() -> None:
    from audio_browser.cli import SEGMENT_METHODS

    assert tuple(METHODS) == SEGMENT_METHODS


# ------------------------------------------------------------- comparison


def test_two_methods_that_said_the_same_thing_agree_completely(
    indexed: sqlite3.Connection,
) -> None:
    run_method(indexed, FakeSegmenter("yamnet"))
    run_method(indexed, FakeSegmenter("clap"))
    pair = compare_pair(indexed, "yamnet", "clap")
    assert pair.files == 2
    assert pair.fraction == pytest.approx(1.0)


def test_disagreement_is_counted_in_seconds_and_attributed(
    indexed: sqlite3.Connection,
) -> None:
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 10.0, MUSIC, 0.9)])
    replace_spans(indexed, "a" * 64, "clap", [Span(0.0, 10.0, SPEECH, 0.9)])
    pair = compare_pair(indexed, "yamnet", "clap")
    assert pair.agreed_s == 0.0
    assert pair.covered_s == pytest.approx(10.0)
    assert pair.confusion[(MUSIC, SPEECH)] == pytest.approx(10.0)


def test_the_worst_file_is_the_one_with_the_most_seconds_in_dispute(
    indexed: sqlite3.Connection,
) -> None:
    """Not the lowest percentage: a long recording matters more than a sample."""
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 2.0, MUSIC, 0.9)])
    replace_spans(indexed, "a" * 64, "clap", [Span(0.0, 2.0, SPEECH, 0.9)])
    replace_spans(indexed, "b" * 64, "yamnet", [Span(0.0, 100.0, MUSIC, 0.9)])
    replace_spans(
        indexed,
        "b" * 64,
        "clap",
        [Span(0.0, 50.0, MUSIC, 0.9), Span(50.0, 100.0, SPEECH, 0.9)],
    )
    pair = compare_pair(indexed, "yamnet", "clap")
    assert pair.worst[0].hash == "b" * 64


def test_a_file_only_one_method_ran_on_is_left_out_of_the_pair(
    indexed: sqlite3.Connection,
) -> None:
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 5.0, MUSIC, 0.9)])
    replace_spans(indexed, "b" * 64, "clap", [Span(0.0, 5.0, MUSIC, 0.9)])
    assert compare_pair(indexed, "yamnet", "clap").files == 0


def test_every_unordered_pair_is_compared(indexed: sqlite3.Connection) -> None:
    for method in ("yamnet", "vad", "clap"):
        replace_spans(indexed, "a" * 64, method, [Span(0.0, 5.0, MUSIC, 0.9)])
    pairs = all_pairs(indexed, ["yamnet", "vad", "clap"])
    assert [(p.left, p.right) for p in pairs] == [
        ("yamnet", "vad"),
        ("yamnet", "clap"),
        ("vad", "clap"),
    ]


def test_a_method_summary_counts_spans_and_seconds_per_label(
    indexed: sqlite3.Connection,
) -> None:
    replace_spans(
        indexed,
        "a" * 64,
        "yamnet",
        [Span(0.0, 3.0, SPEECH, 0.9), Span(3.0, 10.0, MUSIC, 0.9)],
    )
    summary = method_summary(indexed, "yamnet")
    assert summary.files == 1
    assert summary.spans == 2
    assert summary.per_label_s[SPEECH] == pytest.approx(3.0)
    assert summary.per_label_s[MUSIC] == pytest.approx(7.0)
    assert summary.dominant[MUSIC] == 1


def test_a_method_that_never_ran_summarises_to_zero(
    indexed: sqlite3.Connection,
) -> None:
    summary = method_summary(indexed, "nothing")
    assert summary.files == 0
    assert summary.spans_per_file == 0.0


# ------------------------------------------------------------- folder proxy


def test_the_folder_proxy_scores_a_method_against_where_a_sound_lives(
    indexed: sqlite3.Connection,
) -> None:
    """The folders are the only labels here that no model produced."""
    indexed.execute(
        "UPDATE alias SET path = ? WHERE hash = ?",
        ("/x/sounds - spoken/a.wav", "a" * 64),
    )
    replace_spans(
        indexed,
        "a" * 64,
        "yamnet",
        [Span(0.0, 8.0, SPEECH, 0.9), Span(8.0, 10.0, MUSIC, 0.9)],
    )
    scores = {s.folder: s for s in folder_proxy(indexed, "yamnet")}
    assert scores["sounds - spoken"].fraction == pytest.approx(0.8)
    assert scores["sounds - spoken"].files == 1
    assert scores["sounds - foley"].fraction == 0.0


def test_a_folder_with_no_classified_sounds_scores_zero_without_dividing_by_it(
    indexed: sqlite3.Connection,
) -> None:
    scores = folder_proxy(indexed, "yamnet")
    assert all(s.fraction == 0.0 and s.total_s == 0.0 for s in scores)


def test_the_proxy_folders_can_be_replaced(indexed: sqlite3.Connection) -> None:
    indexed.execute(
        "UPDATE alias SET path = ? WHERE hash = ?", ("/x/drums/a.wav", "a" * 64)
    )
    replace_spans(indexed, "a" * 64, "yamnet", [Span(0.0, 5.0, MUSIC, 0.9)])
    scores = folder_proxy(indexed, "yamnet", {"drums": MUSIC})
    assert len(scores) == 1
    assert scores[0].fraction == pytest.approx(1.0)



def test_a_slow_file_is_committed_before_the_next_one_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Half an hour of work must not sit uncommitted behind nine short files.

    The check runs from a second connection opened part-way through, because
    "committed" means exactly "another reader can see it".
    """
    from audio_browser.segment import runner as runner_module

    db = tmp_path / "slow.db"
    conn = open_db(db)
    for digest in ("d" * 64, "e" * 64):
        conn.execute(
            "INSERT INTO blob (hash, size_bytes, duration_s) VALUES (?, 1, 60.0)",
            (digest,),
        )
        conn.execute(
            "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
            "VALUES (?, ?, 'r', ?, '.wav', 0, '2026-01-01T00:00:00+00:00')",
            (digest, f"/tmp/{digest[:1]}.wav", f"{digest[:1]}.wav"),
        )
    conn.commit()

    # Every file counts as slow, and the batch never fires on its own.
    monkeypatch.setattr(runner_module, "COMMIT_AFTER_S", 0.0)
    monkeypatch.setattr(runner_module, "COMMIT_EVERY", 1000)

    seen_by_a_second_reader: list[set[str]] = []

    class Watching(FakeSegmenter):
        def segment(
            self, path: Path, duration_s: float | None = None
        ) -> list[Span]:
            other = open_db(db)
            try:
                seen_by_a_second_reader.append(done_hashes(other, self.method))
            finally:
                other.close()
            return super().segment(path, duration_s)

    try:
        run_method(conn, Watching())
    finally:
        conn.close()

    # Nothing before the first file, the first file before the second.
    assert seen_by_a_second_reader[0] == set()
    assert len(seen_by_a_second_reader[1]) == 1


def test_a_batch_of_quick_files_is_not_committed_one_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Committing per file would fsync once per sound over 942 of them."""
    from audio_browser.segment import runner as runner_module

    db = tmp_path / "quick.db"
    conn = open_db(db)
    conn.execute(
        "INSERT INTO blob (hash, size_bytes, duration_s) VALUES (?, 1, 60.0)",
        ("d" * 64,),
    )
    conn.execute(
        "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
        "VALUES (?, '/tmp/d.wav', 'r', 'd.wav', '.wav', 0, '2026-01-01T00:00:00+00:00')",
        ("d" * 64,),
    )
    conn.commit()

    monkeypatch.setattr(runner_module, "COMMIT_AFTER_S", 1e9)
    monkeypatch.setattr(runner_module, "COMMIT_EVERY", 1000)

    seen_mid_run: list[set[str]] = []

    class Watching(FakeSegmenter):
        def segment(
            self, path: Path, duration_s: float | None = None
        ) -> list[Span]:
            other = open_db(db)
            try:
                seen_mid_run.append(done_hashes(other, self.method))
            finally:
                other.close()
            return super().segment(path, duration_s)

    run_method(conn, Watching())
    try:
        # Nothing was visible while the run was going; the final commit does it.
        assert seen_mid_run == [set()]
        assert done_hashes(conn, "fake") == {"d" * 64}
    finally:
        conn.close()
