from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from audio_browser.config import Root
from audio_browser.scan import scan_roots, walk_audio_files
from conftest import needs_ffprobe, write_wav


def quiet(_: str) -> None:
    return None


def run(conn: sqlite3.Connection, roots, **kwargs):
    kwargs.setdefault("probe", False)
    kwargs.setdefault("log", quiet)
    kwargs.setdefault("workers", 2)
    return scan_roots(conn, roots, **kwargs)


def test_walk_only_yields_allowlisted_extensions(tmp_path: Path) -> None:
    write_wav(tmp_path / "a.wav")
    write_wav(tmp_path / "nested" / "b.WAV")
    (tmp_path / "c.rpp").write_text("x")
    (tmp_path / "d.mid").write_text("x")
    (tmp_path / "e.reapeaks").write_text("x")
    found = {p.name for p in walk_audio_files(tmp_path, on_error=quiet)}
    assert found == {"a.wav", "b.WAV"}


def test_walk_skips_appledouble_sidecars(tmp_path: Path) -> None:
    write_wav(tmp_path / "a.wav")
    (tmp_path / "._a.wav").write_bytes(b"\x00\x05\x16\x07resource fork")
    found = {p.name for p in walk_audio_files(tmp_path, on_error=quiet)}
    assert found == {"a.wav"}


def test_walk_does_not_follow_directory_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real"
    write_wav(real / "a.wav")
    (tmp_path / "loop").symlink_to(real, target_is_directory=True)
    found = list(walk_audio_files(tmp_path, on_error=quiet))
    assert len(found) == 1


def test_identical_files_share_one_blob(conn: sqlite3.Connection, two_roots) -> None:
    stats = run(conn, two_roots)
    # 3 files per tree, two trees; kick.wav and kick-again.wav share bytes.
    assert stats.files_found == 6
    assert stats.files_hashed == 6
    assert conn.execute("SELECT COUNT(*) FROM alias").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM blob").fetchone()[0] == 2


def test_non_audio_files_are_ignored(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    exts = {
        row["ext"] for row in conn.execute("SELECT DISTINCT ext FROM alias")
    }
    assert exts == {".wav"}


def test_paths_are_stored_resolved(conn: sqlite3.Connection, tmp_path: Path) -> None:
    real = tmp_path / "real"
    write_wav(real / "a.wav")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    run(conn, [Root(name="linked", path=link.resolve())])
    stored = conn.execute("SELECT path FROM alias").fetchone()["path"]
    assert stored == str((real / "a.wav").resolve())


def test_rescan_is_a_no_op(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    again = run(conn, two_roots)
    assert again.files_found == 6
    assert again.files_unchanged == 6
    assert again.files_hashed == 0
    assert again.aliases_new == 0
    assert again.aliases_pruned == 0
    assert again.blobs_pruned == 0


def test_changed_file_is_rehashed(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    source = two_roots[0]
    target = source.path / "hats" / "hat.wav"
    write_wav(target, freq=3000, seconds=0.2)
    os.utime(target, (0, 0))  # force a different mtime
    again = run(conn, two_roots)
    assert again.files_hashed == 1
    assert again.blobs_new == 1


def test_deleted_file_is_pruned(conn: sqlite3.Connection, two_roots) -> None:
    run(conn, two_roots)
    (two_roots[0].path / "hats" / "hat.wav").unlink()
    again = run(conn, two_roots)
    assert again.aliases_pruned == 1
    assert conn.execute("SELECT COUNT(*) FROM alias").fetchone()[0] == 5
    # The copy still holds those bytes, so the blob survives.
    assert conn.execute("SELECT COUNT(*) FROM blob").fetchone()[0] == 2


def test_favorited_blob_survives_losing_every_alias(
    conn: sqlite3.Connection, two_roots
) -> None:
    run(conn, two_roots)
    hat_hash = conn.execute(
        "SELECT hash FROM alias WHERE filename = 'hat.wav'"
    ).fetchone()["hash"]
    conn.execute(
        "INSERT INTO favorite (hash, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')",
        (hat_hash,),
    )
    for root in two_roots:
        (root.path / "hats" / "hat.wav").unlink()
    again = run(conn, two_roots)
    assert again.aliases_pruned == 2
    assert again.blobs_pruned == 0  # favorited, so kept
    assert conn.execute(
        "SELECT COUNT(*) FROM blob WHERE hash = ?", (hat_hash,)
    ).fetchone()[0] == 1


def test_unmarked_orphan_blob_is_dropped(
    conn: sqlite3.Connection, two_roots
) -> None:
    run(conn, two_roots)
    for root in two_roots:
        (root.path / "hats" / "hat.wav").unlink()
    again = run(conn, two_roots)
    assert again.aliases_pruned == 2
    assert again.blobs_pruned == 1
    assert conn.execute("SELECT COUNT(*) FROM blob").fetchone()[0] == 1


def test_pruning_is_skipped_for_an_empty_root(
    conn: sqlite3.Connection, two_roots, tmp_path: Path
) -> None:
    """An unmounted volume looks empty. It must not wipe the index."""
    run(conn, two_roots)
    empty = tmp_path / "unmounted"
    empty.mkdir()
    run(conn, [Root(name="copy", path=empty)])
    assert conn.execute("SELECT COUNT(*) FROM alias").fetchone()[0] == 6


def test_missing_root_is_skipped(conn: sqlite3.Connection, tmp_path: Path) -> None:
    stats = run(conn, [Root(name="gone", path=tmp_path / "does-not-exist")])
    assert stats.roots_skipped == ["gone"]
    assert stats.files_found == 0


def test_unreadable_file_does_not_stop_the_scan(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    write_wav(tmp_path / "good.wav")
    bad = tmp_path / "bad.wav"
    write_wav(bad)
    bad.chmod(0o000)
    try:
        stats = run(conn, [Root(name="r", path=tmp_path)])
        assert stats.files_hashed == 1
        assert stats.read_errors == 1
    finally:
        bad.chmod(0o600)


def test_scan_does_not_modify_the_root(conn: sqlite3.Connection, two_roots) -> None:
    source = two_roots[0]
    before = {
        str(p): (p.stat().st_size, p.stat().st_mtime)
        for p in source.path.rglob("*")
        if p.is_file()
    }
    run(conn, two_roots)
    after = {
        str(p): (p.stat().st_size, p.stat().st_mtime)
        for p in source.path.rglob("*")
        if p.is_file()
    }
    assert before == after


@needs_ffprobe
def test_probe_fills_metadata(conn: sqlite3.Connection, two_roots) -> None:
    stats = run(conn, two_roots, probe=True)
    assert stats.probed == 2  # one probe per blob, not per alias
    assert stats.probe_errors == 0
    row = conn.execute(
        "SELECT duration_s, sample_rate, channels, codec FROM blob LIMIT 1"
    ).fetchone()
    assert row["sample_rate"] == 8000
    assert row["channels"] == 1
    assert row["codec"] == "pcm_s16le"
    assert 0.05 < row["duration_s"] < 0.5
    # A second scan probes nothing new.
    assert run(conn, two_roots, probe=True).probed == 0
