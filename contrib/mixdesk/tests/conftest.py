"""The mix desk's test rig: the server started in this process against hands.testing's FakeLive and fake MiniLab.

Everything is made up and on free ports: the history, checkpoints, surfaces and analysis live in tmp_path, the pager
sends its datagrams to a UDP port the test picked, and Live is a FakeLive served on its own TCP port. Nothing here
reaches the running desk (:8985, UDP 8986/8987), Anthony's files or the real Live.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from hands.testing import FakeLive, MiniLab_3, hw002_like  # noqa: E402

MOD = "zpkt_mixdesk_pager"

# A made-up analysis.json in the shape analyze.py writes (only what the server reads, plus a little for the page).
ANALYSIS = {
    "ref_align_s": 24.0,
    "sources": {
        sid: {"id": sid, "kind": "ref" if sid.startswith("C") else "mix", "duration_s": 60.0,
              "sections": {"drop": {"lufs": lufs}, "build": {"lufs": lufs - 3}}}
        for sid, lufs in (("A", -9.0), ("B", -10.0), ("C1", -12.0), ("C2", -11.0), ("C3", -11.5), ("C4", -13.0))
    },
}


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


@dataclass
class Rig:
    """A running desk: its base URL, the fake Live and MiniLab, and the server's Desk."""

    url: str
    live: FakeLive
    minilab: MiniLab_3
    desk: Any
    tmp: Path

    def request(self, method: str, path: str, body: Any = None, raw: bytes | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, Any]:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, payload, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            code, payload, ctype = exc.code, exc.read(), exc.headers.get("Content-Type", "")
        return code, json.loads(payload) if ctype.startswith("application/json") else payload

    def get(self, path: str, **kw: Any) -> tuple[int, Any]:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        return self.request("POST", path, body=body if body is not None else {}, **kw)

    def send(self, data: bytes | dict) -> None:
        """One datagram to the desk's UDP port, as the pager sends them."""
        out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        out.sendto(data if isinstance(data, bytes) else json.dumps(data).encode(), ("127.0.0.1", self.desk.settings.udp_port))
        out.close()

    def state(self) -> dict:
        return self.get("/api/state")[1]

    def call(self, expr: str) -> Any:
        return self.live.run(
            f"import sys\nm = sys.modules.get({MOD!r})\nresult = {expr} if m is not None and m.DESK is not None else None"
        )

    def track(self, name: str) -> Any:
        song = self.live.song
        return next(t for t in [*song.tracks, *song.return_tracks, song.master_track] if t.name == name)


def settings(tmp: Path, live_port: int | None) -> Any:
    import server

    viz = tmp / "viz"
    viz.mkdir(exist_ok=True)
    (viz / "analysis.json").write_text(json.dumps(ANALYSIS))
    (viz / "A.wav").write_bytes(b"RIFF" + bytes(range(256)) * 4)
    return server.Settings(
        set_name="HW002_121_pp_finish",
        viz_dir=viz,
        http_port=0,
        udp_port=free_port(socket.SOCK_DGRAM),
        meter_port=free_port(socket.SOCK_DGRAM),
        live_port=live_port,
        history_dir=tmp / "hist",
        checkpoints_dir=tmp / "state",
        surfaces_dir=tmp / "surfaces",
    )


@pytest.fixture()
def rig(tmp_path: Path) -> Iterator[Rig]:
    import server

    minilab = MiniLab_3()
    live = FakeLive(hw002_like(), surfaces=[minilab])
    desk = server.Desk(settings(tmp_path, live.serve()))
    http = server.start(desk, supervise=False)
    threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    desk.restart_pager()
    try:
        yield Rig(f"http://127.0.0.1:{http.server_address[1]}", live, minilab, desk, tmp_path)
    finally:
        http.shutdown()
        http.server_close()
        try:
            live.run(f"import sys\nm = sys.modules.get({MOD!r})\nif m is not None and m.DESK is not None:\n    m.DESK.stop()\nresult = 'ok'")
        finally:
            live.close()
