"""Tests for the one-time deduplication tool.

Every test builds its own fixture tree under ``tmp_path``. Nothing here reads
or writes the real collection.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from audio_browser.config import Root
from audio_browser.db import now_iso
from audio_browser.dedupe import (
    BUNDLE_REASON,
    PROJECT_DIR_REASON,
    Copy,
    DedupePlan,
    ProjectDirs,
    SkippedSound,
    SoundPlan,
    UnsafeDeletion,
    apply_plan,
    deleted_sightings,
    ensure_under_root,
    example_lines,
    is_under_root,
    no_project_dirs,
    plan_root,
    plan_sound,
    protection_for,
    survivor_key,
    validate_plan,
    write_plan,
)

from conftest import write_wav

HASH_A = "a" * 64
HASH_B = "b" * 64


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def add_blob(conn: sqlite3.Connection, file_hash: str, size: int = 1000) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO blob (hash, size_bytes) VALUES (?, ?)",
        (file_hash, size),
    )


def add_alias(
    conn: sqlite3.Connection, file_hash: str, path: Path | str, root: str
) -> None:
    text = str(path)
    conn.execute(
        "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            file_hash,
            text,
            root,
            os.path.basename(text),
            os.path.splitext(text)[1].lower(),
            0.0,
            now_iso(),
        ),
    )


def touch(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


# --------------------------------------------------------------------------
# root containment
# --------------------------------------------------------------------------


def test_is_under_root_accepts_a_child() -> None:
    assert is_under_root("/lib/a/b.wav", "/lib")


def test_is_under_root_rejects_the_root_itself() -> None:
    assert not is_under_root("/lib", "/lib")


def test_is_under_root_rejects_a_sibling_with_a_shared_prefix() -> None:
    # "/library" starts with "/lib" as a string but is not inside it.
    assert not is_under_root("/library/a.wav", "/lib")


def test_is_under_root_rejects_the_other_root() -> None:
    assert not is_under_root(
        "/Users/x/_tmsmsm/daw-library/compost/a.wav", "/Users/x/sandbox/audio-library"
    )


def test_is_under_root_tolerates_a_trailing_separator() -> None:
    assert is_under_root("/lib/a.wav", "/lib/")


def test_ensure_under_root_raises_for_an_outside_path() -> None:
    with pytest.raises(UnsafeDeletion, match="not under the requested root"):
        ensure_under_root("/elsewhere/a.wav", "/lib")


# --------------------------------------------------------------------------
# protections
# --------------------------------------------------------------------------


def test_bundle_path_is_protected() -> None:
    assert (
        protection_for("/lib/Song.logicx/Media/take.wav", dir_has_project=no_project_dirs)
        == BUNDLE_REASON
    )


def test_bundle_check_is_case_insensitive() -> None:
    assert (
        protection_for("/lib/Song.LogicX/Media/take.wav", dir_has_project=no_project_dirs)
        == BUNDLE_REASON
    )


def test_a_file_merely_named_logicx_is_not_a_bundle() -> None:
    assert (
        protection_for("/lib/mix.logicx.wav", dir_has_project=no_project_dirs) is None
    )


def test_path_beside_a_project_file_is_protected() -> None:
    assert (
        protection_for("/lib/session/kick.wav", dir_has_project=lambda d: True)
        == PROJECT_DIR_REASON
    )


def test_plain_path_is_not_protected() -> None:
    assert protection_for("/lib/kick.wav", dir_has_project=no_project_dirs) is None


@pytest.mark.parametrize("project", ["song.rpp", "song.rpp-bak", "song.als"])
def test_project_dirs_finds_every_project_extension(
    tmp_path: Path, project: str
) -> None:
    touch(tmp_path / "session" / project)
    touch(tmp_path / "session" / "kick.wav")
    assert ProjectDirs()(str(tmp_path / "session"))


def test_project_dirs_is_case_insensitive(tmp_path: Path) -> None:
    touch(tmp_path / "session" / "Song.RPP")
    assert ProjectDirs()(str(tmp_path / "session"))


def test_project_dirs_says_no_for_a_plain_directory(tmp_path: Path) -> None:
    touch(tmp_path / "samples" / "kick.wav")
    assert not ProjectDirs()(str(tmp_path / "samples"))


def test_project_dirs_ignores_a_directory_named_like_a_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "samples" / "old.rpp").mkdir(parents=True)
    assert not ProjectDirs()(str(tmp_path / "samples"))


def test_project_dirs_protects_a_directory_it_cannot_read(tmp_path: Path) -> None:
    # Missing evidence must never read as "safe to delete".
    assert ProjectDirs()(str(tmp_path / "does-not-exist"))


def test_project_dirs_caches_its_answer(tmp_path: Path) -> None:
    session = tmp_path / "session"
    touch(session / "kick.wav")
    oracle = ProjectDirs()
    assert not oracle(str(session))
    touch(session / "song.rpp")
    assert not oracle(str(session)), "the cached answer should be reused"


# --------------------------------------------------------------------------
# survivor choice
# --------------------------------------------------------------------------


def test_survivor_key_prefers_fewer_separators() -> None:
    assert survivor_key("/lib/z.wav") < survivor_key("/lib/a/a.wav")


def test_survivor_key_breaks_ties_alphabetically() -> None:
    assert survivor_key("/lib/a.wav") < survivor_key("/lib/b.wav")


def test_plan_sound_keeps_the_shallowest_copy() -> None:
    plan = plan_sound(
        HASH_A,
        100,
        ["/lib/deep/deeper/kick.wav", "/lib/kick.wav", "/lib/deep/kick.wav"],
        dir_has_project=no_project_dirs,
    )
    assert isinstance(plan, SoundPlan)
    assert plan.keep == "/lib/kick.wav"
    assert plan.delete == ("/lib/deep/kick.wav", "/lib/deep/deeper/kick.wav")
    assert plan.freed_bytes == 200


def test_plan_sound_breaks_depth_ties_alphabetically() -> None:
    plan = plan_sound(
        HASH_A, 10, ["/lib/b.wav", "/lib/a.wav"], dir_has_project=no_project_dirs
    )
    assert isinstance(plan, SoundPlan)
    assert plan.keep == "/lib/a.wav"
    assert plan.delete == ("/lib/b.wav",)


def test_plan_sound_ignores_a_sound_with_one_copy() -> None:
    assert plan_sound(HASH_A, 10, ["/lib/a.wav"], dir_has_project=no_project_dirs) is None


def test_plan_sound_deduplicates_repeated_paths() -> None:
    assert (
        plan_sound(
            HASH_A, 10, ["/lib/a.wav", "/lib/a.wav"], dir_has_project=no_project_dirs
        )
        is None
    )


def test_plan_sound_never_selects_a_bundle_path() -> None:
    plan = plan_sound(
        HASH_A,
        10,
        ["/lib/Song.logicx/Media/take.wav", "/lib/take.wav", "/lib/copy/take.wav"],
        dir_has_project=no_project_dirs,
    )
    assert isinstance(plan, SoundPlan)
    assert plan.delete == ("/lib/copy/take.wav",)
    assert plan.keep == "/lib/take.wav"
    assert [c.path for c in plan.protected] == ["/lib/Song.logicx/Media/take.wav"]
    assert plan.protected[0].protection == BUNDLE_REASON


def test_plan_sound_never_selects_a_path_beside_a_project() -> None:
    plan = plan_sound(
        HASH_A,
        10,
        ["/lib/session/kick.wav", "/lib/kick.wav", "/lib/dupes/kick.wav"],
        dir_has_project=lambda d: d == "/lib/session",
    )
    assert isinstance(plan, SoundPlan)
    assert "/lib/session/kick.wav" not in plan.delete
    assert plan.delete == ("/lib/dupes/kick.wav",)


def test_plan_sound_keeps_one_free_copy_even_when_a_protected_copy_exists() -> None:
    """A survivor outside a project folder is kept, not only the project's own."""
    plan = plan_sound(
        HASH_A,
        10,
        ["/lib/session/kick.wav", "/lib/a/kick.wav", "/lib/b/kick.wav"],
        dir_has_project=lambda d: d == "/lib/session",
    )
    assert isinstance(plan, SoundPlan)
    assert plan.keep == "/lib/a/kick.wav"
    assert plan.delete == ("/lib/b/kick.wav",)
    assert set(plan.survivors) == {"/lib/a/kick.wav", "/lib/session/kick.wav"}


def test_plan_sound_skips_a_sound_whose_copies_are_all_protected() -> None:
    outcome = plan_sound(
        HASH_A,
        50,
        ["/lib/One.logicx/Media/a.wav", "/lib/Two.logicx/Media/a.wav"],
        dir_has_project=no_project_dirs,
    )
    assert isinstance(outcome, SkippedSound)
    assert outcome.unreclaimed_bytes == 50
    assert all(not c.deletable for c in outcome.copies)


def test_plan_sound_never_reduces_a_sound_to_zero_copies() -> None:
    """Two copies, one protected: the protected one stays and so does the other."""
    outcome = plan_sound(
        HASH_A,
        10,
        ["/lib/session/kick.wav", "/lib/kick.wav"],
        dir_has_project=lambda d: d == "/lib/session",
    )
    assert outcome is None


def test_every_plan_leaves_at_least_one_copy() -> None:
    plan = plan_sound(
        HASH_A,
        10,
        ["/lib/a.wav", "/lib/b.wav", "/lib/c/d.wav"],
        dir_has_project=no_project_dirs,
    )
    assert isinstance(plan, SoundPlan)
    assert len(plan.survivors) >= 1
    assert set(plan.delete).isdisjoint(plan.survivors)


# --------------------------------------------------------------------------
# planning against the index
# --------------------------------------------------------------------------


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A small tree with the three shapes the rules care about."""
    lib = tmp_path / "audio-library"
    write_wav(lib / "kick.wav", freq=60)
    write_wav(lib / "packs" / "kick.wav", freq=60)
    write_wav(lib / "packs" / "deep" / "kick.wav", freq=60)
    write_wav(lib / "session" / "kick.wav", freq=60)
    (lib / "session" / "song.rpp").write_text("<REAPER_PROJECT>")
    write_wav(lib / "Song.logicx" / "Media" / "kick.wav", freq=60)
    return lib


def index_library(conn: sqlite3.Connection, lib: Path, root: str) -> None:
    add_blob(conn, HASH_A, size=1000)
    for path in sorted(lib.rglob("*.wav")):
        add_alias(conn, HASH_A, path, root)
    conn.commit()


def test_plan_root_applies_every_rule_together(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))

    assert plan.sounds_touched == 1
    sound = plan.sounds[0]
    assert sound.keep == str(library / "kick.wav")
    assert set(sound.delete) == {
        str(library / "packs" / "kick.wav"),
        str(library / "packs" / "deep" / "kick.wav"),
    }
    protected = {c.path: c.protection for c in sound.protected}
    assert protected == {
        str(library / "session" / "kick.wav"): PROJECT_DIR_REASON,
        str(library / "Song.logicx" / "Media" / "kick.wav"): BUNDLE_REASON,
    }
    assert plan.files == 2
    assert plan.bytes_freed == 2000


def test_plan_root_ignores_the_other_root(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A twin in the mirror root never makes a path here redundant."""
    lib = tmp_path / "audio-library"
    other = tmp_path / "compost"
    write_wav(lib / "kick.wav", freq=60)
    write_wav(other / "kick.wav", freq=60)
    add_blob(conn, HASH_A)
    add_alias(conn, HASH_A, lib / "kick.wav", "audio-library")
    add_alias(conn, HASH_A, other / "kick.wav", "compost")
    conn.commit()

    plan = plan_root(conn, Root(name="audio-library", path=lib))
    assert plan.files == 0
    assert plan.sounds == ()


def test_plan_root_refuses_an_alias_that_escapes_its_root(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    lib = tmp_path / "audio-library"
    lib.mkdir()
    add_blob(conn, HASH_A)
    add_alias(conn, HASH_A, lib / "kick.wav", "audio-library")
    # An index row that claims this root but points outside it.
    add_alias(conn, HASH_A, tmp_path / "compost" / "kick.wav", "audio-library")
    conn.commit()

    with pytest.raises(UnsafeDeletion, match="not under the requested root"):
        plan_root(conn, Root(name="audio-library", path=lib))


def test_plan_root_counts_skipped_sounds(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    lib = tmp_path / "audio-library"
    write_wav(lib / "One.logicx" / "Media" / "a.wav")
    write_wav(lib / "Two.logicx" / "Media" / "a.wav")
    add_blob(conn, HASH_A, size=700)
    for path in sorted(lib.rglob("*.wav")):
        add_alias(conn, HASH_A, path, "audio-library")
    conn.commit()

    plan = plan_root(conn, Root(name="audio-library", path=lib))
    assert plan.files == 0
    assert plan.sounds_skipped == 1
    assert plan.skipped_bytes == 700


def test_plan_root_uses_the_real_filesystem_for_project_dirs(
    conn: sqlite3.Connection, library: Path
) -> None:
    """No oracle is injected, so the .rpp beside the file must be found on disk."""
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    assert str(library / "session" / "kick.wav") not in plan.sounds[0].delete


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def test_validate_plan_rejects_a_path_outside_the_root() -> None:
    plan = DedupePlan(
        root="audio-library",
        root_path="/lib",
        sounds=(
            SoundPlan(
                file_hash=HASH_A,
                size_bytes=10,
                keep="/lib/a.wav",
                delete=("/elsewhere/b.wav",),
                protected=(),
            ),
        ),
    )
    with pytest.raises(UnsafeDeletion, match="not under the requested root"):
        validate_plan(plan)


def test_validate_plan_rejects_deleting_the_kept_copy() -> None:
    plan = DedupePlan(
        root="audio-library",
        root_path="/lib",
        sounds=(
            SoundPlan(
                file_hash=HASH_A,
                size_bytes=10,
                keep="/lib/a.wav",
                delete=("/lib/a.wav",),
                protected=(),
            ),
        ),
    )
    with pytest.raises(UnsafeDeletion, match="also the kept copy"):
        validate_plan(plan)


def test_validate_plan_rejects_deleting_a_protected_copy() -> None:
    plan = DedupePlan(
        root="audio-library",
        root_path="/lib",
        sounds=(
            SoundPlan(
                file_hash=HASH_A,
                size_bytes=10,
                keep="/lib/a.wav",
                delete=("/lib/s/b.wav",),
                protected=(Copy(path="/lib/s/b.wav", protection=PROJECT_DIR_REASON),),
            ),
        ),
    )
    with pytest.raises(UnsafeDeletion, match="protected copy"):
        validate_plan(plan)


def test_validate_plan_rejects_a_repeated_deletion() -> None:
    entry = SoundPlan(
        file_hash=HASH_A,
        size_bytes=10,
        keep="/lib/a.wav",
        delete=("/lib/b.wav",),
        protected=(),
    )
    other = SoundPlan(
        file_hash=HASH_B,
        size_bytes=10,
        keep="/lib/c.wav",
        delete=("/lib/b.wav",),
        protected=(),
    )
    with pytest.raises(UnsafeDeletion, match="twice"):
        validate_plan(
            DedupePlan(root="audio-library", root_path="/lib", sounds=(entry, other))
        )


# --------------------------------------------------------------------------
# applying
# --------------------------------------------------------------------------


def test_apply_plan_deletes_and_records(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))

    result = apply_plan(conn, plan)
    assert result.deleted == 2
    assert result.bytes_freed == 2000
    assert result.failed == []

    assert (library / "kick.wav").exists()
    assert (library / "session" / "kick.wav").exists()
    assert (library / "Song.logicx" / "Media" / "kick.wav").exists()
    assert not (library / "packs" / "kick.wav").exists()
    assert not (library / "packs" / "deep" / "kick.wav").exists()

    rows = deleted_sightings(conn, HASH_A)
    assert {r[0] for r in rows} == set(plan.sounds[0].delete)
    assert all(r[1] == "audio-library" for r in rows)
    assert all("kept" in r[3] for r in rows)


def test_apply_plan_drops_the_alias_rows_it_deleted(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    apply_plan(conn, plan)
    remaining = {
        str(r["path"])
        for r in conn.execute("SELECT path FROM alias WHERE hash = ?", (HASH_A,))
    }
    assert remaining == set(plan.sounds[0].survivors)


def test_apply_plan_is_idempotent_on_a_second_run(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    apply_plan(conn, plan)
    again = plan_root(conn, Root(name="audio-library", path=library))
    assert again.files == 0


def test_deletion_rows_survive_a_prune(
    conn: sqlite3.Connection, library: Path
) -> None:
    """The scan's prune clears aliases. The deletion record has to outlast it."""
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    apply_plan(conn, plan)

    conn.execute("DELETE FROM alias")
    conn.execute(
        "DELETE FROM blob WHERE hash NOT IN (SELECT hash FROM alias) "
        "AND hash NOT IN (SELECT hash FROM favorite) "
        "AND hash NOT IN (SELECT hash FROM tag)"
    )
    conn.commit()
    assert len(deleted_sightings(conn, HASH_A)) == 2


def test_apply_plan_refuses_an_outside_path_and_deletes_nothing(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    lib = tmp_path / "audio-library"
    other = tmp_path / "compost"
    inside = write_wav(lib / "a" / "kick.wav")
    outside = write_wav(other / "kick.wav")

    plan = DedupePlan(
        root="audio-library",
        root_path=str(lib),
        sounds=(
            SoundPlan(
                file_hash=HASH_A,
                size_bytes=10,
                keep=str(lib / "kick.wav"),
                delete=(str(inside), str(outside)),
                protected=(),
            ),
        ),
    )
    with pytest.raises(UnsafeDeletion, match="not under the requested root"):
        apply_plan(conn, plan)

    assert inside.exists(), "validation runs first, so nothing is unlinked"
    assert outside.exists()
    assert conn.execute("SELECT COUNT(*) AS n FROM deletion").fetchone()["n"] == 0


def test_apply_plan_refuses_a_path_that_symlinks_out_of_the_root(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    lib = tmp_path / "audio-library"
    other = tmp_path / "compost"
    real = write_wav(other / "kick.wav")
    (lib / "link").mkdir(parents=True)
    escape = lib / "link" / "kick.wav"
    escape.symlink_to(real)

    plan = DedupePlan(
        root="audio-library",
        root_path=str(lib),
        sounds=(
            SoundPlan(
                file_hash=HASH_A,
                size_bytes=10,
                keep=str(lib / "kick.wav"),
                delete=(str(escape),),
                protected=(),
            ),
        ),
    )
    with pytest.raises(UnsafeDeletion):
        apply_plan(conn, plan)
    assert real.exists()


def test_apply_plan_counts_a_file_that_is_already_gone(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    (library / "packs" / "kick.wav").unlink()

    result = apply_plan(conn, plan)
    assert result.deleted == 1
    assert result.already_missing == 1
    # The path is still recorded: the sound is no longer there either way.
    assert len(deleted_sightings(conn, HASH_A)) == 2


def test_apply_plan_reports_a_failed_unlink(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    victim = plan.sounds[0].delete[0]

    def refuse(path: str) -> None:
        if path == victim:
            raise PermissionError("read-only file system")
        os.remove(path)

    result = apply_plan(conn, plan, unlink=refuse)
    assert result.deleted == 1
    assert [p for p, _ in result.failed] == [victim]
    assert Path(victim).exists()
    assert {r[0] for r in deleted_sightings(conn, HASH_A)} == set(
        plan.sounds[0].delete
    ) - {victim}


def test_re_deleting_the_same_path_updates_one_row(
    conn: sqlite3.Connection, library: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    apply_plan(conn, plan)
    # Restore one file and delete it again through the same plan.
    write_wav(Path(plan.sounds[0].delete[0]))
    apply_plan(conn, plan)
    assert conn.execute("SELECT COUNT(*) AS n FROM deletion").fetchone()["n"] == 2


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def test_write_plan_lists_only_deletions_on_uncommented_lines(
    conn: sqlite3.Connection, library: Path, tmp_path: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    out = tmp_path / "plan" / "dedupe-plan.txt"
    assert write_plan(plan, out) == 2

    lines = [
        line
        for line in out.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert set(lines) == set(plan.sounds[0].delete)


def test_write_plan_mentions_every_protected_copy(
    conn: sqlite3.Connection, library: Path, tmp_path: Path
) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    out = tmp_path / "dedupe-plan.txt"
    write_plan(plan, out)
    text = out.read_text()
    for copy in plan.sounds[0].protected:
        assert copy.path in text


def test_example_lines_are_capped(conn: sqlite3.Connection, library: Path) -> None:
    index_library(conn, library, "audio-library")
    plan = plan_root(conn, Root(name="audio-library", path=library))
    assert len(example_lines(plan, 2)) == 2
    assert example_lines(plan, 10)[0].startswith("keep")


def test_example_lines_do_not_let_one_sound_fill_the_sample() -> None:
    """Twenty copies of one sound must not crowd out every other sound."""
    def sound(name: str, copies: int) -> SoundPlan:
        return SoundPlan(
            file_hash=name * 64,
            size_bytes=10,
            keep=f"/lib/{name}.wav",
            delete=tuple(f"/lib/d{i}/{name}.wav" for i in range(copies)),
            protected=(),
        )

    plan = DedupePlan(
        root="r", root_path="/lib", sounds=(sound("a", 20), sound("b", 1))
    )
    lines = example_lines(plan, 10)
    assert any("/lib/b.wav" in line for line in lines)
    assert sum(1 for line in lines if line.startswith("keep")) == 2
    assert any("and 18 more copies" in line for line in lines)


def test_example_lines_are_empty_for_an_empty_plan() -> None:
    assert example_lines(DedupePlan(root="r", root_path="/lib")) == []
