"""Listen: the adapter at /app/listen with a made-up capture (a generator of PCM), and the Live device's capture
against a stand-in device on free localhost ports. No Swift tool, no Live, no sound."""

from __future__ import annotations

import math
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.app.conftest import Rig, free_port, wait_for
from tests.live.test_listen import RATE as DEVICE_RATE
from tests.live.test_listen import Device, continuous
from zpkt.app.adapters import AdapterError, AppContext, discover
from zpkt.app.adapters.listen import ListenAdapter, source_from
from zpkt.app.listen import FRAME, capture, device
from zpkt.app.listen.hub import QUEUE_CHUNKS, Hub, Listener
from zpkt.live.listen import CONTROL_PORT, LISTEN_PORT, encode_message

CHUNK_FRAMES = 960  # 20 ms at 48 kHz, as the real capture gives


def tone(n: int, start: int = 0) -> bytes:
    """`n` frames of a 440 Hz tone on the left and silence on the right."""
    return b"".join(
        struct.pack("<hh", int(8000 * math.sin(2 * math.pi * 440 * (start + i) / 48000)), 0) for i in range(n)
    )


CHUNK = tone(CHUNK_FRAMES)


class FakeStream:
    """A capture that gives one 20 ms piece every few milliseconds until closed."""

    def __init__(self, chunk: bytes = CHUNK, every: float = 0.005, rate: int = 48000, source: str = "made up") -> None:
        self.chunk, self.every, self.rate, self.source = chunk, every, rate, source
        self.closed = threading.Event()

    def read(self) -> bytes:
        return b"" if self.closed.wait(self.every) else self.chunk

    def close(self) -> None:
        self.closed.set()


@dataclass
class FakeSource:
    reason: str = ""
    chunk: bytes = CHUNK
    streams: list[FakeStream] = field(default_factory=list)
    checks: int = 0
    rate: int = 48000
    name: str = "made up"

    def check(self) -> str:
        self.checks += 1
        return self.reason

    def open(self) -> FakeStream:
        if self.reason:
            raise capture.Unavailable(self.reason)
        self.streams.append(FakeStream(self.chunk, rate=self.rate, source=self.name))
        return self.streams[-1]

    @property
    def running(self) -> int:
        return sum(1 for s in self.streams if not s.closed.is_set())


@dataclass
class Listening:
    rig: Rig
    source: FakeSource
    adapter: ListenAdapter

    def status(self) -> dict[str, Any]:
        code, body = self.rig.get("/app/listen/status")
        assert code == 200
        return body

    def open(self, path: str = "/app/listen/stream.pcm") -> Any:
        return urllib.request.urlopen(self.rig.url + path, timeout=10)


@pytest.fixture()
def listening(rig: Rig) -> Iterator[Listening]:
    source = FakeSource()
    adapter = ListenAdapter(AppContext(rig.desk.bus, rig.desk, rig.desk.settings), source=source, linger=0.15)
    adapter.start()
    try:
        yield Listening(rig, source, adapter)
    finally:
        adapter.stop()


def test_the_status_says_available_the_format_and_nobody_listening(listening):
    assert listening.status() == {
        "available": True,
        "reason": "",
        "listeners": 0,
        "capturing": False,
        "source": "made up",
        "format": {"encoding": "s16le", "rate": 48000, "channels": 2},
    }
    assert listening.source.streams == []  # asking the status starts no capture


def test_the_stream_delivers_the_captures_pcm_in_whole_frames(listening):
    with listening.open() as r:
        assert r.status == 200 and r.headers["X-Audio-Format"] == "s16le;rate=48000;channels=2"
        assert r.headers["Content-Length"] is None  # it goes on until the page stops reading
        got = r.read(len(CHUNK) * 3)
    assert got == CHUNK * 3


def test_capture_starts_with_the_first_listener_and_stops_after_the_last(listening):
    src = listening.source
    assert src.running == 0
    a = listening.open()
    a.read(FRAME)
    assert src.running == 1 and listening.status()["listeners"] == 1 and listening.status()["capturing"]
    b = listening.open()
    b.read(FRAME)
    assert len(src.streams) == 1 and listening.status()["listeners"] == 2  # one capture for both
    a.close()
    assert wait_for(lambda: listening.status()["listeners"] == 1)
    assert src.running == 1
    b.close()
    assert wait_for(lambda: listening.status()["listeners"] == 0)
    assert wait_for(lambda: src.running == 0, 3)  # a little after the last one left
    assert listening.status()["capturing"] is False


def test_a_listener_who_comes_back_soon_keeps_the_same_capture(rig):
    source = FakeSource()
    hub = Hub(source, linger=5.0)
    one = hub.join()
    hub.leave(one)
    two = hub.join()  # a reload, or a move to another page
    assert len(source.streams) == 1 and source.running == 1 and two.get() == CHUNK
    hub.stop()
    assert source.running == 0 and two.get() is None


def test_when_capture_cannot_start_the_status_and_the_stream_say_why(listening):
    listening.source.reason = "The Mac has not allowed zpkt to record Live's sound."
    status = listening.status()
    assert status["available"] is False and status["reason"] == listening.source.reason and status["source"] == ""
    with pytest.raises(urllib.error.HTTPError) as err:
        listening.open()
    assert err.value.code == 503 and listening.source.reason.encode() in err.value.read()
    assert listening.status()["listeners"] == 0


def test_the_status_keeps_its_check_for_a_while(listening):
    for _ in range(5):
        listening.status()
    assert listening.source.checks == 1


def test_when_the_capture_ends_by_itself_the_stream_ends(listening):
    with listening.open() as r:
        r.read(FRAME)
        listening.source.streams[0].close()
        rest = r.read()  # to the end: the connection is closed, it does not hang
    assert len(rest) % FRAME == 0
    assert wait_for(lambda: listening.status()["listeners"] == 0)


def test_a_capture_that_is_cut_off_after_running_a_while_is_started_again():
    source = FakeSource()
    hub = Hub(source, linger=0.05, restart_after=0.0)
    listener = hub.join()
    assert listener.get() == CHUNK
    source.streams[0].close()  # macOS cut it off
    assert wait_for(lambda: len(source.streams) == 2)
    while listener.q.qsize():  # what was queued before the cut
        assert listener.get() is not None
    assert listener.get() == CHUNK and hub.starts == 2  # the same listener hears the new capture
    hub.stop()
    assert source.running == 0


def test_a_slow_listener_loses_its_oldest_sound_not_its_newest():
    slow = Listener()
    for i in range(QUEUE_CHUNKS + 5):
        slow.put(bytes([i]) * FRAME)
    assert slow.dropped == 5 and slow.get() == bytes([5]) * FRAME


def test_the_hub_hands_out_whole_frames_when_the_capture_splits_them():
    source = FakeSource(chunk=CHUNK[:-3] + CHUNK[:1])  # each read ends two bytes into a frame
    hub = Hub(source, linger=0.05)
    listener = hub.join()
    got = [listener.get(), listener.get(), listener.get()]
    hub.stop()
    assert all(piece and len(piece) % FRAME == 0 for piece in got)


def test_only_get_is_answered_and_an_unknown_path_is_404(listening):
    assert listening.rig.post("/app/listen/status")[0] == 405
    assert listening.rig.get("/app/listen/nothing")[0] == 404
    assert listening.rig.request("HEAD", "/app/listen/stream.pcm")[0] == 200
    assert listening.source.streams == []  # a HEAD starts no capture


def test_the_pages_script_is_served_from_the_mount(listening):
    code, body = listening.rig.get("/app/listen/listen.js")
    assert code == 200 and b"zpkt-listen" in body and b'getElementById("listen")' in body.replace(b"'", b'"')


def test_the_mp3_stream_is_the_same_sound_through_ffmpeg(listening):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is not installed")
    with listening.open("/app/listen/stream.mp3") as r:
        assert r.headers["Content-Type"] == "audio/mpeg"
        head = r.read(2048)
    assert head[:3] == b"ID3" or (head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    assert wait_for(lambda: listening.status()["listeners"] == 0)


# ---- the sample rate is the capture's -----------------------------------------------------------------------------


@pytest.mark.parametrize("rate", [44100, 48000])
def test_the_captures_rate_is_in_the_status_and_in_the_streams_header(listening, rate):
    listening.source.rate = rate
    assert listening.status()["format"]["rate"] == rate  # before anything runs: what the source expects to give
    with listening.open() as r:
        assert r.headers["X-Audio-Format"] == f"s16le;rate={rate};channels=2"
        r.read(FRAME)
        status = listening.status()
    assert status["capturing"] and status["format"] == {"encoding": "s16le", "rate": rate, "channels": 2}


@pytest.mark.parametrize("rate", [44100, 48000])
def test_the_mp3_stream_tells_ffmpeg_the_captures_rate(rig, tmp_path, monkeypatch, rate):
    said = tmp_path / "ffmpeg-said"
    tool = tmp_path / "ffmpeg"  # a stand-in that writes down what it was asked and passes the sound through
    tool.write_text(f'#!/bin/sh\necho "$@" > {said}\nexec cat\n')
    tool.chmod(0o755)
    monkeypatch.setattr("zpkt.app.listen.routes.shutil.which", lambda name: str(tool))
    source = FakeSource(rate=rate)
    adapter = ListenAdapter(AppContext(rig.desk.bus, rig.desk, rig.desk.settings), source=source, linger=0.05)
    adapter.start()
    try:
        with urllib.request.urlopen(rig.url + "/app/listen/stream.mp3", timeout=10) as r:
            assert r.read(FRAME)
        asked = said.read_text().split()
    finally:
        adapter.stop()
    assert asked[asked.index("-ar") + 1] == str(rate) and asked[asked.index("-f") + 1] == "s16le"


def test_a_capture_that_comes_back_at_another_rate_ends_its_listeners():
    source = FakeSource(rate=44100)
    hub = Hub(source, linger=0.05, restart_after=0.0)
    old = hub.join()
    assert old.rate == 44100 and old.get() == CHUNK
    source.rate = 48000  # the device left; the screen capture takes over
    source.streams[0].close()
    assert wait_for(lambda: len(source.streams) == 2)
    while (piece := old.get()) is not None:  # what was queued before the cut, then the end
        assert piece
    assert hub.status()["listeners"] == 0 and hub.status()["format"]["rate"] == 48000
    new = hub.join()  # the page connects again and is told the new rate
    assert new.rate == 48000 and new.get() == CHUNK and len(source.streams) == 2
    hub.leave(new)
    assert wait_for(lambda: source.running == 0, 3)  # and the capture still stops when nobody listens
    hub.stop()


# ---- the Live device's capture, against a stand-in device ---------------------------------------------------------


@dataclass
class OnMain:
    """The stand-in for "zpkt listen" on Main (tests/live), and the capture that reads it, on free ports."""

    device: Device
    capture: device.DeviceCapture
    port: int


@pytest.fixture()
def on_main() -> Iterator[OnMain]:
    port = free_port()
    assert port not in (LISTEN_PORT, CONTROL_PORT)
    stand_in = Device(port)
    assert stand_in.control_port not in (LISTEN_PORT, CONTROL_PORT)
    try:
        yield OnMain(stand_in, device.DeviceCapture(port, stand_in.control_port, gone_after=0.6), port)
    finally:
        stand_in.close()


def nobody_on_main(**more: Any) -> device.DeviceCapture:
    """A capture whose device is not there: nothing hears its control messages and nothing connects."""
    return device.DeviceCapture(free_port(), free_port(socket.SOCK_DGRAM), connect_wait=0.2, **more)


def read_bytes(stream: Any, n: int) -> bytes:
    pcm = b""
    while len(pcm) < n:
        piece = stream.read()
        assert piece, "the capture ended"
        pcm += piece
    return pcm


def test_the_device_capture_reads_lives_sound_at_lives_rate_and_stops_the_device(on_main):
    stream = on_main.capture.open()
    try:
        assert stream.rate == DEVICE_RATE == 44100 and stream.source == "live device"
        pcm = read_bytes(stream, 2048 * FRAME)
        assert len(pcm) % FRAME == 0 and continuous(pcm)
    finally:
        stream.close()
    assert wait_for(lambda: on_main.device.heard[-1] == 0 and not on_main.device.on, 2)  # "/listen 0"
    again = on_main.capture.open()  # the ports are free: the next capture binds them again
    try:
        assert read_bytes(again, FRAME)
    finally:
        again.close()


def test_the_device_captures_check_leaves_nothing_running(on_main):
    assert on_main.capture.check() == "" and on_main.capture.rate == 44100
    assert wait_for(lambda: on_main.device.heard[-1] == 0, 2)
    free = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # past the closed connection's wait, not past a
    free.bind(("127.0.0.1", on_main.port))  # socket that still listens there: that would be "address in use"
    free.close()


def test_with_no_device_on_main_the_capture_says_the_fix_and_frees_the_port():
    source = nobody_on_main()
    began = time.monotonic()
    with pytest.raises(capture.Unavailable) as err:
        source.open()
    assert time.monotonic() - began < 2.0
    text = str(err.value)
    assert '"zpkt listen" device on Main' in text and "contrib/mixdesk/listen.py install" in text
    assert "audio output device" in text and "clock stands still" in text
    assert source.check() == device.NO_DEVICE  # and it could bind again to find that out


def test_a_port_somebody_else_holds_is_said_in_plain_words():
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 0))
    held.listen(1)
    try:
        source = device.DeviceCapture(held.getsockname()[1], free_port(socket.SOCK_DGRAM), connect_wait=0.2)
        assert "already reading Live's sound" in source.check()
    finally:
        held.close()


def test_the_device_stream_waits_out_a_quiet_moment_and_ends_when_the_device_is_gone(on_main):
    stream = on_main.capture.open()
    try:
        read_bytes(stream, FRAME)
        on_main.device.mute = True  # connected and sending nothing, as when Live's audio stops
        got: list[bytes] = []
        reader = threading.Thread(target=lambda: got.append(stream.read()), daemon=True)
        time.sleep(0.3)
        while stream.reader.read(0.0):  # what was already on its way
            pass
        reader.start()
        reader.join(timeout=1.0)
        assert reader.is_alive()  # a read waits; it does not say the capture ended
        on_main.device.mute = False
        reader.join(timeout=5.0)
        assert got and got[0]
        on_main.device.done.set()  # Live closes
        on_main.device.thread.join(timeout=2.0)
        on_main.device.drop()
        began = time.monotonic()
        while stream.read():
            assert time.monotonic() - began < 5.0
        assert time.monotonic() - began >= 0.5  # gone for a while, not just a hiccup
    finally:
        stream.close()


def test_the_device_stream_ends_when_live_changes_its_sample_rate(on_main):
    stream = on_main.capture.open()
    try:
        read_bytes(stream, FRAME)
        on_main.device.send(encode_message("sr", 48000.0))
        began = time.monotonic()
        while stream.read():
            assert time.monotonic() - began < 3.0
    finally:
        stream.close()


# ---- the chain: the device first, then the screen capture ---------------------------------------------------------


def test_the_chain_takes_the_device_when_it_is_on_main(on_main):
    screen = FakeSource(name="screen capture")
    chain = capture.Chain([on_main.capture, screen])
    assert chain.check() == "" and chain.name == "live device" and chain.rate == 44100
    stream = chain.open()
    try:
        assert stream.source == "live device" and stream.rate == 44100 and screen.streams == []
    finally:
        stream.close()


def test_the_chain_falls_back_to_the_screen_capture():
    screen = FakeSource(name="screen capture")
    chain = capture.Chain([nobody_on_main(), screen])
    assert chain.check() == "" and chain.name == "screen capture" and chain.rate == 48000
    stream = chain.open()
    assert stream.rate == 48000 and len(screen.streams) == 1
    stream.close()


def test_when_neither_can_capture_the_reason_names_both_fixes():
    screen = FakeSource(reason=capture.PERMISSION.format(app="Terminal"), name="screen capture")
    chain = capture.Chain([nobody_on_main(), screen])
    reason = chain.check()
    assert chain.name == ""
    for words in ('"zpkt listen" device on Main', "listen.py install", "audio output device", "Screen & System Audio"):
        assert words in reason
    with pytest.raises(capture.Unavailable) as err:
        chain.open()
    assert str(err.value) == reason
    status = Hub(chain).status()
    assert status["available"] is False and status["source"] == "" and status["reason"] == reason


def test_the_device_is_heard_end_to_end_at_44100_and_the_fallback_at_48000(rig, on_main):
    screen = FakeSource(name="screen capture")
    for first, source, rate in ((on_main.capture, "live device", 44100), (nobody_on_main(), "screen capture", 48000)):
        chain = capture.Chain([first, screen])
        adapter = ListenAdapter(AppContext(rig.desk.bus, rig.desk, rig.desk.settings), source=chain, linger=0.05)
        adapter.start()
        try:
            status = rig.get("/app/listen/status")[1]
            assert status["available"] and status["source"] == source and status["format"]["rate"] == rate
            with urllib.request.urlopen(rig.url + "/app/listen/stream.pcm", timeout=10) as r:
                assert r.headers["X-Audio-Format"] == f"s16le;rate={rate};channels=2"
                pcm = r.read(1024 * FRAME)
                status = rig.get("/app/listen/status")[1]
            assert status["capturing"] and status["source"] == source and status["format"]["rate"] == rate
            assert continuous(pcm) if source == "live device" else pcm == (CHUNK * 2)[: 1024 * FRAME]
        finally:
            adapter.stop()
    assert wait_for(lambda: on_main.device.heard[-1] == 0, 2)  # stopping the adapter stopped the device


def test_the_environment_chooses_the_source():
    auto = source_from({})
    assert isinstance(auto, capture.Chain)
    assert [type(s) for s in auto.sources] == [device.DeviceCapture, capture.SwiftCapture]
    assert isinstance(source_from({"ZPKT_LISTEN_SOURCE": "auto"}), capture.Chain)
    only = source_from({"ZPKT_LISTEN_SOURCE": "device"})
    assert isinstance(only, device.DeviceCapture) and (only.port, only.control_port) == (LISTEN_PORT, CONTROL_PORT)
    assert isinstance(source_from({"ZPKT_LISTEN_SOURCE": "Screen"}), capture.SwiftCapture)
    with pytest.raises(AdapterError, match="it can be auto, device, screen"):
        source_from({"ZPKT_LISTEN_SOURCE": "loopback"})


# ---- the adapter and the real source, without running it ---------------------------------------------------------


def test_listen_is_an_adapter_and_is_started_by_default():
    from zpkt.app import parse_args

    assert "listen" in discover()
    assert "listen" in parse_args([]).adapters.split(",")


def test_starting_the_adapter_only_mounts_it(rig, tmp_path):
    def which(name: str) -> None:
        raise AssertionError("the adapter looked for a compiler at start")

    source = capture.SwiftCapture(folder=tmp_path / "cache", which=which)
    adapter = ListenAdapter(AppContext(rig.desk.bus, rig.desk, rig.desk.settings), source=source)
    adapter.start()
    try:
        assert "/app/listen" in rig.desk.mounts.prefixes() and not (tmp_path / "cache").exists()
    finally:
        adapter.stop()
    assert "/app/listen" not in rig.desk.mounts.prefixes()


def test_off_a_mac_listen_is_unavailable_in_plain_words(tmp_path):
    source = capture.SwiftCapture(folder=tmp_path, platform="linux")
    assert source.check() == capture.NOT_A_MAC
    with pytest.raises(capture.Unavailable, match="not a Mac"):
        source.open()


def test_without_a_swift_compiler_listen_says_so(tmp_path):
    source = capture.SwiftCapture(folder=tmp_path / "cache", platform="darwin", which=lambda name: None)
    assert source.check() == capture.NO_SWIFT
    assert Hub(source).status()["available"] is False


def test_the_tools_exit_codes_become_plain_reasons(tmp_path):
    source = capture.SwiftCapture(folder=tmp_path)
    assert "Screen & System Audio Recording" in source._reason(capture.EXIT_PERMISSION, "permission needed")
    assert source._reason(capture.EXIT_NO_APP, "") == capture.NOT_RUNNING
    assert source._reason(70, "failed: no display\n").endswith("failed: no display")


def test_the_tool_is_source_in_the_repo_never_a_binary():
    assert capture.SOURCE.name == "capture.swift" and capture.SOURCE.is_file()
    assert "ScreenCaptureKit" in capture.SOURCE.read_text()
    assert [p.name for p in capture.SOURCE.parent.iterdir() if p.name.startswith("zpkt-listen-capture")] == []


def test_the_cache_folder_is_under_the_rigs_data_or_named(tmp_path):
    assert capture.cache_dir({}) == tmp_path / "data" / "cache" / "listen"
    assert capture.cache_dir({"ZPKT_LISTEN_DIR": str(tmp_path / "x")}) == tmp_path / "x"
