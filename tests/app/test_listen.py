"""Listen: the adapter at /app/listen with a made-up capture (a generator of PCM). No Swift tool, no Live, no sound."""

from __future__ import annotations

import math
import struct
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from tests.app.conftest import Rig, wait_for
from zpkt.app.adapters import AppContext, discover
from zpkt.app.adapters.listen import ListenAdapter
from zpkt.app.listen import FRAME, capture
from zpkt.app.listen.hub import QUEUE_CHUNKS, Hub, Listener

CHUNK_FRAMES = 960  # 20 ms at 48 kHz, as the real capture gives


def tone(n: int, start: int = 0) -> bytes:
    """`n` frames of a 440 Hz tone on the left and silence on the right."""
    return b"".join(
        struct.pack("<hh", int(8000 * math.sin(2 * math.pi * 440 * (start + i) / 48000)), 0) for i in range(n)
    )


CHUNK = tone(CHUNK_FRAMES)


class FakeStream:
    """A capture that gives one 20 ms piece every few milliseconds until closed."""

    def __init__(self, chunk: bytes = CHUNK, every: float = 0.005) -> None:
        self.chunk, self.every = chunk, every
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

    def check(self) -> str:
        self.checks += 1
        return self.reason

    def open(self) -> FakeStream:
        if self.reason:
            raise capture.Unavailable(self.reason)
        self.streams.append(FakeStream(self.chunk))
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
    assert status["available"] is False and status["reason"] == listening.source.reason
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
