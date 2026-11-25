"""The Song: the arranger mounted at /app/song, the recipe's two halves, the writes as commands and the build in Live.

The mounted routes are compared with the old arranger server on :8975's code (started in-process on a free port on a copy
of the same data), so what the arranger did, the Song does. Live is FakeLive. Nothing here reaches the real arranger,
its data or Live.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.app.conftest import Rig
from tests.app.song_data import samples, write_song_data
from zpkt.app import song
from zpkt.app.adapters import AppContext
from zpkt.app.adapters.song import SongAdapter
from zpkt.app.bus import Command

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
MIX_SET = "HW002_121_pp_mix"


@dataclass
class SongRig:
    rig: Rig
    data: Path
    worker_starts: list[int]
    adapter: SongAdapter

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, str], bytes]:
        return ask(self.rig.url + song.PREFIX, method, path, body)


def ask(base: str, method: str, path: str, body: Any = None) -> tuple[int, dict[str, str], bytes]:
    """(status, headers, body bytes) of one request."""
    raw = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=raw, method=method)
    try:
        with OPENER.open(req, timeout=20) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


@pytest.fixture
def song_rig(rig: Rig, tmp_path: Path) -> Iterator[SongRig]:
    data = write_song_data(tmp_path / "arranger")
    starts: list[int] = []
    settings = song.SongSettings(
        data, MIX_SET, 160.0, "short-8d2a2", start_worker=lambda: starts.append(1), worker_running=lambda: False
    )
    adapter = SongAdapter(AppContext(rig.desk.bus, rig.desk, rig.desk.settings), settings)
    adapter.start()
    try:
        yield SongRig(rig, data, starts, adapter)
    finally:
        adapter.stop()


@pytest.fixture
def old_arranger(tmp_path: Path, song_rig: SongRig) -> Iterator[tuple[str, Path, list[int]]]:
    """The old arranger server, in-process, on a copy of the data: (its url, its data folder, its worker starts)."""
    data = tmp_path / "old-arranger"
    shutil.copytree(song_rig.data, data)
    starts: list[int] = []
    code = song.load_arranger()
    httpd = code.server.make_server(data, port=0, start_worker=lambda: starts.append(1), worker_running=lambda: False)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", data, starts
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---- the same routes, the same answers -------------------------------------------------------------------------------


def settle(body: bytes) -> Any:
    """A body with the values that come from the clock replaced, so two runs compare."""
    text = body.decode(errors="replace")
    text = re.sub(r'"(saved|made)": [0-9.e+-]+', r'"\1": 0', text)
    text = re.sub(r"b\d{4}-\d{6}", "b-time", text)
    return text


PAGES = ["/", "/index.html", "/transitions", "/transitions/", "/mix", "/mix/", "/mix2", "/mix2/", "/spectral", "/kick/"]
READS = [
    "/api/arrangements",
    "/api/arrangements/short-8d2a2",
    "/api/arrangements/nope",
    "/api/arrangements/Bad_Id",
    "/api/transitions",
    "/api/mix2/requests",
    "/api/mix2/queue",
    "/loops.json",
    "/fx.json",
    "/refs/refs.json",
    "/audio/0000000000000001.flac",
    "/audio/not-a-hash.flac",
    "/nothing/here",
]
PAGE_SAVE = {"name": "Mine", "bars": 40, "regions": [{"lane": "kick", "clip": "kick-rumble-a", "start": 16, "len": 4}]}
WRITES = [
    ("PUT", "/api/arrangements/short-8d2a2", PAGE_SAVE),
    ("PUT", "/api/arrangements/new-one", PAGE_SAVE),
    ("PUT", "/api/arrangements/short-8d2a2", {"name": "no regions"}),
    ("PUT", "/api/arrangements/short-8d2a2", b"not json"),
    ("PUT", "/api/arrangements/Bad_Id", PAGE_SAVE),
    ("PUT", "/api/arrangements/short-8d2a2/transitions", [{"id": "x", "seam": 17}]),
    ("PUT", "/api/arrangements/short-8d2a2/transitions", [{"id": "x"}]),
    ("PUT", "/api/arrangements/short-8d2a2/mix", {"channels": {"kick": {"gainDb": -2}}}),
    ("PUT", "/api/arrangements/short-8d2a2/mix2", [{"device": "Saturator", "target": "bus-kick", "values": {}}]),
    ("PUT", "/api/arrangements/short-8d2a2/spectral", [{"id": "a", "parts": []}]),
    ("PUT", "/api/arrangements/short-8d2a2/kickFuzz", {"loop": "solo-mf1.flac", "kickTurnedDb": 1.0}),
    ("PUT", "/api/arrangements/short-8d2a2/kickFuzz", None),
    ("PUT", "/api/arrangements/short-8d2a2/mix", "not an object"),
    ("PUT", "/api/arrangements/missing/mix", {"channels": {}}),
    ("PUT", "/api/transitions", {"picks": {"a": 1}}),
    ("PUT", "/api/transitions", {"no": "picks"}),
    ("POST", "/api/mix2/requests", {"target": "kick", "device": "Saturator", "params": ["Drive"], "bars": [1, 8]}),
    ("POST", "/api/mix2/requests", {"target": "kick"}),
    ("POST", "/api/mix2/requests", None),
    ("POST", "/api/elsewhere", {}),
    ("PUT", "/elsewhere", {}),
    ("DELETE", "/api/arrangements/other", None),
    ("DELETE", "/elsewhere", None),
]


def test_every_page_and_read_answers_as_the_arranger_does(song_rig, old_arranger):
    old_url, _, _ = old_arranger
    for path in [*PAGES, *READS]:
        new = song_rig.call("GET", path)
        old = ask(old_url, "GET", path)
        assert new[0] == old[0], path
        assert new[1].get("Content-Type") == old[1].get("Content-Type"), path
        assert new[1].get("Cache-Control") == old[1].get("Cache-Control"), path
        want = song.mount_html(old[2].decode()).encode() if old[1]["Content-Type"].startswith("text/html") else old[2]
        assert settle(new[2]) == settle(want), path


def test_every_write_answers_as_the_arranger_does_and_leaves_the_same_files(song_rig, old_arranger):
    old_url, old_data, old_starts = old_arranger
    for method, path, body in WRITES:
        new = song_rig.call(method, path, body)
        old = ask(old_url, method, path, body)
        assert new[0] == old[0], (method, path, body)
        assert settle(new[2]) == settle(old[2]), (method, path, body)
    new_files = sorted(p.relative_to(song_rig.data) for p in song_rig.data.rglob("*") if p.is_file())
    old_files = sorted(p.relative_to(old_data) for p in old_data.rglob("*") if p.is_file())
    assert [re.sub(r"-\d{9,}", "", str(p)) for p in new_files] == [re.sub(r"-\d{9,}", "", str(p)) for p in old_files]
    for rel in new_files:
        if rel.parts[0] in ("arrangements", "mix2", "transitions.json") and rel.suffix == ".json":
            a, b = song_rig.data / rel, old_data / rel
            if b.exists():
                assert settle(a.read_bytes()) == settle(b.read_bytes()), rel
    assert song_rig.worker_starts == old_starts and len(old_starts) == 1


def test_the_pages_hold_no_link_outside_the_prefix():
    """Every absolute link in the six pages gains /app/song, so nothing leaves the mount."""
    static = song.arranger_dir() / "static"
    link = re.compile(r"""['"`]/(?!app/song/)[a-zA-Z0-9.]""")
    for page in sorted(static.glob("*.html")):
        mounted = song.mount_html(page.read_text())
        assert mounted != page.read_text() or page.name == "never"
        assert link.findall(mounted) == [], page.name
    assert song.mount_html("fetch('/api/x'); f(`/audio/${a}`); ['A', '/']; '/mix2/'; '/fx.json'") == (
        "fetch('/app/song/api/x'); f(`/app/song/audio/${a}`); ['A', '/app/song/']; '/app/song/mix2/'; "
        "'/app/song/fx.json'"
    )
    assert (
        song.mount_html("a/b 'x' '/elsewhere' '//cdn' 'http://x/api'") == "a/b 'x' '/elsewhere' '//cdn' 'http://x/api'"
    )


def test_the_old_arranger_page_files_are_not_edited():
    """The sheets are the pages unchanged: the mount rewrites on the way out, the files stay as the arranger has them."""
    assert "/app/song" not in "".join(p.read_text() for p in (song.arranger_dir() / "static").glob("*.html"))


# ---- the saved arrangement: same bytes for keys the app does not own ------------------------------------------------


def stored(song_rig: SongRig, aid: str = "short-8d2a2") -> dict[str, Any]:
    result: dict[str, Any] = json.loads((song_rig.data / "arrangements" / f"{aid}.json").read_text())
    return result


def test_opening_gives_the_files_own_bytes(song_rig):
    file_bytes = (song_rig.data / "arrangements" / "short-8d2a2.json").read_bytes()
    code, _, body = song_rig.call("GET", "/api/arrangements/short-8d2a2")
    assert code == 200 and body == file_bytes


def test_a_save_from_the_page_keeps_every_other_key_byte_for_byte(song_rig):
    sample = samples().ARRANGEMENT
    future = {"futureKey": {"z": [1, 2.50, "x"], "a": None}, "desk": {"monitor": ["mon C1"], "n": 1e-3}}
    f = song_rig.data / "arrangements" / "short-8d2a2.json"
    f.write_text(json.dumps({**sample, **future}))
    before = json.loads(f.read_text())
    code, _, _ = song_rig.call("PUT", "/api/arrangements/short-8d2a2", PAGE_SAVE)
    after = json.loads(f.read_text())
    assert code == 200
    owned = {"name", "bars", "regions", "mutes", "saved"}
    for key in set(before) - owned:  # transitions, mix, mix2, spectral, kickFuzz, desk and a key nobody knows yet
        assert json.dumps(after[key]) == json.dumps(before[key]), key
    assert set(after) - owned == set(before) - owned
    assert after["regions"] == PAGE_SAVE["regions"] and after["name"] == "Mine"
    assert "futureKey" in after and after["saved"] > before["saved"]


def test_the_recipe_has_the_structure_and_the_sound_apart_and_together_they_are_the_file(song_rig):
    code, recipe = song_rig.rig.command("song.recipe", {"id": "short-8d2a2"})
    on_disk = stored(song_rig)
    assert code == 200
    structure, sound = recipe["structure"], recipe["sound"]
    assert set(structure) & set(sound) == set()
    assert set(structure) == {"name", "bars", "regions", "mutes", "transitions"}
    assert set(sound) == {"mix", "mix2", "spectral", "kickFuzz", "desk"}
    assert {**structure, **sound, "saved": recipe["saved"]} == on_disk


def test_the_song_is_the_structure_as_lanes_in_the_loops_order(song_rig):
    code, view = song_rig.rig.command("song.show", {"id": "short-8d2a2"})
    assert code == 200 and view["name"] == "8d2a2 Fast build, slow peak" and view["bars"] == 40
    assert [lane["lane"] for lane in view["lanes"]] == ["kick", "p1-oh", "splash", "chord"]
    kick = view["lanes"][0]
    assert kick["title"] == "Kick" and kick["regions"][0]["start"] == 16
    assert [t["id"] for t in view["transitions"]] == ["nr-lp-2", "sc-hp-1bar"]
    assert "mix" not in view and "desk" not in view  # a Song is structure only


def test_a_song_view_without_a_loops_index_lists_lanes_by_id(song_rig):
    (song_rig.data / "loops.json").unlink()
    code, view = song_rig.rig.command("song.show", {"id": "short-8d2a2"})
    assert code == 200 and {lane["title"] for lane in view["lanes"]} == {"kick", "p1-oh", "splash", "chord"}


def test_the_list_and_the_unknown_arrangement(song_rig):
    code, reply = song_rig.rig.command("song.list")
    assert code == 200 and reply["canonical"] == "short-8d2a2"
    assert [a["id"] for a in reply["arrangements"]] == ["other", "short-8d2a2"] or len(reply["arrangements"]) == 2
    assert song_rig.rig.command("song.show", {"id": "nope"})[0] == 400
    assert song_rig.rig.command("song.show", {"id": "Bad_Id"})[0] == 400


# ---- the writes are commands on the bus ------------------------------------------------------------------------------


def test_a_page_save_is_a_command_by_you_in_the_bus_log(song_rig):
    code, _, _ = song_rig.call("PUT", "/api/arrangements/short-8d2a2", PAGE_SAVE)
    assert code == 200
    assert song_rig.rig.desk.bus.log[-1]["kind"] == "song.save" and song_rig.rig.desk.bus.log[-1]["who"] == "you"
    song_rig.call("PUT", "/api/arrangements/short-8d2a2/mix", {"channels": {}})
    assert song_rig.rig.desk.bus.log[-1]["kind"] == "song.keep"
    kinds = [e["kind"] for e in song_rig.rig.desk.bus.log]
    assert "song.save" in kinds and song_rig.rig.get("/api/commands")[1]["commands"].count("song.build") == 1


def test_the_same_save_through_the_command_door_gives_the_same_file(song_rig):
    code, reply = song_rig.rig.command("song.save", {"id": "x-1", "body": PAGE_SAVE})
    assert code == 200 and reply["ok"] is True
    assert stored(song_rig, "x-1")["regions"] == PAGE_SAVE["regions"]
    assert song_rig.rig.command("song.keep", {"id": "x-1", "key": "mix", "body": {"channels": {}}})[0] == 200
    assert stored(song_rig, "x-1")["mix"] == {"channels": {}}
    assert song_rig.rig.command("song.keep", {"id": "x-1", "key": "desk", "body": {}})[0] == 400  # not a later key
    assert song_rig.rig.command("song.save", {"id": "Bad Id", "body": PAGE_SAVE})[0] == 400
    assert song_rig.rig.command("song.save", {"id": "x-1", "body": {"no": "regions"}})[0] == 400
    assert song_rig.rig.command("song.delete", {"id": "x-1"})[0] == 200
    assert not (song_rig.data / "arrangements" / "x-1.json").exists()


def test_an_agent_may_save_but_the_agent_rule_still_holds_for_the_build(song_rig):
    bus = song_rig.rig.desk.bus
    assert bus.submit(Command("song.save", "agent", {"id": "by-agent", "body": PAGE_SAVE}))[0] == 200
    assert bus.log[-1]["who"] == "agent"
    code, reply = bus.submit(Command("song.build", "agent", {}))
    assert code == 403 and "cannot change Live" in reply["error"]


# ---- building Live ---------------------------------------------------------------------------------------------------


@pytest.fixture
def quick_live(monkeypatch):
    """The build's waits (the browser load) cost no time."""
    from types import SimpleNamespace

    from zpkt.live import ops

    monkeypatch.setattr(ops, "time", SimpleNamespace(sleep=lambda s: None))


def open_set(rig: Rig, name: str | None) -> None:
    rig.live.song.file_path = f"/Sets/{name} Project/{name}.als" if name else ""
    rig.desk.bus.guard.forget()


def test_the_build_is_refused_on_another_set_and_sends_nothing(song_rig, quick_live):
    rig = song_rig.rig
    open_set(rig, "HW002_121_pp_finish")
    tracks_before = [t.name for t in rig.live.song.tracks]
    calls = len(rig.live.calls)
    code, reply = rig.command("song.build")
    assert code == 409 and "HW002_121_pp_mix" in reply["error"]
    assert len(rig.live.calls) == calls + 1  # the one question about the open set
    assert [t.name for t in rig.live.song.tracks] == tracks_before


def test_the_build_is_refused_on_a_set_live_does_not_name(song_rig, quick_live):
    """It empties the set, so an unsaved one is not trusted the way a move trusts it."""
    rig = song_rig.rig
    open_set(rig, None)
    tracks_before = [t.name for t in rig.live.song.tracks]
    code, reply = rig.command("song.build")
    assert code == 409 and "does not name" in reply["error"]
    assert [t.name for t in rig.live.song.tracks] == tracks_before


def test_the_build_makes_the_mix_set_through_the_apps_connection(song_rig, quick_live):
    rig = song_rig.rig
    open_set(rig, MIX_SET)
    calls = len(rig.live.calls)
    code, reply = rig.command("song.build", {"id": "short-8d2a2"})
    assert code == 200, reply
    assert reply["channels"] == 5 and reply["buses"] == 4 and reply["clips"] == 47 and reply["id"] == "short-8d2a2"
    names = [t.name for t in rig.live.song.tracks]
    assert names == [
        "Kick bus", "Hats bus", "Chord and splash bus", "Transitions bus",
        "kick", "p1-oh", "splash", "chord", "fx-riser",
    ]  # fmt: skip
    assert rig.live.song.tempo == 160.0
    assert len(rig.live.calls) > calls + 20  # many short calls, each through the one connection
    kick = rig.track("kick")
    assert sorted(c.start_time for c in kick.arrangement_clips) == [64.0, 80.0, 96.0, 112.0, 128.0, 144.0]
    assert len(rig.track("p1-oh").arrangement_clips) == 36
    assert all(c.warping is False for c in kick.arrangement_clips)
    main = [d.name for d in rig.live.song.master_track.devices]
    assert main[-1] == "EQ Eight"  # the kept spectral fix, after the headroom Utility Main already had
    assert rig.desk.bus.log[-1]["kind"] == "song.build" and rig.desk.bus.log[-1]["status"] == 200


def test_the_build_runs_with_live_held_so_nothing_else_talks_to_it_meanwhile(song_rig, quick_live):
    rig = song_rig.rig
    open_set(rig, MIX_SET)
    held: list[bool] = []
    real = song_rig.adapter.service.build

    def watching(live, cmd):
        held.append(rig.conn.lock._is_owned())
        return real(live, cmd)

    song_rig.adapter.service.build = watching
    assert rig.command("song.build")[0] == 200
    assert held == [True]


def test_the_build_says_what_is_missing_instead_of_failing(song_rig, quick_live):
    rig = song_rig.rig
    open_set(rig, MIX_SET)
    (song_rig.data / "loops.json").unlink()
    code, reply = rig.command("song.build")
    assert code == 400 and "loops.json" in reply["error"] and "mine.py" in reply["error"]
    assert rig.command("song.build", {"id": "nope"})[0] == 400
