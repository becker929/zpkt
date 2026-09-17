"""SQLite connection handling.

One writer thread owns the connection. Workers never touch it.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from collections.abc import Iterator
from pathlib import Path


def schema_sql() -> str:
    """The contents of ``schema.sql``, shipped inside the package."""
    return resources.files("audio_browser").joinpath("schema.sql").read_text()


def connect(db_path: Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open the database and apply the pragmas the scan relies on.

    WAL keeps readers from blocking the writer. ``synchronous=NORMAL`` trades a
    crash costing the unflushed batch for a much faster scan; the scan is
    restartable, so that is the right trade.
    """
    if read_only:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if not read_only:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables, indexes, the FTS index and its sync triggers."""
    conn.executescript(schema_sql())
    conn.commit()


def open_db(db_path: Path) -> sqlite3.Connection:
    """Open for writing and make sure the schema exists."""
    conn = connect(db_path)
    init_db(conn)
    return conn


@contextmanager
def writer(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a writable connection, close it on the way out."""
    conn = open_db(db_path)
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def now_iso() -> str:
    """Current UTC time, ISO 8601, second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()
