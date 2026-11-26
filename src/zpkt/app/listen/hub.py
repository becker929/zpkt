"""The hub: one capture, shared by every listener, running only while somebody listens.

The first listener starts the capture. When the last one leaves, the capture goes on for a few seconds (`linger`), so
a page reload or a change of page does not restart it, and then stops. Each listener has a short queue. When a
listener is slow (a phone on a bad network), its oldest sound is dropped: late sound is worth less than a gap.

The sample rate is the open capture's. Each listener is told the rate of the capture it joined, and when a capture
has to be started again and comes back at another rate, the listeners are ended so their pages connect anew.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from zpkt.app.listen import FRAME, audio_format
from zpkt.app.listen.capture import Source, Stream, Unavailable

QUEUE_CHUNKS = 24  # about half a second of sound, at the 20 ms pieces the capture gives
CHECK_KEPT_S = 10.0


class Listener:
    """One listener's queue of PCM. `get` waits for the next piece; None means the capture has ended."""

    def __init__(self, rate: int = 0, source: str = "") -> None:
        self.rate = rate  # of the capture this listener joined; it does not change while the listener lives
        self.source = source
        self.q: queue.Queue[bytes | None] = queue.Queue(maxsize=QUEUE_CHUNKS)
        self.dropped = 0

    def put(self, chunk: bytes | None) -> None:
        while True:
            try:
                return self.q.put_nowait(chunk)
            except queue.Full:
                try:
                    self.q.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass

    def get(self, timeout: float = 1.0) -> bytes | None:
        """The next piece; b"" when none came in `timeout` (the capture is alive but quiet); None at the end."""
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return b""


class Hub:
    def __init__(self, source: Source, linger: float = 5.0, restart_after: float = 2.0) -> None:
        self.source = source
        self.linger = linger
        self.restart_after = restart_after  # a capture that ran this long and then ended is started again
        self._lock = threading.Lock()
        self._listeners: set[Listener] = set()
        self._stream: Stream | None = None
        self._timer: threading.Timer | None = None
        self._checked: tuple[float, str] | None = None
        self.starts = 0  # how many times a capture was started (for the status, and for tests)

    # ---- listeners -----------------------------------------------------------------------------------------------
    def join(self) -> Listener:
        """A new listener. Starts the capture if it is not running. Raises Unavailable."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if self._stream is None:
                try:
                    stream = self.source.open()
                except Unavailable as exc:
                    self._checked = (time.monotonic(), str(exc))
                    raise
                self._checked = (time.monotonic(), "")
                self._stream = stream
                self.starts += 1
                threading.Thread(target=self._pump, args=(stream,), daemon=True, name="listen-pump").start()
            listener = Listener(self._stream.rate, self._stream.source)
            self._listeners.add(listener)
            return listener

    def leave(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.discard(listener)
            self._linger()

    def _linger(self) -> None:
        """With the lock held: when nobody listens, stop the capture a little later."""
        if self._listeners or self._stream is None or self._timer is not None:
            return
        self._timer = threading.Timer(self.linger, self._stop_if_alone)
        self._timer.daemon = True
        self._timer.start()

    def _stop_if_alone(self) -> None:
        with self._lock:
            self._timer = None
            if self._listeners or self._stream is None:
                return
            stream, self._stream = self._stream, None
        stream.close()

    def _pump(self, stream: Stream) -> None:
        """Hand the capture's sound to every listener until it is stopped. A capture that ends by itself after
        running a while (macOS cut it off, the device went away) is started again, so listeners hear a gap and not
        an end. When it comes back at another sample rate (another capture, or Live's rate changed) the listeners
        are ended instead: what they play at the old rate would be wrong, and their pages connect again."""
        while True:
            began = time.monotonic()
            self._copy(stream)
            with self._lock:
                if self._stream is not stream:
                    return  # stopped on purpose; a newer capture may be running
                again = bool(self._listeners) and time.monotonic() - began >= self.restart_after
            stream.close()
            fresh: Stream | None = None
            reason = ""
            if again:
                try:
                    fresh = self.source.open()
                except Unavailable as exc:
                    reason = str(exc)
            with self._lock:
                if self._stream is not stream:  # stopped while it was starting again
                    if fresh is not None:
                        fresh.close()
                    return
                self._stream = fresh
                same = fresh is not None and fresh.rate == stream.rate
                listeners = [] if same else list(self._listeners)
                if fresh is not None:
                    self.starts += 1
                    if not same:
                        self._listeners.clear()
                        self._linger()
                else:
                    self._checked = (time.monotonic(), reason) if reason else None
            for listener in listeners:  # it is over for them: their pages reconnect, or say why they cannot
                listener.put(None)
            if fresh is None:
                return
            stream = fresh

    def _copy(self, stream: Stream) -> None:
        """One capture's sound, in whole frames, to every listener, until it ends."""
        rest = b""
        while True:
            data = stream.read()
            if not data:
                return
            data = rest + data
            whole = len(data) - len(data) % FRAME
            data, rest = data[:whole], data[whole:]
            if not data:
                continue
            with self._lock:
                if self._stream is not stream:
                    return
                listeners = list(self._listeners)
            for listener in listeners:
                listener.put(data)

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            stream, self._stream = self._stream, None
            listeners = list(self._listeners)
            self._listeners.clear()
        for listener in listeners:
            listener.put(None)
        if stream is not None:
            stream.close()

    # ---- status --------------------------------------------------------------------------------------------------
    def reason(self) -> str:
        """ "" when listening can start, else why not. A running capture is its own proof; a check is kept 10 s."""
        with self._lock:
            if self._stream is not None:
                return ""
            kept = self._checked
        now = time.monotonic()
        if kept is not None and now - kept[0] < CHECK_KEPT_S:
            return kept[1]
        reason = self.source.check()
        with self._lock:
            self._checked = (now, reason)
        return reason

    def status(self) -> dict[str, Any]:
        """`format` and `source` are the running capture's. With none running they are what the last check or
        capture found: the rate a new listener will most likely get, and which capture ("" when none can start)."""
        reason = self.reason()
        with self._lock:
            stream = self._stream
            source = stream.source if stream is not None else "" if reason else self.source.name
            return {
                "available": not reason,
                "reason": reason,
                "listeners": len(self._listeners),
                "capturing": stream is not None,
                "source": source,
                "format": audio_format(stream.rate if stream is not None else self.source.rate),
            }
