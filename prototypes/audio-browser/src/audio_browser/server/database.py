"""One SQLite connection per request thread.

A ``sqlite3.Connection`` belongs to the thread that opened it. Routes are plain
``def`` functions, so Starlette runs them in its worker pool; each worker gets
its own connection here. WAL mode lets those readers run while another thread
writes a favorite or a peaks blob.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from ..db import connect, init_db


class MissingDatabase(Exception):
    """The configured database file does not exist."""


class Database:
    """Thread-local connections to one index file."""

    def __init__(self, path: Path, *, create: bool = False) -> None:
        if not create and not path.exists():
            raise MissingDatabase(
                f"no database at {path}; run 'audio-browser scan' first"
            )
        self.path = path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._peak_locks: dict[str, threading.Lock] = {}

    def connection(self) -> sqlite3.Connection:
        """The calling thread's connection, opened on first use.

        The connection is writable. Favorites and the lazy peaks cache both
        write, and both write only to the index, never to an audio root.

        The schema is applied on every fresh connection. Every statement in
        ``schema.sql`` is ``CREATE ... IF NOT EXISTS``, so this is a no-op on an
        up-to-date index and is how an index written before a table existed
        picks that table up. ``span`` arrived this way.
        """
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.path)
            init_db(conn)
            self._local.conn = conn
        return conn

    def peak_lock(self, file_hash: str) -> threading.Lock:
        """One lock per hash, so two requests never decode the same file twice."""
        with self._lock:
            lock = self._peak_locks.get(file_hash)
            if lock is None:
                lock = threading.Lock()
                self._peak_locks[file_hash] = lock
            return lock
