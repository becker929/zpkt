"""Listen: Live's output as a PCM stream, sent by a Max for Live device on Main.

The device is built by contrib/mixdesk/listen.py ("zpkt listen"). It passes the audio through untouched. Beside it,
jit.catch~ collects the stereo signal and jit.net.send sends it to 127.0.0.1:LISTEN_PORT over TCP as Jitter matrices
(one-dimensional, two planes of float32, one cell per sample frame), about a hundred times a second. It sends only
while asked: an OSC message "/listen 1" on UDP CONTROL_PORT starts it, "/listen 0" stops it, and it stops by itself
when no "/listen 1" has come for WATCHDOG_MS (so a reader that dies leaves nothing running).

This module is the reading side. It never opens a socket: the caller hands in a listening TCP socket (the device
connects to it) and a UDP socket to send the control messages from, as the app does for the meter
(zpkt.app.connections). `ListenSource` gives interleaved signed 16-bit little-endian stereo PCM at Live's sample
rate, which the device reports on the same connection once a second.

The wire format is Cycling '74's Jitter networking protocol: chunks of a four-character id and a 32-bit size, then
a body. "JMTX" is a matrix (a 288-byte header, then the cells); "JMMP" is a Max message (here "sr 48000."); "JMLP"
is a latency reply, which this side never needs to send.
"""

from __future__ import annotations

import contextlib
import math
import queue
import select
import struct
import sys
import threading
import time
from array import array
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

LISTEN_PORT = 8988  # TCP: the device connects here and sends the audio
CONTROL_PORT = 8989  # UDP: the device hears "/listen 1" and "/listen 0" here
CHANNELS = 2
SAMPLE_WIDTH = 2  # bytes: signed 16-bit little-endian
DEFAULT_RATE = 48000  # assumed until the device reports Live's rate
INTERVAL_MS = 5  # how often the device looks for collected audio to send (it sends one audio buffer at a time)
KEEPALIVE_S = 1.0  # how often the reader says "/listen 1"
WATCHDOG_MS = 3000  # the device stops when it has heard nothing for this long
SILENT_PEAK = 1e-4  # -80 dBFS: under this for SILENT_AFTER_S the status is "silent"
SILENT_AFTER_S = 1.0
STALE_S = 0.5  # no matrix for this long: no longer "receiving"
STALLED_S = 2.5  # asked for this long and nothing came: say "off" and "on" again
SETTLE_MAX_S = 1.5  # at most this long is spent dropping the device's backlog when a stream starts

_MATRIX = b"JMTX"
_MESSAGE = b"JMMP"
_LATENCY = b"JMLP"
_MATRIX_HEADER = 288  # id, size, planecount, type, dimcount, dim[32], dimstride[32], datasize, time
_FLOAT32, _FLOAT64 = 2, 3
_MAX_CHUNK = 1 << 22  # 4 MB: no chunk the device sends comes near; a larger size means a broken stream


# ---- the control messages (OSC) ------------------------------------------------------------------------------------
def control_message(on: bool) -> bytes:
    """The OSC datagram that starts or stops the device's sending: "/listen" with one int."""
    return b"/listen\x00" + b",i\x00\x00" + struct.pack(">i", 1 if on else 0)


# ---- decoding the stream -------------------------------------------------------------------------------------------
@dataclass
class Block:
    """One matrix as PCM: interleaved s16le stereo, its frame count, peak (0..1) and when it arrived."""

    pcm: bytes
    frames: int
    peak: float
    at: float


def _order(first: int) -> str:
    """The byte order of a chunk, from its size field: the same field read the other way is absurd."""
    return ">" if first < (1 << 24) else "<"


def float_to_s16le(samples: array[float]) -> tuple[bytes, float]:
    """Float samples (-1..1) as s16le bytes, clipped at full scale, and their peak before clipping."""
    out = array("h", bytes(2 * len(samples)))
    peak = 0.0
    for i, v in enumerate(samples):
        if v != v:  # NaN
            v = 0.0
        a = -v if v < 0 else v
        if a > peak:
            peak = a
        out[i] = 32767 if v >= 1.0 else -32768 if v <= -1.0 else round(v * 32767.0)
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes(), peak


def decode_matrix(body: bytes, at: float = 0.0) -> Block | None:
    """A "JMTX" chunk's body (header and cells) as a Block; None when it is not float audio.

    Everything but the id is big-endian on the wire, the cells too (seen from Live 12 on Apple silicon: the id reads
    "XTMJ", a float 1.0 is 3f 80 00 00). Should a sender ever leave the cells in its own order, they read as
    absurd numbers this way round and are taken the other way."""
    if len(body) < _MATRIX_HEADER or body[:4] not in (_MATRIX, _MATRIX[::-1]):
        return None
    planes, kind, dimcount = struct.unpack_from(">3i", body, 8)
    if kind not in (_FLOAT32, _FLOAT64) or not 1 <= planes <= 32 or not 1 <= dimcount <= 32:
        return None
    dim = struct.unpack_from(f">{dimcount}i", body, 20)
    datasize = struct.unpack_from(">i", body, 276)[0]
    frames = 1
    for d in dim:
        frames *= d
    width = 4 if kind == _FLOAT32 else 8
    cells = body[_MATRIX_HEADER : _MATRIX_HEADER + datasize]
    if frames <= 0 or len(cells) < frames * planes * width:
        return None
    floats = array("f" if kind == _FLOAT32 else "d")
    floats.frombytes(cells[: frames * planes * width])
    if sys.byteorder == "little":
        floats.byteswap()
    if not _plausible(floats):
        floats.byteswap()
        if not _plausible(floats):
            return None
    if planes == CHANNELS:
        stereo = floats
    else:  # one plane: the same on both sides; more than two: the first two
        stereo = array(floats.typecode, bytes(floats.itemsize * frames * 2))
        stereo[0::2] = floats[0::planes]
        stereo[1::2] = floats[0::planes] if planes == 1 else floats[1::planes]
    pcm, peak = float_to_s16le(stereo)
    return Block(pcm, frames, peak, at)


def _plausible(floats: array[float]) -> bool:
    """Whether the cells read as audio: in the wrong byte order floats come out huge, or not numbers at all."""
    loudest = max(max(floats), -min(floats))
    return loudest == loudest and loudest < 1000.0


def decode_message(body: bytes) -> list[Any]:
    """A "JMMP" chunk's body as the Max message: its name, then its arguments; [] when it does not parse.

    The body is a 32-bit size, a 32-bit count, then atoms: one type byte and a value ('s' a zero-terminated symbol,
    'l' a 32-bit int, 'f' a 32-bit float; numbers big-endian), padded with zeros to the size."""
    atoms: list[Any] = []
    i = 8
    try:
        while i < len(body):
            tag = body[i : i + 1]
            i += 1
            if tag == b"s":
                end = body.index(b"\x00", i)
                atoms.append(body[i:end].decode("utf-8", "replace"))
                i = end + 1
            elif tag == b"l":
                atoms.append(struct.unpack_from(">i", body, i)[0])
                i += 4
            elif tag == b"f":
                atoms.append(struct.unpack_from(">f", body, i)[0])
                i += 4
            else:
                break
    except (ValueError, struct.error):
        return []
    return atoms


def encode_matrix(samples: Sequence[float], planes: int = CHANNELS, time_ms: float = 0.0) -> bytes:
    """Interleaved float samples as the "JMTX" chunk the device would send: for tests and stand-in devices."""
    frames = len(samples) // planes
    cells = array("f", samples[: frames * planes])
    if sys.byteorder == "little":
        cells.byteswap()
    data = cells.tobytes()
    dim = [frames] + [1] * 31
    stride = [4 * planes] + [0] * 31
    header = _MATRIX[::-1] + struct.pack(">4i", _MATRIX_HEADER, planes, _FLOAT32, 1)
    header += struct.pack(">32i", *dim) + struct.pack(">32i", *stride) + struct.pack(">id", len(data), time_ms)
    return _MATRIX + struct.pack("<i", _MATRIX_HEADER) + header + data


def encode_message(name: str, *args: float | int | str) -> bytes:
    """A Max message as the "JMMP" chunk the device would send (e.g. "sr", 44100.0)."""
    atoms = b"s" + name.encode() + b"\x00"
    for a in args:
        if isinstance(a, str):
            atoms += b"s" + a.encode() + b"\x00"
        elif isinstance(a, int):
            atoms += b"l" + struct.pack(">i", a)
        else:
            atoms += b"f" + struct.pack(">f", a)
    size = 8 + len(atoms) + 4
    return _MESSAGE + struct.pack(">i", size) + struct.pack(">2i", size, 1) + atoms + b"\x00" * 4


@dataclass
class Decoder:
    """Bytes of the device's TCP stream in, Blocks out. Keeps what is left of a chunk until the rest comes."""

    rate: int = 0  # Live's sample rate as the device last reported it; 0 until it has
    _buf: bytearray = field(default_factory=bytearray)

    def feed(self, data: bytes, at: float = 0.0) -> list[Block]:
        self._buf += data
        blocks: list[Block] = []
        while True:
            if len(self._buf) < 8:
                return blocks
            ident = bytes(self._buf[:4])
            if ident not in (_MATRIX, _MESSAGE, _LATENCY):
                # Lost the chunk boundary: look for the next id and go on from there.
                nxt = min((p for p in (self._buf.find(k, 1) for k in (_MATRIX, _MESSAGE)) if p > 0), default=-1)
                del self._buf[: nxt if nxt > 0 else max(0, len(self._buf) - 3)]
                if nxt < 0:
                    return blocks
                continue
            first = struct.unpack_from(">i", self._buf, 4)[0]
            size = first if _order(first) == ">" else struct.unpack_from("<i", self._buf, 4)[0]
            if ident == _LATENCY:
                size = 32  # four doubles; its header has no size field
                if len(self._buf) < 4 + size:
                    return blocks
                del self._buf[: 4 + size]
                continue
            if size < 0 or size > _MAX_CHUNK:
                del self._buf[:4]
                continue
            if ident == _MATRIX:
                # The chunk's size is the matrix header's; the cells follow, their length in the header.
                if len(self._buf) < 8 + size:
                    return blocks
                datasize = struct.unpack_from(">i", self._buf, 8 + 276)[0]
                if datasize < 0 or datasize > _MAX_CHUNK:
                    del self._buf[:4]
                    continue
                total = 8 + size + datasize
                if len(self._buf) < total:
                    return blocks
                block = decode_matrix(bytes(self._buf[8:total]), at)
                del self._buf[:total]
                if block is not None:
                    blocks.append(block)
                continue
            if len(self._buf) < 8 + size:
                return blocks
            atoms = decode_message(bytes(self._buf[8 : 8 + size]))
            del self._buf[: 8 + size]
            if len(atoms) == 2 and atoms[0] == "sr" and isinstance(atoms[1], int | float) and atoms[1] > 0:
                self.rate = round(atoms[1])


# ---- the source ----------------------------------------------------------------------------------------------------
class ListeningSocket(Protocol):
    """What `ListenSource` needs of the TCP socket it is handed: bound and listening on localhost."""

    def accept(self) -> tuple[Any, Any]: ...
    def fileno(self) -> int: ...
    def close(self) -> None: ...


class ControlSocket(Protocol):
    """What `ListenSource` needs of the UDP socket it is handed."""

    def sendto(self, data: bytes, address: Any, /) -> int: ...
    def close(self) -> None: ...


@dataclass
class ListenStatus:
    state: str  # "receiving", "silent", "no device" or "stopped"
    rate: int  # Live's sample rate (DEFAULT_RATE until the device has reported it)
    rate_known: bool
    connected: bool
    frames: int  # sample frames received since start
    blocks: int
    dropped: int  # blocks thrown away because nobody read them
    stale: int  # blocks of old audio thrown away when the stream started
    reconnects: int
    peak: float  # the loudest sample of the last second, 0..1
    interval_ms: float  # mean time between blocks
    jitter_ms: float  # standard deviation of the time between blocks
    max_gap_ms: float  # the longest wait between two blocks


class ListenSource:
    """Live's output as s16le stereo PCM, from the "zpkt listen" device.

    `server` is a TCP socket already listening on 127.0.0.1:LISTEN_PORT; `control` a UDP socket. Both are closed by
    `stop()`. `start()` asks the device to send and keeps asking; `read()` waits for the next chunk, at most
    `timeout` seconds, and returns b"" when none came (it never blocks for ever); `stop()` tells the device to
    stop. Chunks nobody reads are dropped oldest first, so a slow reader hears the present, late.
    """

    def __init__(
        self,
        server: ListeningSocket,
        control: ControlSocket,
        control_address: tuple[str, int] = ("127.0.0.1", CONTROL_PORT),
        max_queued: int = 200,
    ) -> None:
        self._server = server
        self._control = control
        self._address = control_address
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queued)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._decoder = Decoder()
        self._connected = False
        self._frames = self._blocks = self._dropped = self._reconnects = 0
        self._last_block = 0.0
        self._last_loud = 0.0
        self._peaks: list[tuple[float, float]] = []
        self._gaps: list[float] = []
        self._started = False
        self._stale = 0
        self._settling_since = 0.0  # when the stream (re)started; 0 once its backlog has gone by

    # ---- the interface ---------------------------------------------------------------------------------------------
    @property
    def rate(self) -> int:
        return self._decoder.rate or DEFAULT_RATE

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stop.clear()
        for target in (self._receive, self._keepalive):
            t = threading.Thread(target=target, daemon=True, name=f"listen-{target.__name__.strip('_')}")
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        self._say(False)
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads.clear()
        for s in (self._server, self._control):
            with contextlib.suppress(OSError):
                s.close()
        self._started = False
        self._connected = False

    def read(self, timeout: float = 1.0) -> bytes:
        """The next chunk of interleaved s16le stereo PCM; b"" when none came within `timeout` seconds."""
        try:
            return self._queue.get(timeout=max(0.0, timeout))
        except queue.Empty:
            return b""

    def __iter__(self) -> Iterator[bytes]:
        """Chunks until `stop()`. A gap in the audio yields b"" about once a second, so a consumer can notice."""
        while not self._stop.is_set():
            yield self.read(1.0)

    def status(self) -> ListenStatus:
        now = time.monotonic()
        with self._lock:
            gaps = list(self._gaps)
            peak = max((p for t, p in self._peaks if now - t <= SILENT_AFTER_S), default=0.0)
            fresh = self._connected and now - self._last_block < STALE_S
            if not self._started:
                state = "stopped"
            elif not fresh:
                state = "no device"
            elif now - self._last_loud > SILENT_AFTER_S:
                state = "silent"
            else:
                state = "receiving"
            mean = sum(gaps) / len(gaps) if gaps else 0.0
            sd = math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps)) if gaps else 0.0
            return ListenStatus(
                state=state,
                rate=self.rate,
                rate_known=bool(self._decoder.rate),
                connected=self._connected,
                frames=self._frames,
                blocks=self._blocks,
                dropped=self._dropped,
                stale=self._stale,
                reconnects=self._reconnects,
                peak=peak,
                interval_ms=mean * 1000.0,
                jitter_ms=sd * 1000.0,
                max_gap_ms=max(gaps, default=0.0) * 1000.0,
            )

    # ---- the threads -----------------------------------------------------------------------------------------------
    def _say(self, on: bool) -> None:
        with contextlib.suppress(OSError):
            self._control.sendto(control_message(on), self._address)

    def _keepalive(self) -> None:
        # Off then on: a device still sending to a reader that died starts again from a known state.
        self._say(False)
        time.sleep(0.05)
        asked = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                quiet = now - max(self._last_block, asked)
            if quiet > STALLED_S:  # asked and nothing comes: start the device again from "off"
                self._say(False)
                time.sleep(0.05)
                asked = now
            self._say(True)
            self._stop.wait(KEEPALIVE_S)

    def _receive(self) -> None:
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([self._server], [], [], 0.25)
                if not ready:
                    continue
                conn, _ = self._server.accept()
            except (OSError, ValueError):
                if self._stop.wait(0.25):
                    return
                continue
            with self._lock:
                self._connected = True
                self._reconnects += 1
                self._decoder = Decoder(rate=self._decoder.rate)
            try:
                self._drain(conn)
            finally:
                with contextlib.suppress(OSError):
                    conn.close()
                with self._lock:
                    self._connected = False

    def _drain(self, conn: Any) -> None:
        conn.settimeout(0.25)
        while not self._stop.is_set():
            try:
                data = conn.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            if not data:
                return  # the device went away (deleted, Live closed, set changed): wait for the next connection
            now = time.monotonic()
            for block in self._decoder.feed(data, now):
                self._take(block, now)

    def _take(self, block: Block, now: float) -> None:
        with self._lock:
            gap = now - self._last_block if self._last_block else STALE_S
            self._last_block = now
            if gap >= STALE_S:
                self._settling_since = now  # a stream starts: what comes first is the device's backlog
            if self._settling_since:
                # While it was not asked, the device went on collecting (up to its buffer), and it sends that old
                # audio first, faster than real time. It has caught up when a block had to wait for its audio.
                caught_up = gap < STALE_S and gap >= 0.8 * block.frames / self.rate
                if not caught_up and now - self._settling_since < SETTLE_MAX_S:
                    self._stale += 1
                    return
                self._settling_since = 0.0
            elif gap < STALE_S:
                self._gaps.append(gap)
                del self._gaps[:-2000]
            self._frames += block.frames
            self._blocks += 1
            self._peaks.append((now, block.peak))
            while self._peaks and now - self._peaks[0][0] > 2 * SILENT_AFTER_S:
                self._peaks.pop(0)
            if block.peak > SILENT_PEAK:
                self._last_loud = now
        while True:
            try:
                self._queue.put_nowait(block.pcm)
                return
            except queue.Full:
                with contextlib.suppress(queue.Empty):
                    self._queue.get_nowait()
                with self._lock:
                    self._dropped += 1
