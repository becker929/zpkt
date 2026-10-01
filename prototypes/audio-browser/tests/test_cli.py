from __future__ import annotations

import os
from pathlib import Path

import pytest

from audio_browser.cli import human_bytes, human_duration, main
from conftest import needs_ffmpeg, write_wav


@pytest.fixture
def cli_config(tmp_path: Path) -> Path:
    """A config with a source tree and a byte-for-byte copy of it."""
    import shutil

    source = tmp_path / "compost"
    write_wav(source / "kick.wav", freq=60)
    write_wav(source / "loops" / "loop.wav", freq=220)
    (source / "session.rpp").write_text("not audio")
    shutil.copytree(source, tmp_path / "audio-library")

    config = tmp_path / "config.toml"
    config.write_text(
        'db = "index.db"\n\n'
        '[[roots]]\nname = "compost"\npath = "compost"\n\n'
        '[[roots]]\nname = "audio-library"\npath = "audio-library"\n',
        encoding="utf-8",
    )
    return config


def test_scan_then_dupes_then_stats(cli_config: Path, capsys) -> None:
    assert main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "hashed           4" in out

    assert main(["--config", str(cli_config), "dupes"]) == 0
    out = capsys.readouterr().out
    assert "duplicated blobs   2" in out
    assert "without a twin             0" in out
    assert "fully redundant" in out
    assert "never deletes anything" in out

    assert main(["--config", str(cli_config), "stats"]) == 0
    out = capsys.readouterr().out
    assert "aliases (paths)    4" in out
    assert "blobs (sounds)     2" in out


def test_rescan_reports_no_work(cli_config: Path, capsys) -> None:
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    out = capsys.readouterr().out
    assert "unchanged        4" in out
    assert "hashed           0" in out


def test_dupes_flags_a_file_that_is_only_in_the_copy(
    cli_config: Path, capsys
) -> None:
    write_wav(cli_config.parent / "audio-library" / "extra.wav", freq=999)
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    main(["--config", str(cli_config), "dupes", "--limit", "0"])
    out = capsys.readouterr().out
    assert "without a twin             1" in out
    assert "Do not delete it yet" in out


def test_scan_can_target_one_root(cli_config: Path, capsys) -> None:
    code = main(
        [
            "--config",
            str(cli_config),
            "scan",
            "--root",
            "compost",
            "--no-probe",
            "--quiet",
            "--no-prune",
        ]
    )
    assert code == 0
    assert "hashed           2" in capsys.readouterr().out


def test_unknown_root_is_an_error(cli_config: Path, capsys) -> None:
    assert main(["--config", str(cli_config), "scan", "--root", "nope"]) == 2
    assert "unknown root" in capsys.readouterr().err


def test_missing_config_is_an_error(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(tmp_path / "none.toml"), "stats"]) == 2
    assert "no config file" in capsys.readouterr().err


def test_stats_before_any_scan_is_an_error(cli_config: Path, capsys) -> None:
    assert main(["--config", str(cli_config), "stats"]) == 1
    assert "run 'audio-browser scan' first" in capsys.readouterr().err


def test_search_finds_a_filename(cli_config: Path, capsys) -> None:
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    main(["--config", str(cli_config), "search", "kick"])
    out = capsys.readouterr().out
    assert "kick.wav" in out
    assert "2 match(es)" in out


def test_dupes_skips_the_verdict_when_roots_are_missing(
    tmp_path: Path, capsys
) -> None:
    write_wav(tmp_path / "only" / "a.wav")
    config = tmp_path / "config.toml"
    config.write_text(
        'db = "index.db"\n\n[[roots]]\nname = "only"\npath = "only"\n',
        encoding="utf-8",
    )
    main(["--config", str(config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    assert main(["--config", str(config), "dupes"]) == 0
    assert "skipping redundancy check" in capsys.readouterr().err


def test_db_override(cli_config: Path, tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.db"
    main(
        [
            "--config",
            str(cli_config),
            "--db",
            str(other),
            "scan",
            "--no-probe",
            "--quiet",
        ]
    )
    assert other.exists()
    assert not (tmp_path / "index.db").exists()


def test_dedupe_requires_a_root(cli_config: Path) -> None:
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    with pytest.raises(SystemExit):
        main(["--config", str(cli_config), "dedupe"])


def test_dedupe_rejects_an_unknown_root(cli_config: Path, capsys) -> None:
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    assert main(["--config", str(cli_config), "dedupe", "--root", "nope"]) == 2
    assert "unknown root" in capsys.readouterr().err


def add_redundant_copies(root: Path) -> tuple[Path, Path]:
    """Two more copies of kick.wav, away from the .rpp at the root.

    The copy at the top of the tree sits beside ``session.rpp``, so it is
    protected. These two are not, which gives the planner something to choose
    between: ``copies/kick.wav`` survives and ``copies/deep/kick.wav`` goes.
    """
    survivor = write_wav(root / "copies" / "kick.wav", freq=60)
    doomed = write_wav(root / "copies" / "deep" / "kick.wav", freq=60)
    return survivor, doomed


def test_dedupe_dry_run_deletes_nothing(cli_config: Path, capsys) -> None:
    library = cli_config.parent / "audio-library"
    survivor, doomed = add_redundant_copies(library)
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()

    assert main(["--config", str(cli_config), "dedupe", "--root", "audio-library"]) == 0
    out = capsys.readouterr().out
    assert "files to delete  1" in out
    assert "DRY RUN" in out
    assert doomed.exists()
    assert survivor.exists()
    assert (library / "kick.wav").exists()


def test_dedupe_ignores_the_other_root(cli_config: Path, capsys) -> None:
    """The two trees mirror each other on purpose, so that is not redundancy."""
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    assert main(["--config", str(cli_config), "dedupe", "--root", "audio-library"]) == 0
    assert "files to delete  0" in capsys.readouterr().out


def test_dedupe_writes_a_plan_file(cli_config: Path, tmp_path: Path, capsys) -> None:
    library = cli_config.parent / "audio-library"
    _, doomed = add_redundant_copies(library)
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()

    out_file = tmp_path / "plan.txt"
    main(
        [
            "--config",
            str(cli_config),
            "dedupe",
            "--root",
            "audio-library",
            "--plan-out",
            str(out_file),
        ]
    )
    lines = [
        line
        for line in out_file.read_text().splitlines()
        if line and not line.startswith("#")
    ]
    assert lines == [str(doomed)]


def test_dedupe_apply_removes_the_redundant_copy(cli_config: Path, capsys) -> None:
    library = cli_config.parent / "audio-library"
    survivor, doomed = add_redundant_copies(library)
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()

    code = main(
        ["--config", str(cli_config), "dedupe", "--root", "audio-library", "--apply"]
    )
    assert code == 0
    assert "deleted          1" in capsys.readouterr().out
    assert not doomed.exists()
    assert survivor.exists()
    assert (library / "kick.wav").exists()


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores the write bit",
)
def test_dedupe_apply_refuses_a_read_only_root(cli_config: Path, capsys) -> None:
    """``compost`` is ``chmod -R a-w`` in real life.

    A root that cannot be written is not a root this tool may change, whatever
    the plan says.
    """
    compost = cli_config.parent / "compost"
    _, doomed = add_redundant_copies(compost)
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()

    compost.chmod(0o555)
    try:
        code = main(
            ["--config", str(cli_config), "dedupe", "--root", "compost", "--apply"]
        )
    finally:
        compost.chmod(0o755)
    assert code == 1
    assert "not writable" in capsys.readouterr().err
    assert doomed.exists()


def test_human_bytes() -> None:
    assert human_bytes(0) == "0 B"
    assert human_bytes(1023) == "1023 B"
    assert human_bytes(1536) == "1.5 KiB"
    assert human_bytes(65 * 1024**3) == "65.0 GiB"


def test_human_duration() -> None:
    assert human_duration(0) == "0:00:00"
    assert human_duration(3661) == "1:01:01"


# ------------------------------------------------------------------ segment


def test_segment_rejects_a_method_that_does_not_exist(cli_config: Path) -> None:
    """argparse refuses it before any model library is imported."""
    with pytest.raises(SystemExit):
        main(["--config", str(cli_config), "segment", "telepathy"])


def test_bakeoff_on_an_index_with_no_spans_says_so(cli_config: Path, capsys) -> None:
    assert main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"]) == 0
    capsys.readouterr()
    assert main(["--config", str(cli_config), "bakeoff"]) == 1
    assert "no method has written a span" in capsys.readouterr().err


def test_bakeoff_reports_one_method_without_comparing_it(
    cli_config: Path, tmp_path: Path, capsys
) -> None:
    assert main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"]) == 0
    capsys.readouterr()
    _write_spans(tmp_path / "index.db", [("yamnet", "speech", 0.0, 4.0)])

    assert main(["--config", str(cli_config), "bakeoff"]) == 0
    out = capsys.readouterr().out
    assert "yamnet" in out
    assert "nothing to compare" in out


def test_bakeoff_measures_where_two_methods_disagree(
    cli_config: Path, tmp_path: Path, capsys
) -> None:
    assert main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"]) == 0
    capsys.readouterr()
    _write_spans(
        tmp_path / "index.db",
        [("yamnet", "speech", 0.0, 4.0), ("clap", "music", 0.0, 4.0)],
    )

    assert main(["--config", str(cli_config), "bakeoff"]) == 0
    out = capsys.readouterr().out
    # `bakeoff` with no --method uses every method present, in name order.
    assert "clap vs yamnet: 0.0%" in out
    assert "music  in clap     but speech in yamnet" in out


def test_bakeoff_narrows_to_the_methods_it_is_given(
    cli_config: Path, tmp_path: Path, capsys
) -> None:
    assert main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"]) == 0
    capsys.readouterr()
    _write_spans(
        tmp_path / "index.db",
        [
            ("yamnet", "speech", 0.0, 4.0),
            ("clap", "music", 0.0, 4.0),
            ("vad", "other", 0.0, 4.0),
        ],
    )

    assert main(["--config", str(cli_config), "bakeoff", "--method", "yamnet"]) == 0
    out = capsys.readouterr().out
    assert "clap" not in out


def _write_spans(
    db_path: Path, rows: list[tuple[str, str, float, float]]
) -> None:
    """Attach spans to whatever the first blob in the index happens to be."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    file_hash = conn.execute("SELECT hash FROM blob LIMIT 1").fetchone()["hash"]
    conn.executemany(
        "INSERT INTO span (hash, method, start_s, end_s, label, confidence) "
        "VALUES (?, ?, ?, ?, ?, 0.9)",
        [(file_hash, method, start, end, label) for method, label, start, end in rows],
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ silence
#
# `audio-browser silence` is what makes the two silence tables reproducible
# rather than a pair of hand-written one-offs. These tests drive it end to end
# and then check the audio roots are untouched.


@needs_ffmpeg
def test_silence_measures_every_unmeasured_sound_and_then_stops(
    cli_config: Path, capsys
) -> None:
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()

    assert main(["--config", str(cli_config), "silence"]) == 0
    assert "measured 2 of 2 sound(s)" in capsys.readouterr().out

    # Restartable: a second run finds nothing left to do.
    assert main(["--config", str(cli_config), "silence"]) == 0
    assert "every sound has been measured" in capsys.readouterr().out


@needs_ffmpeg
def test_silence_leaves_every_audio_file_exactly_as_it_found_it(
    cli_config: Path, capsys
) -> None:
    """ffmpeg decodes to the null muxer. Nothing is opened for writing."""
    from conftest import tree_snapshot

    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    roots = ("compost", "audio-library")
    before = {root: tree_snapshot(cli_config.parent / root) for root in roots}

    main(["--config", str(cli_config), "silence", "--quiet"])
    capsys.readouterr()

    assert {root: tree_snapshot(cli_config.parent / root) for root in roots} == before


@needs_ffmpeg
def test_silence_writes_a_row_even_for_a_sound_with_no_gaps(
    cli_config: Path, capsys
) -> None:
    """Otherwise every restart would re-measure the sounds that hold no silence."""
    import sqlite3

    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    main(["--config", str(cli_config), "silence", "--quiet"])
    capsys.readouterr()

    conn = sqlite3.connect(cli_config.parent / "index.db")
    measured = conn.execute("SELECT COUNT(*) FROM silence").fetchone()[0]
    blobs = conn.execute("SELECT COUNT(*) FROM blob").fetchone()[0]
    conn.close()
    assert measured == blobs


# ----------------------------------------------------------------- projects


def test_projects_prints_the_board_from_the_files(cli_config: Path, capsys) -> None:
    import json

    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()

    projects = cli_config.parent / "projects"
    projects.mkdir()
    (projects / "a-project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "a-project",
                "name": "a project",
                "column": "stored",
                "created_at": "2026-09-16T21:04:00Z",
                "updated_at": "2026-09-16T21:04:00Z",
                "notes": "",
                "abandoned": None,
                "commits": [],
                "sounds": [],
            }
        ),
        encoding="utf-8",
    )

    assert main(["--config", str(cli_config), "projects"]) == 0
    out = capsys.readouterr().out
    assert "stored   1/1" in out
    assert "collage  0/1" in out
    assert "enrich   0/1" in out
    assert "1 project file(s)" in out


def test_projects_rebuild_derives_the_index_from_the_directory(
    cli_config: Path, capsys
) -> None:
    main(["--config", str(cli_config), "scan", "--no-probe", "--quiet"])
    capsys.readouterr()
    assert main(["--config", str(cli_config), "projects", "--rebuild"]) == 0
    assert "rebuilt the index from 0 file(s)" in capsys.readouterr().out
