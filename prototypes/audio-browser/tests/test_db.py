from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from audio_browser.db import connect, init_db, now_iso, open_db


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def test_schema_creates_every_table(conn: sqlite3.Connection) -> None:
    assert {"blob", "alias", "favorite", "tag", "alias_fts"} <= table_names(conn)


def test_init_is_idempotent(db_path: Path) -> None:
    conn = open_db(db_path)
    init_db(conn)
    init_db(conn)
    assert {"blob", "alias"} <= table_names(conn)
    conn.close()


def test_wal_is_enabled(db_path: Path) -> None:
    conn = open_db(db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    conn.close()


def test_alias_needs_an_existing_blob(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
            "VALUES ('nope', '/x.wav', 'r', 'x.wav', '.wav', 1.0, ?)",
            (now_iso(),),
        )


def test_alias_path_is_unique(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO blob (hash, size_bytes) VALUES ('h', 10)")
    args = ("h", "/x.wav", "r", "x.wav", ".wav", 1.0, now_iso())
    sql = (
        "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    conn.execute(sql, args)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(sql, args)


def test_favorite_follows_the_hash_not_the_path(conn: sqlite3.Connection) -> None:
    """Two paths, one blob. Favoriting the blob marks both copies."""
    conn.execute("INSERT INTO blob (hash, size_bytes) VALUES ('h', 10)")
    for path in ("/a.wav", "/b.wav"):
        conn.execute(
            "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
            "VALUES ('h', ?, 'r', ?, '.wav', 1.0, ?)",
            (path, path.lstrip("/"), now_iso()),
        )
    conn.execute(
        "INSERT INTO favorite (hash, created_at) VALUES ('h', ?)", (now_iso(),)
    )
    rows = conn.execute(
        "SELECT a.path FROM alias a JOIN favorite f ON f.hash = a.hash"
    ).fetchall()
    assert {r["path"] for r in rows} == {"/a.wav", "/b.wav"}


def test_fts_triggers_track_alias_writes(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO blob (hash, size_bytes) VALUES ('h', 10)")
    conn.execute(
        "INSERT INTO alias (hash, path, root, filename, ext, mtime, seen_at) "
        "VALUES ('h', '/lib/deep_kick.wav', 'r', 'deep_kick.wav', '.wav', 1.0, ?)",
        (now_iso(),),
    )
    hits = conn.execute(
        "SELECT rowid FROM alias_fts WHERE alias_fts MATCH 'deep_kick'"
    ).fetchall()
    assert len(hits) == 1

    conn.execute("DELETE FROM alias WHERE path = '/lib/deep_kick.wav'")
    hits = conn.execute(
        "SELECT rowid FROM alias_fts WHERE alias_fts MATCH 'deep_kick'"
    ).fetchall()
    assert hits == []


def test_read_only_connection_cannot_write(db_path: Path) -> None:
    open_db(db_path).close()
    ro = connect(db_path, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO blob (hash, size_bytes) VALUES ('h', 1)")
    ro.close()
