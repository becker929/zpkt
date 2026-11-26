"""The first-choice capture: the "zpkt listen" Max for Live device on Main, read by zpkt.live.listen.

The device sends Live's own samples at Live's sample rate (44.1 kHz on a set at 44.1 kHz), about 12 ms after Live
played them, and needs no macOS permission. It has to be on Main (contrib/mixdesk/listen.py install puts it there),
and Live has to be running its audio: with no audio output device selected Live's clock stands still and the device
sends nothing.

The sockets are the app's (zpkt.app.connections.open_listen_sockets); zpkt.live.listen is handed them. Starting a
capture binds the port, asks the device to send and waits a moment for it to connect and say its rate. When nothing
comes, the ports are freed and the capture is Unavailable, so a chain can go on to the screen capture.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable

from zpkt.app.connections import open_listen_sockets
from zpkt.app.listen.capture import Unavailable
from zpkt.live.listen import CONTROL_PORT, DEFAULT_RATE, LISTEN_PORT, ListenSource

NAME = "live device"
CONNECT_WAIT_S = 1.5  # how long the device is given to connect: it hears "/listen 1" about once a second
RATE_WAIT_S = 1.5  # and, once connected, to say Live's sample rate (it says it with every "/listen 1")
GONE_AFTER_S = 4.0  # a running capture ends when the device has been away this long
POLL_S = 0.25  # how often a read with no sound looks at the device's state
NO_DEVICE = (
    'Live did not send its sound. Put the "zpkt listen" device on Main in Live (on the Mac: '
    ".venv/bin/python contrib/mixdesk/listen.py install), and see that Live is running with an audio output device "
    "selected in its Audio settings: without one Live's clock stands still and nothing is sent."
)
NO_RATE = (
    'The "zpkt listen" device on Main connected but did not say Live\'s sample rate. Build it again '
    "(.venv/bin/python contrib/mixdesk/listen.py make), then delete it from Main and install it again."
)
PORT_TAKEN = (
    "Something else on the Mac is already reading Live's sound (port {port} is taken: another copy of zpkt app, or "
    "contrib/mixdesk/listen.py check). Stop it and tap Listen again."
)

Sockets = Callable[[int], tuple[socket.socket, socket.socket]]


class DeviceStream:
    """A running capture from the device. `read` waits for sound for as long as the device is there."""

    source = NAME

    def __init__(self, reader: ListenSource, rate: int, gone_after: float = GONE_AFTER_S) -> None:
        self.reader = reader
        self.rate = rate
        self.gone_after = gone_after
        self._closed = threading.Event()
        self._lock = threading.Lock()

    def read(self) -> bytes:
        """The next piece of PCM. A quiet moment (Live's audio stopped, the set is being changed) is waited out;
        b"" only when the capture is closed, the device has been away for `gone_after` seconds, or Live's sample rate
        is no longer the one this capture started with (the hub then starts a new capture, at the new rate)."""
        seen = time.monotonic()  # when the device was last connected
        while not self._closed.is_set():
            data = self.reader.read(POLL_S)
            if self.reader.rate != self.rate:
                return b""
            if data:
                return data
            status = self.reader.status()
            now = time.monotonic()
            if status.connected:
                seen = now
            elif now - seen >= self.gone_after:
                return b""
        return b""

    def close(self) -> None:
        """Tell the device to stop ("/listen 0") and free the ports."""
        self._closed.set()
        with self._lock:
            self.reader.stop()


class DeviceCapture:
    """The source: one ListenSource per capture, on sockets the app opens."""

    name = NAME

    def __init__(
        self,
        port: int = LISTEN_PORT,
        control_port: int = CONTROL_PORT,
        connect_wait: float = CONNECT_WAIT_S,
        rate_wait: float = RATE_WAIT_S,
        gone_after: float = GONE_AFTER_S,
        sockets: Sockets = open_listen_sockets,
    ) -> None:
        self.port = port
        self.control_port = control_port
        self.connect_wait = connect_wait
        self.rate_wait = rate_wait
        self.gone_after = gone_after
        self.sockets = sockets
        self.rate = DEFAULT_RATE  # until the device has said Live's
        self._one = threading.Lock()  # one capture or check at a time: they need the same port

    def _start(self) -> tuple[ListenSource, int]:
        """A started reader the device has connected to, and Live's rate. Raises Unavailable, with the ports freed."""
        try:
            server, control = self.sockets(self.port)
        except OSError as exc:
            raise Unavailable(PORT_TAKEN.format(port=self.port)) from exc
        reader = ListenSource(server, control, ("127.0.0.1", self.control_port))
        reader.start()
        began = time.monotonic()
        connected = 0.0
        while True:
            status = reader.status()
            now = time.monotonic()
            if status.connected and not connected:
                connected = now
            if status.rate_known:
                self.rate = status.rate
                return reader, status.rate
            if not connected and now - began >= self.connect_wait:
                reason = NO_DEVICE
                break
            if connected and now - connected >= self.rate_wait:
                reason = NO_RATE
                break
            time.sleep(0.02)
        reader.stop()
        raise Unavailable(reason)

    def check(self) -> str:
        """Ask the device for a moment: "" when it connects and says its rate. Nothing is left running."""
        with self._one:
            try:
                reader, _ = self._start()
            except Unavailable as exc:
                return str(exc)
            reader.stop()
            return ""

    def open(self) -> DeviceStream:
        with self._one:
            reader, rate = self._start()
            return DeviceStream(reader, rate, self.gone_after)
