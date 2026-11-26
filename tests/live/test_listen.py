"""zpkt.live.listen with no Live: the decoder against a real capture and a synthesised stream, and the source against
a stand-in device on free localhost ports."""

from __future__ import annotations

import itertools
import math
import socket
import struct
import threading
import time
from array import array
from pathlib import Path

from zpkt.live.listen import (
    Decoder,
    ListenSource,
    control_message,
    decode_message,
    encode_matrix,
    encode_message,
    float_to_s16le,
)

CAPTURE = Path(__file__).parent / "data" / "listen-capture.bin"  # from Live 12 on the rig: "sr 44100." and one block
RATE = 44100


def sine(frames: int, start: int = 0, hz: float = 441.0, rate: int = RATE) -> list[float]:
    """Interleaved stereo: a sine on the left, the same at half level and inverted on the right."""
    out = []
    for n in range(start, start + frames):
        v = 0.5 * math.sin(2 * math.pi * hz * n / rate)
        out += [v, -0.5 * v]
    return out


def s16(pcm: bytes) -> array:
    a = array("h")
    a.frombytes(pcm)
    return a


def test_a_real_capture_decodes_to_the_rate_and_one_click():
    decoder = Decoder()
    blocks = decoder.feed(CAPTURE.read_bytes(), at=1.0)
    assert decoder.rate == 44100
    assert [(b.frames, b.peak, b.at) for b in blocks] == [(512, 1.0, 1.0)]
    samples = s16(blocks[0].pcm)
    assert len(samples) == 1024 and samples[0] == 32767 and not any(samples[1:])  # one full-scale sample, on the left


def test_the_encoder_writes_what_live_sent():
    """The stand-in used by the tests below is byte for byte the real thing (but for the header's time stamp)."""
    real = CAPTURE.read_bytes()
    click = [0.0] * 1024
    click[0] = 1.0
    made = encode_message("sr", 44100.0) + encode_matrix(click)
    time_at = 29 + 8 + 280  # the message, the chunk header, the matrix header up to its time stamp
    assert len(made) == len(real)
    assert made[:time_at] == real[:time_at] and made[time_at + 8 :] == real[time_at + 8 :]


def test_the_control_message_is_osc():
    assert control_message(True) == b"/listen\x00,i\x00\x00\x00\x00\x00\x01"
    assert control_message(False) == b"/listen\x00,i\x00\x00\x00\x00\x00\x00"


def test_a_sine_round_trips_sample_for_sample_however_the_bytes_are_cut():
    wave = sine(2048)
    stream = encode_message("sr", 48000.0) + b"".join(encode_matrix(wave[i : i + 1024]) for i in range(0, 4096, 1024))
    expected, peak = float_to_s16le(array("f", wave))
    for cut in (1, 7, 300, 4096, len(stream)):
        decoder = Decoder()
        blocks = [b for i in range(0, len(stream), cut) for b in decoder.feed(stream[i : i + cut])]
        assert decoder.rate == 48000
        assert [b.frames for b in blocks] == [512] * 4
        assert b"".join(b.pcm for b in blocks) == expected
        assert max(b.peak for b in blocks) == peak
    got = s16(expected)
    assert max(abs(got[2 * n] - round(32767 * 0.5 * math.sin(2 * math.pi * 441 * n / RATE))) for n in range(2048)) <= 1
    assert max(abs(got[2 * n + 1] + got[2 * n] / 2) for n in range(2048)) <= 1  # right is left, halved and inverted


def test_samples_are_clipped_and_one_plane_goes_to_both_sides():
    pcm, peak = float_to_s16le(array("f", [2.0, -2.0, 1.0, -1.0, 0.0, float("nan")]))
    assert list(s16(pcm)) == [32767, -32768, 32767, -32768, 0, 0] and peak == 2.0
    mono = Decoder().feed(encode_matrix([0.25, -0.5], planes=1))
    assert list(s16(mono[0].pcm)) == [8192, 8192, -16384, -16384] and mono[0].frames == 2


def test_the_decoder_finds_its_place_again_after_rubbish_or_a_cut_stream():
    a, b = encode_matrix(sine(64)), encode_matrix(sine(64, 64))
    decoder = Decoder()
    # The tail of an older matrix (jit.net.send flushes what it had left into a new connection), then good chunks.
    blocks = decoder.feed(a[100:] + b"\x00\x01garbage" + a + encode_message("sr", 44100.0) + b)
    assert [x.frames for x in blocks] == [64, 64] and decoder.rate == 44100
    assert b"".join(x.pcm for x in blocks) == float_to_s16le(array("f", sine(128)))[0]
    # A chunk that says it is absurdly large is skipped, not waited for.
    huge = b"JMTX" + struct.pack("<i", 288) + a[8 : 8 + 276] + struct.pack(">i", 1 << 30) + a[8 + 280 :]
    assert [x.frames for x in Decoder().feed(huge + b)] == [64]
    assert Decoder().feed(b"") == [] and Decoder().feed(b"JMT") == []


def test_messages_that_are_not_the_rate_are_ignored():
    decoder = Decoder()
    decoder.feed(encode_message("hello", 1, "x") + encode_message("sr", -5.0) + encode_message("sr"))
    assert decoder.rate == 0
    assert decode_message(encode_message("sr", 96000.0)[8:]) == ["sr", 96000.0]
    assert decode_message(b"\x00" * 8 + b"sbroken") == []


# ---- the source, against a stand-in device -------------------------------------------------------------------------
class Device:
    """What "zpkt listen" does, as far as the reader can tell: hears /listen on UDP, connects, sends while asked."""

    def __init__(self, tcp_port: int) -> None:
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", 0))
        self.udp.settimeout(0.01)
        self.control_port = self.udp.getsockname()[1]
        self.tcp_port = tcp_port
        self.on = False
        self.heard: list[int] = []
        self.sent = 0  # frames
        self.mute = False  # asked, connected, and sending nothing (a stalled device)
        self.conn: socket.socket | None = None
        self.done = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while not self.done.is_set():
            try:
                data, _ = self.udp.recvfrom(64)
                value = struct.unpack(">i", data[-4:])[0]
                self.heard.append(value)
                self.on = bool(value)
                if self.on and self.conn is None:
                    self.conn = socket.create_connection(("127.0.0.1", self.tcp_port), timeout=1.0)
                if self.on and self.conn is not None:
                    self.send(encode_message("sr", float(RATE)))
            except TimeoutError:
                pass
            except OSError:
                self.conn = None
            if self.on and self.conn is not None and not self.mute:
                self.send(encode_matrix(sine(64, self.sent)))
                self.sent += 64

    def send(self, data: bytes) -> None:
        try:
            assert self.conn is not None
            self.conn.sendall(data)
        except OSError:
            self.conn = None

    def drop(self) -> None:
        """Lose the connection, as when the device is deleted or Live closes."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def close(self) -> None:
        self.done.set()
        self.thread.join(timeout=2.0)
        self.drop()
        self.udp.close()


def make_source() -> tuple[ListenSource, Device]:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    device = Device(server.getsockname()[1])
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return ListenSource(server, control, ("127.0.0.1", device.control_port)), device


def read_frames(source: ListenSource, frames: int, within: float = 5.0) -> bytes:
    pcm = b""
    end = time.monotonic() + within
    while len(pcm) < frames * 4 and time.monotonic() < end:
        pcm += source.read(0.2)
    return pcm


def continuous(pcm: bytes) -> bool:
    """Whether the left channel is the stand-in's sine with no sample missing: each step is a sine's step."""
    left = s16(pcm)[0::2]
    limit = 32767 * 0.5 * 2 * math.pi * 441 / RATE * 1.05 + 2
    return all(abs(b - a) <= limit for a, b in itertools.pairwise(left))


def test_the_source_starts_the_device_reads_its_audio_and_stops_it():
    source, device = make_source()
    try:
        assert source.status().state == "stopped"
        source.start()
        pcm = read_frames(source, 4096)
        status = source.status()
        assert len(pcm) >= 4096 * 4 and len(pcm) % 4 == 0 and continuous(pcm)
        assert status.state == "receiving" and status.connected and status.rate == RATE and status.rate_known
        assert status.frames >= 4096 and status.reconnects == 1 and 0.4 < status.peak <= 0.5
        assert device.heard[:2] == [0, 1]  # off first, so a device left on by a dead reader starts clean
    finally:
        source.stop()
        time.sleep(0.1)
        device.close()
    assert device.heard[-1] == 0 and not device.on
    assert source.status().state == "stopped"


def test_read_never_blocks_for_ever_and_says_no_device_when_nothing_connects():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    nobody = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    nobody.bind(("127.0.0.1", 0))
    source = ListenSource(server, control, nobody.getsockname())
    source.start()
    try:
        began = time.monotonic()
        assert source.read(0.2) == b""
        assert 0.15 < time.monotonic() - began < 1.0
        status = source.status()
        assert status.state == "no device" and not status.connected and not status.rate_known
        assert status.rate == 48000  # the stated default until a device says otherwise
        assert next(iter(source)) == b""  # the iterator also yields an empty chunk rather than waiting for ever
    finally:
        source.stop()
        nobody.close()


def test_the_source_survives_a_gap_and_a_lost_connection():
    source, device = make_source()
    try:
        source.start()
        assert continuous(read_frames(source, 2048))
        device.drop()  # the device goes away: the next "/listen 1" (within a second) makes it connect again
        time.sleep(0.3)
        while source.read(0.05):
            pass
        assert source.status().state == "no device"
        pcm = read_frames(source, 2048)
        assert len(pcm) >= 2048 * 4 and continuous(pcm)
        status = source.status()
        assert status.state == "receiving" and status.reconnects == 2
    finally:
        source.stop()
        device.close()


def test_silence_is_reported_as_silent_and_unread_audio_is_dropped_oldest_first():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    source = ListenSource(server, control, ("127.0.0.1", 9), max_queued=4)
    source.start()
    conn = socket.create_connection(server.getsockname())
    try:
        for k in range(40):  # 40 blocks of 64 silent frames, 2 ms apart: the first is taken as backlog
            conn.sendall(encode_matrix([0.0] * 128))
            time.sleep(0.002)
            if k == 0:
                time.sleep(0.01)
        time.sleep(0.2)
        status = source.status()
        assert status.state == "silent" and status.peak == 0.0
        assert status.blocks + status.stale == 40 and status.stale >= 1
        assert status.dropped == status.blocks - 4  # the queue kept the newest four
        assert status.interval_ms > 0 and status.jitter_ms >= 0 and status.max_gap_ms >= status.interval_ms
        assert source.read(0.1) == bytes(256)
    finally:
        conn.close()
        source.stop()
