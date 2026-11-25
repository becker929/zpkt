"""Watching the armed page in Live: the app tells the Remote Script what to watch, and Live's changes come back.

The pager used its own listeners in Live to report a value that moved. The Remote Script now has one generic watch
(zpkt.live.watch): the app registers the current page's state keys, and each change is pushed back on the app's one
connection. This service owns that: it registers a page's keys, re-registers when the connection was remade (the watches
live as long as the connection), and gives each change to a callback as (state key, raw value) from `serve`'s thread.

Built and tested on FakeLive. `zpkt app` does not turn it on yet: the pager's own reports still feed the desk until the
pager retires (CHANGE-app-gateway.md), and a pushing connection must be held open (`open_connections(pushes=True)`).
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from typing import Any

from zpkt.app.connections import LiveConnections
from zpkt.live import watch


class PageWatcher:
    """Registers keys with Live and hands each pushed change on. One owner of the watches, one lock."""

    def __init__(self, conn: LiveConnections, on_change: Callable[[str, Any], None]) -> None:
        self.conn, self.on_change = conn, on_change
        self._lock = threading.Lock()
        self._keys: tuple[str, ...] = ()
        self._made = -1  # the connection count the watches were registered on
        self.failed: dict[str, str] = {}  # key -> why Live could not watch it
        conn.on_push(self._pushed)

    def watch(self, keys: Iterable[str]) -> watch.Watching:
        """Watch exactly these state keys (replacing the last page's)."""
        unique = tuple(dict.fromkeys(keys))
        with self.conn.exclusive():
            got = watch.watch(self.conn, {k: k for k in unique}) if unique else watch.unwatch(self.conn)
            made = self.conn.connections
        with self._lock:
            self._keys, self._made, self.failed = unique, made, dict(got.failed)
        return got

    def ensure(self) -> bool:
        """Register again if the connection was remade since (Live's side forgot). True when it did."""
        with self._lock:
            keys, made = self._keys, self._made
        if not keys or self.conn.connections == made:
            return False
        self.watch(keys)
        return True

    def _pushed(self, message: dict[str, Any]) -> None:
        push = watch.parse_push(message)
        if push is None:
            return
        for change in push.changes:
            self.on_change(change.id, change.value)

    def serve(self, stop: threading.Event, wait_s: float = 0.05) -> None:
        """Read pushes until `stop` is set (run it in a thread). Reading never holds the lock while it waits."""
        while not stop.is_set():
            try:
                self.conn.pump_pushes(wait_s)
                self.ensure()
            except Exception as exc:  # one bad read or a lost connection never ends the watching
                print(f"app: watching Live failed ({type(exc).__name__}: {exc}); trying again", flush=True)
                stop.wait(0.5)
