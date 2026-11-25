"""The app's test rig: the app started in this process on FakeLive, a fake meter and free ports.

Live is a FakeLive handed straight to the app's connections (no TCP port), the MiniLab is zpkt.live.testing's fake, the
meter is a queue of made-up datagrams, and every file lives in tmp_path. Nothing here reaches the running desk
(:8985-8987), Anthony's files, a MiniLab or the real Live.
"""

from __future__ import annotations

import json
import queue
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from zpkt.app import desk as desk_module
from zpkt.app import web
from zpkt.app.connections import LiveConnections
from zpkt.live import config, desk_pager
from zpkt.live.testing import FakeLive, MiniLab_3, hw002_like


def made_up_analysis() -> dict:
    """An analysis.json in the shape analyze.py writes (every key the page draws), with made-up numbers."""
    centers = [round(20.0 * 2 ** (k / 6), 2) for k in range(61)]

    def section(a: float, b: float, lufs: float) -> dict:
        return {
            "from_s": a,
            "to_s": b,
            "lufs": lufs,
            "spec": [-30.0 - k * 0.3 for k in range(61)],
            "side_spec": [-40.0 - k * 0.3 for k in range(61)],
            "peak_db": -0.5,
            "crest_db": 9.0,
            "width_db": -12.0,
            "bass_corr": 0.98,
        }

    sources = {}
    for sid, label, lufs in (
        ("A", "Original", -9.0),
        ("B", "Recipe", -10.0),
        ("C1", "KSMS", -12.0),
        ("C2", "BSLS", -11.0),
        ("C3", "Hedon", -11.5),
        ("C4", "Patriotic", -13.0),
    ):
        ref = sid.startswith("C")
        dur = 30.0 if ref else 60.0
        secs = (
            {"drop": section(0.0, dur, lufs)}
            if ref
            else {"build": section(0.0, 24.0, lufs - 3), "drop": section(24.0, dur, lufs)}
        )
        ts = [t + 1.5 for t in range(int(dur) - 1)]
        sources[sid] = {
            "duration_s": dur,
            "sr": 44100,
            "sections": secs,
            "timeline": {
                "t": ts,
                "lufs": [lufs] * len(ts),
                "crest": [9.0] * len(ts),
                "width": [-12.0] * len(ts),
                "bass_corr": [0.98] * len(ts),
            },
            "bands": {k: [-6.0] * len(ts) for k in ("low", "mid", "high")},
            "env": [0.3] * int(dur * 20),
            "peak_db": -0.5,
            "id": sid,
            "label": label,
            "what": label,
            "kind": "ref" if ref else "mix",
            "file": f"/made/up/{sid}.flac",
            "wav": f"/media/{sid}.wav",
        }
    return {"build_end_s": 24.0, "ref_align_s": 24.0, "centers": centers, "sources": sources}


ANALYSIS = made_up_analysis()


@pytest.fixture(autouse=True)
def throwaway_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test gets its own folders and a Live port nothing listens on (the discard port), so a test that forgets
    its fake gets "Cannot reach Ableton" and never the real Live."""
    for key in ("sets", "data", "renders", "prefs"):
        (tmp_path / key).mkdir()
    monkeypatch.setenv("ZPKT_RIG_CONFIG", str(tmp_path / "no-rig.toml"))
    monkeypatch.setenv("ZPKT_SETS_DIR", str(tmp_path / "sets"))
    monkeypatch.setenv("ZPKT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ZPKT_RENDERS_DIR", str(tmp_path / "renders"))
    monkeypatch.setenv("ZPKT_LIVE_PREFS_DIR", str(tmp_path / "prefs"))
    monkeypatch.setenv("ZPKT_LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setenv("ZPKT_LIVE_PORT", "9")
    config.rig.cache_clear()
    yield
    config.rig.cache_clear()


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    s = socket.socket(socket.AF_INET, kind)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(check: Callable[[], Any], seconds: float = 3.0) -> Any:
    end = time.time() + seconds
    while time.time() < end:
        got = check()
        if got:
            return got
        time.sleep(0.01)
    return check()


class FakeMeter:
    """The meter's socket: `send` queues a datagram, `recvfrom` hands it over (blocking like a socket)."""

    def __init__(self) -> None:
        self.q: queue.Queue[bytes] = queue.Queue()
        self.closed = False

    def send(self, data: bytes) -> None:
        self.q.put(data)

    def recvfrom(self, size: int, /) -> tuple[bytes, Any]:
        while not self.closed:
            try:
                return self.q.get(timeout=0.05), ("127.0.0.1", 0)
            except queue.Empty:
                continue
        raise OSError("closed")

    def fileno(self) -> int:
        return -1 if self.closed else 0

    def close(self) -> None:
        self.closed = True


def osc_spec(levels: list[float]) -> bytes:
    """An OSC "/spec f f ..." datagram, as the Max for Live meter sends it."""
    import struct

    tags = ("," + "f" * len(levels)).encode() + b"\x00"
    tags += b"\x00" * (-len(tags) % 4)
    return b"/spec\x00\x00\x00" + tags + b"".join(struct.pack(">f", v) for v in levels)


@dataclass
class Rig:
    """A running app: its base URL, the fake Live and MiniLab, the Desk and the meter."""

    url: str
    live: FakeLive
    minilab: MiniLab_3
    desk: Any
    tmp: Path
    meter: FakeMeter
    conn: LiveConnections

    def request(self, method: str, path: str, body: Any = None, raw: bytes | None = None) -> tuple[int, Any]:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.url + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, payload, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            code, payload, ctype = exc.code, exc.read(), exc.headers.get("Content-Type", "")
        return code, json.loads(payload) if ctype.startswith("application/json") else payload

    def get(self, path: str) -> tuple[int, Any]:
        return self.request("GET", path)

    def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        return self.request("POST", path, body=body if body is not None else {})

    def command(self, kind: str, args: dict | None = None, **extra: Any) -> tuple[int, Any]:
        return self.post("/api/command", {"kind": kind, "args": args or {}, **extra})

    def send(self, data: bytes | dict) -> None:
        """One datagram to the app's UDP port, as the pager sends them."""
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out.sendto(
            data if isinstance(data, bytes) else json.dumps(data).encode(), ("127.0.0.1", self.desk.settings.udp_port)
        )
        out.close()

    def state(self) -> dict:
        return self.get("/api/state")[1]

    def track(self, name: str) -> Any:
        song = self.live.song
        return next(t for t in [*song.tracks, *song.return_tracks, song.master_track] if t.name == name)


def make_settings(tmp: Path) -> Any:
    viz = tmp / "viz"
    viz.mkdir(exist_ok=True)
    (viz / "analysis.json").write_text(json.dumps(ANALYSIS))
    (viz / "A.wav").write_bytes(b"RIFF" + bytes(range(256)) * 4)
    return desk_module.Settings(
        set_name="HW002_121_pp_finish",
        viz_dir=viz,
        http_port=0,
        udp_port=free_port(socket.SOCK_DGRAM),
        meter_port=free_port(socket.SOCK_DGRAM),
        live_port=None,
        history_dir=tmp / "hist",
        checkpoints_dir=tmp / "state",
        surfaces_dir=tmp / "surfaces",
        changes_file=tmp / "changes" / "set.jsonl",
    )


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    minilab = MiniLab_3()
    live = FakeLive(hw002_like(), surfaces=[minilab])
    meter = FakeMeter()
    conn = LiveConnections(live, meter)
    desk = desk_module.Desk(make_settings(tmp_path), connections=conn)
    http = web.start(desk, supervise=False)
    web.serve_in_thread(http)
    desk.restart_pager()
    try:
        yield Rig(f"http://127.0.0.1:{http.server_address[1]}", live, minilab, desk, tmp_path, meter, conn)
    finally:
        http.shutdown()
        http.server_close()
        meter.close()
        try:
            live.run(
                f"import sys\nm = sys.modules.get({desk_pager.MODULE!r})\n"
                "if m is not None and m.DESK is not None:\n    m.DESK.stop()\nresult = 'ok'"
            )
        finally:
            live.close()
