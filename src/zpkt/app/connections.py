"""The app's connections to Live: the one LiveClient and the meter's UDP socket, behind one lock.

Only the app talks to Live. It opens these once, at start, and hands `LiveConnections` into every zpkt.live call (it
is an McpTransport, so `state.take(connections)` works). zpkt.live and zpkt.audio never open a connection.

The lock makes every call to Live take its turn. `exclusive()` holds it across several calls (one read of the whole
mix; a render), and a command that cannot get it in time is refused with a reason rather than dropped. The meter's
socket is read in its own thread and is not under the lock: a read blocks until the device sends.

Tests hand in FakeLive and a fake socket, so they need no ports.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Iterator
from typing import Any, Protocol

from zpkt.live.meter import DatagramSource, read_levels
from zpkt.live.transport import LiveClient, McpResult, McpTransport

CALL_TIMEOUT_S = 10.0  # each call to Live; the Remote Script gives up at 12
BUSY_WAIT_S = 5.0  # how long a command waits for Live before it says Live is busy


class LiveBusy(RuntimeError):
    """Live is held by another job (a render, a long read); the message says so."""


class Closable(Protocol):
    def close(self) -> None: ...


class LiveConnections:
    """The one connection to Live, as an McpTransport, plus the meter's socket. One owner, one lock."""

    def __init__(self, live: McpTransport, meter: DatagramSource | None = None, closers: tuple[Closable, ...] = ()):
        self.live = live
        self.meter = meter
        self.lock = threading.RLock()
        self._closers = closers

    # ---- McpTransport: every call to Live holds the lock ---------------------------------------------------------
    def execute(self, code: str) -> McpResult:
        with self.lock:
            return self.live.execute(code)

    def run(self, code: str) -> Any:
        with self.lock:
            return self.live.run(code)

    @contextlib.contextmanager
    def exclusive(self, wait_s: float | None = None) -> Iterator[LiveConnections]:
        """Hold Live for several calls. `wait_s` None waits for as long as it takes; a number gives up and raises
        LiveBusy after that many seconds."""
        if not self.lock.acquire(timeout=-1 if wait_s is None else wait_s):
            raise LiveBusy("Live is busy with another job (a render?). Try again in a moment.")
        try:
            yield self
        finally:
            self.lock.release()

    # ---- the meter -------------------------------------------------------------------------------------------------
    def read_meter(self) -> list[float] | None:
        """One meter message's RMS levels (blocks until one comes); None for a datagram that is not one."""
        if self.meter is None:
            raise RuntimeError("this app has no meter socket")
        return read_levels(self.meter)

    def close(self) -> None:
        for c in self._closers:
            with contextlib.suppress(OSError):
                c.close()


def bind_udp(port: int) -> socket.socket:
    """A UDP socket on localhost: the app's side of the meter and of the pager's datagrams."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", port))
    return s


class MeterSocket:
    """The meter's UDP socket, bound when the first read asks, so building the app binds nothing."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._sock: socket.socket | None = None
        self._closed = False
        self._lock = threading.Lock()

    def _open(self) -> socket.socket:
        with self._lock:
            if self._closed:
                raise OSError("the meter socket is closed")
            if self._sock is None:
                self._sock = bind_udp(self.port)
            return self._sock

    def recvfrom(self, size: int, /) -> tuple[bytes, Any]:
        return self._open().recvfrom(size)

    def fileno(self) -> int:
        return -1 if self._closed else 0

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._sock is not None:
                self._sock.close()


def open_connections(live_port: int | None, meter_port: int | None) -> LiveConnections:
    """The real connections: a LiveClient (live_port None is the rig's) and the meter's socket (None: no meter)."""
    client = LiveClient(timeout=CALL_TIMEOUT_S, retries=1, port=live_port)
    sock = None if meter_port is None else MeterSocket(meter_port)
    closers: tuple[Closable, ...] = (client,) if sock is None else (client, sock)
    return LiveConnections(client, sock, closers)
