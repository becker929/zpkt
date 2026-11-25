"""Mounts: whole sets of web routes that an adapter or service puts under one path prefix of the web server.

The Song mounts the arranger's pages and routes under /app/song/. The web server knows only this table: it hands a
request whose path starts with a prefix to that mount, with the prefix cut off, and sends back what the mount answers.
So a new area is added without editing the server's own routes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

NO_STORE = "no-store"


@dataclass(frozen=True)
class MountReply:
    """What a mount answers: a status, a body, its type and its cache header."""

    code: int
    body: bytes
    ctype: str = "application/json"
    cache: str = NO_STORE


ReadBody = Callable[[int], bytes | None]  # the request body if its length is within the limit given, else None


class Mount(Protocol):
    """A set of routes. `path` begins with "/" and has the mount's prefix cut off; `read_body(limit)` reads the body."""

    def handle(self, method: str, path: str, read_body: ReadBody) -> MountReply: ...


class Mounts:
    """The mounts of one app, by path prefix (no trailing slash: "/app/song")."""

    def __init__(self) -> None:
        self._table: dict[str, Mount] = {}
        self._lock = threading.Lock()

    def add(self, prefix: str, mount: Mount) -> None:
        if not prefix.startswith("/") or prefix.endswith("/"):
            raise ValueError(f"a mount prefix starts with / and has no trailing /, not {prefix!r}")
        with self._lock:
            if prefix in self._table:
                raise ValueError(f"{prefix} is already mounted")
            self._table[prefix] = mount

    def remove(self, prefix: str) -> None:
        with self._lock:
            self._table.pop(prefix, None)

    def find(self, path: str) -> tuple[str, Mount, str] | None:
        """(prefix, mount, the path after the prefix) for a request path, or None. "/app/song" itself gives "/"."""
        with self._lock:
            items = list(self._table.items())
        for prefix, mount in items:
            if path == prefix:
                return prefix, mount, "/"
            if path.startswith(prefix + "/"):
                return prefix, mount, path[len(prefix) :]
        return None
