"""Mounts: the one seam by which an adapter puts its pages and routes on the web server, under a path prefix.

Ask is mounted at /app/ask and Listen at /app/listen. The web server knows only this table: it hands a request whose
path starts with a prefix to that mount, as a Request, and sends back the MountReply the mount answers. A mount that
answers as it goes (a server-sent stream) writes on the request's connection and returns None. So a new area is
added without editing the server's own routes: `desk.mounts.add("/app/notes", NotesRoutes())`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

NO_STORE = "no-store"


@dataclass(frozen=True)
class MountReply:
    """What a mount answers: a status, a body, its type and its cache header."""

    code: int
    body: bytes
    ctype: str = "application/json"
    cache: str = NO_STORE


ReadBody = Callable[[int], bytes | None]  # the request body if its length is within the limit given, else None


@dataclass(frozen=True)
class Request:
    """One request for a mount."""

    method: str  # GET, HEAD, POST, PUT, PATCH or DELETE
    path: str  # the whole path asked, without the query
    rest: str  # the path with the mount's prefix cut off; it begins with "/"
    query: dict[str, str]
    read_body: ReadBody
    connection: Any  # the web server's handler: the request's headers, and the socket for a mount that streams


class Mount(Protocol):
    """A set of routes under one prefix."""

    def handle(self, request: Request) -> MountReply | None:
        """The answer; or None when the mount wrote its own answer on `request.connection` (a stream)."""
        ...


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

    def prefixes(self) -> list[str]:
        with self._lock:
            return sorted(self._table)

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
