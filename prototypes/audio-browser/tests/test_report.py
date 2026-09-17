from __future__ import annotations

import sqlite3
from pathlib import Path

from audio_browser.config import Root
from audio_browser.report import (
    collect_stats,
    duplicate_groups,
    duplicate_summary,
    is_bundle_path,
    redundancy,
)
from audio_browser.scan import scan_roots
from conftest import write_wav


def quiet(_: str) -> None:
    return None


def run(conn: sqlite3.Connection, roots) -> None:
    scan_roots(conn, roots, probe=False, log=quiet, workers=2)


def test_duplicate_groups_and_waste(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    groups = duplicate_groups(conn)
    assert len(groups) == 2  # the kick blob and the hat blob
    kick = max(groups, key=lambda g: g.copies)
    assert kick.copies == 4  # two names, two trees
    assert kick.wasted_bytes == 3 * kick.size_bytes

    every = duplicate_summary(conn, within_root=False)
    assert every.groups == 2
    assert every.extra_copies == 4  # 3 extra kicks + 1 extra hat
    assert every.wasted_bytes == sum(g.wasted_bytes for g in groups)

    # The default ignores copies explained by one root mirroring another, so
    # only the kick pair counts: the hat exists once per tree and is not waste.
    real = duplicate_summary(conn)
    assert real.groups == 1
    assert real.extra_copies == 1
    assert real.wasted_bytes == kick.size_bytes


def test_duplicate_groups_limit(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    assert len(duplicate_groups(conn, limit=1)) == 1


def test_redundancy_of_a_full_copy(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    report = redundancy(conn, "copy", "source")
    assert report.subject_blobs == 2
    assert report.twinned_blobs == 2
    assert report.untwinned_blobs == 0
    assert report.untwinned_bytes == 0
    assert report.fully_redundant is True


def test_redundancy_spots_a_file_only_in_the_copy(
    conn: sqlite3.Connection, two_roots
) -> None:
    extra = two_roots[1].path / "only-here.wav"
    write_wav(extra, freq=1234)
    run(conn, two_roots)
    report = redundancy(conn, "copy", "source")
    assert report.subject_blobs == 3
    assert report.twinned_blobs == 2
    assert report.untwinned_blobs == 1
    assert report.fully_redundant is False
    assert report.untwinned_examples[0][1] == str(extra.resolve())


def test_redundancy_ignores_renames(conn: sqlite3.Connection, two_roots) -> None:
    """A renamed copy is still the same bytes, so it is still redundant."""
    (two_roots[1].path / "hats" / "hat.wav").rename(
        two_roots[1].path / "hats" / "renamed.wav"
    )
    run(conn, two_roots)
    assert redundancy(conn, "copy", "source").untwinned_blobs == 0


def test_redundancy_on_an_unknown_root_is_empty(
    conn: sqlite3.Connection, two_roots
) -> None:
    run(conn, two_roots)
    report = redundancy(conn, "nowhere", "source")
    assert report.subject_blobs == 0
    assert report.fully_redundant is False


def test_stats_counts_blobs_once_and_paths_many(
    conn: sqlite3.Connection, two_roots
) -> None:
    run(conn, two_roots)
    stats = collect_stats(conn)
    assert stats.aliases == 6
    assert stats.blobs == 2
    assert stats.physical_bytes > stats.logical_bytes
    assert {r.root for r in stats.roots} == {"source", "copy"}
    assert stats.extensions == ((".wav", 6),)
    assert stats.favorites == 0


def test_stats_on_an_empty_index(conn: sqlite3.Connection) -> None:
    stats = collect_stats(conn)
    assert stats.aliases == 0
    assert stats.blobs == 0
    assert stats.logical_bytes == 0
    assert stats.total_duration_s == 0


def test_stats_sees_one_root_only(conn: sqlite3.Connection, tmp_path: Path) -> None:
    write_wav(tmp_path / "solo" / "a.wav")
    run(conn, [Root(name="solo", path=(tmp_path / "solo").resolve())])
    stats = collect_stats(conn)
    assert len(stats.roots) == 1
    assert stats.roots[0].aliases == 1


# ------------------------------------------------- project bundles are locked


def test_is_bundle_path_looks_at_directories() -> None:
    assert is_bundle_path("/x/Song.logicx/Media/Audio Files/take.wav")
    assert is_bundle_path("/x/SONG.LOGICX/Media/take.wav")  # macOS case
    # A name that merely contains the word is an ordinary file.
    assert not is_bundle_path("/x/samples/mix.logicx.wav")
    assert not is_bundle_path("/x/samples/take.wav")


def test_duplicate_summary_can_drop_bundle_copies(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Bytes inside a project bundle are redundancy that cannot be reclaimed.

    The project reads its media from that exact path. Counting those copies as
    waste overstates what a cleanup could free, which is how a cleanup ends up
    breaking a project.
    """
    root = tmp_path / "compost"
    write_wav(root / "samples" / "loose.wav", freq=300)
    write_wav(root / "packs" / "loose-copy.wav", freq=300)
    write_wav(root / "a.logicx" / "Media" / "take.wav", freq=700)
    write_wav(root / "b.logicx" / "Media" / "take.wav", freq=700)
    run(conn, [Root("compost", root.resolve())])

    everything = duplicate_summary(conn)
    assert everything.groups == 2

    reclaimable = duplicate_summary(conn, exclude_bundles=True)
    assert reclaimable.groups == 1
    assert reclaimable.extra_copies == 1
    assert reclaimable.wasted_bytes < everything.wasted_bytes
