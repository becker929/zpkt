"""Every route of the mix desk's server, through real HTTP, against FakeLive with the pager loaded (conftest.py)."""

from __future__ import annotations

import json
import queue
import urllib.request

import jsonschema
import pytest
from conftest import wait_for

import gen_schema
from zpkt.live.testing.display import fader_db

# ---- pages and reads -----------------------------------------------------------------------------------------------


def test_the_page_and_the_desk(rig):
    for path in ("/", "/index.html"):
        code, body = rig.get(path)
        assert code == 200 and b"<script>" in body
    code, desk = rig.get("/api/desk")
    assert code == 200 and desk["pages"][0]["name"] == "Buses" and "controls" in desk["pages"][0]
    assert rig.get("/nope")[0] == 404


def test_state_holds_what_the_pager_reported(rig):
    st = rig.state()
    assert st["live"] == "attached" and st["attached"] is True and st["page"] == 0
    assert st["values"]["0:k8"]["key"] == "Main/desk headroom/Output" and st["values"]["0:k8"]["s"] == "-6.00 dB"
    assert st["monitor"] == {"slot": "W", "ref": "C1"} and st["match"] is True and st["loop"] == "off"


def test_analysis_and_media(rig):
    code, an = rig.get("/api/analysis")
    assert code == 200 and set(an["sources"]) >= {"A", "B", "C1"}
    code, body = rig.get("/media/A.wav")
    assert code == 200 and body.startswith(b"RIFF") and len(body) == 4 + 1024
    code, part = rig.get("/media/A.wav", headers={"Range": "bytes=4-7"})
    assert code == 206 and part == bytes([0, 1, 2, 3])
    for bad in ("/media/B.wav", "/media/x.txt", "/media/..%2Fanalysis.json"):
        assert rig.get(bad)[0] == 404
    (rig.tmp / "viz" / "analysis.json").unlink()
    assert rig.get("/api/analysis") == (404, {"error": "run analyze.py first"})


# ---- the MiniLab's pages and switches ------------------------------------------------------------------------------


def test_arming_a_page_and_toggling_a_pad(rig):
    assert rig.post("/api/page", {"page": 2}) == (200, {"ok": True})
    assert wait_for(lambda: rig.state()["page"] == 2)
    assert rig.call("m.DESK.page") == 2
    desk = rig.get("/api/desk")[1]
    page, slot = next(
        (i, s)
        for i, p in enumerate(desk["pages"])
        for s, c in p["controls"].items()
        if s.startswith("b") and c.get("param") == "mute"
    )
    track = rig.track(desk["pages"][page]["controls"][slot]["track"])
    was = track.mute
    assert rig.post("/api/toggle", {"slot": slot, "page": page}) == (200, {"ok": True})
    assert track.mute is (not was)
    assert rig.post("/api/toggle", {"slot": "k1", "page": 0}) == (400, {"error": "bad slot"})


def test_transport_seek_play_pause_loop(rig):
    assert rig.post("/api/transport", {"action": "seek", "beat": 32.0}) == (200, {"ok": True})
    assert rig.live.song.current_song_time == 32.0
    assert rig.post("/api/transport", {"action": "play"})[0] == 200 and rig.live.song.is_playing
    assert rig.post("/api/transport", {"action": "pause"})[0] == 200 and not rig.live.song.is_playing
    assert rig.post("/api/transport", {"action": "loop", "loop": "drop"})[0] == 200
    assert rig.live.song.loop and rig.live.song.loop_start == 64.0
    assert wait_for(lambda: rig.state()["loop"] == "drop")
    assert rig.post("/api/transport", {"action": "loop", "loop": "sideways"}) == (400, {"error": "bad loop"})
    assert rig.post("/api/transport", {"action": "rewind"}) == (400, {"error": "bad action"})


def test_monitor_solos_the_render_at_the_matched_gain_and_seeks_c_to_the_drop(rig):
    assert rig.post("/api/monitor", {"slot": "A", "ref": "C1"}) == (200, {"ok": True})
    mon_a = rig.track("mon A")
    # A's drop is -9 LUFS, the quietest of A, B, C1 is -12: A plays 3 dB down
    assert mon_a.solo and fader_db(mon_a.mixer_device.volume.value) == pytest.approx(-3.0, abs=0.06)
    assert wait_for(lambda: rig.state()["monitor"] == {"slot": "A", "ref": "C1"})
    assert rig.post("/api/monitor", {"slot": "A", "match": False})[0] == 200
    assert fader_db(mon_a.mixer_device.volume.value) == pytest.approx(0.0, abs=0.06)
    assert rig.state()["match"] is False
    rig.post("/api/transport", {"action": "seek", "beat": 8.0})
    assert rig.post("/api/monitor", {"slot": "C", "ref": "C2"})[0] == 200
    assert rig.live.song.current_song_time == 64.0  # the reference only exists from the drop
    assert rig.post("/api/transport", {"action": "seek", "beat": 8.0})[0] == 200
    assert rig.live.song.current_song_time == 64.0
    assert rig.post("/api/monitor", {"slot": "W"})[0] == 200 and not rig.track("mon C2").solo
    assert rig.post("/api/monitor", {"slot": "Z"}) == (400, {"error": "bad slot or ref"})
    assert rig.post("/api/monitor", {"slot": "C", "ref": "C9"}) == (400, {"error": "bad slot or ref"})


def test_restart_reloads_the_pager_on_the_same_page(rig):
    rig.post("/api/page", {"page": 3})
    assert rig.post("/api/restart") == (200, {"ok": True})
    assert rig.call("m.DESK.page") == 3 and rig.state()["live"] == "attached"


# ---- history: undo, redo, checkpoints, compare, revert -------------------------------------------------------------


def move_kick_bus(rig, value: float) -> None:
    rig.live.run(f"find_track('Kick bus').mixer_device.volume.value = {value}")


def test_a_move_is_history_and_undo_redo_write_it_back(rig):
    move_kick_bus(rig, 0.5)
    hist = wait_for(lambda: (h := rig.get("/api/history")[1])["entries"] and h)
    assert hist["t"] == "hist" and hist["can_undo"] and hist["entries"][-1]["moves"][0]["key"] == "Kick bus/volume"
    code, out = rig.post("/api/undo")
    assert code == 200 and out["ok"] and out["missing"] == [] and out["entry"] == hist["entries"][-1]["id"]
    assert rig.track("Kick bus").mixer_device.volume.value == pytest.approx(0.85)
    assert rig.post("/api/redo")[1]["ok"] and rig.track("Kick bus").mixer_device.volume.value == pytest.approx(0.5)


def test_checkpoints_compare_and_revert(rig):
    code, out = rig.post("/api/checkpoint", {"name": "before"})
    assert code == 200 and out == {"ok": True, "name": "before"}
    saved = json.loads((rig.tmp / "state" / "before.json").read_text())
    assert saved["made_by"] == "mixdesk" and saved["tracks"]["Kick bus"]["mixer"]["volume"][1] == pytest.approx(0.85)
    assert rig.post("/api/checkpoint", {"name": "../x"})[0] == 400
    move_kick_bus(rig, 0.5)
    wait_for(lambda: rig.get("/api/compare?a=before")[1])
    code, cmp = rig.get("/api/compare?a=before&b=now")
    assert code == 200 and list(cmp) == ["Kick bus/volume"] and cmp["Kick bus/volume"]["a"][1] == pytest.approx(0.85)
    code, vals = rig.get("/api/checkpoint?name=before")
    assert code == 200 and vals["Kick bus/volume"][1] == pytest.approx(0.85)
    assert rig.get("/api/checkpoint?name=nope")[0] == 404
    assert rig.get("/api/compare?a=../x")[0] == 404
    code, out = rig.post("/api/revert", {"to": "before", "keys": ["Kick bus/volume"]})
    assert code == 200 and out == {"ok": True, "moved": 1, "missing": []}
    assert rig.track("Kick bus").mixer_device.volume.value == pytest.approx(0.85)


def test_revert_all_puts_the_whole_mix_back_after_a_checkpoint(rig):
    rig.post("/api/checkpoint", {"name": "base"})
    move_kick_bus(rig, 0.4)
    rig.live.run("find_track('Hats bus').devices[0].parameters[0].value = 0.0")  # not a desk control's value
    wait_for(lambda: rig.get("/api/compare?a=base")[1])
    code, out = rig.post("/api/revert", {"to": "base", "all": True})
    assert code == 200 and out["ok"] and isinstance(out["left"], list)
    assert rig.track("Kick bus").mixer_device.volume.value == pytest.approx(0.85)
    assert rig.track("Hats bus").devices[0].parameters[0].value == 1.0
    names = [c["name"] for c in rig.get("/api/history")[1]["checkpoints"]]
    assert names[0] == "base" and names[1].startswith("before-revert-")


# ---- surfaces ------------------------------------------------------------------------------------------------------


SURFACE = {
    "name": "Kick test",
    "what": "the kick bus",
    "controls": {"f1": {"track": "Kick bus", "param": "volume"}, "b1": {"track": "Kick bus", "param": "mute"}},
}


def test_save_and_remove_a_surface(rig):
    pages = len(rig.get("/api/desk")[1]["pages"])
    code, out = rig.post("/api/surface/save", {"surface": SURFACE, "prompt": "a kick page"})
    assert code == 200 and out["ok"] and out["page"] == pages and out["file"].endswith(".json")
    desk = rig.get("/api/desk")[1]
    assert len(desk["pages"]) == pages + 1 and desk["pages"][-1]["surface"] == out["file"]
    assert rig.call("m.DESK.page") == pages
    assert rig.post("/api/surface/save", {"surface": {"name": "x", "controls": {}}})[0] == 400
    assert rig.post("/api/surface/remove", {"file": out["file"]}) == (200, {"ok": True})
    assert len(rig.get("/api/desk")[1]["pages"]) == pages
    assert rig.post("/api/surface/remove", {"file": "../evil.json"})[0] == 400


def test_make_a_surface_runs_the_job_with_a_stand_in_for_claude(rig, monkeypatch):
    import surfaces

    monkeypatch.setattr(surfaces, "ask_claude", lambda prompt: json.dumps(SURFACE))
    q = queue.Queue()
    rig.desk.clients.append(q)
    try:
        assert rig.post("/api/surface/make", {"text": "the kick"}) == (200, {"ok": True})
        msgs = []
        while not msgs or msgs[-1]["status"] not in ("done", "error"):
            m = q.get(timeout=10)
            if m["t"] == "surface":
                msgs.append(m)
        assert msgs[-1]["status"] == "done" and "Kick test" in msgs[-1]["msg"]
    finally:
        rig.desk.clients.remove(q)
    assert rig.get("/api/desk")[1]["pages"][-1]["name"] == "Kick test"
    assert rig.post("/api/surface/make", {"text": "  "}) == (400, {"error": "say what the surface is for"})


# ---- the event stream ----------------------------------------------------------------------------------------------


def test_events_start_with_the_full_state_then_stream_moves(rig):
    with urllib.request.urlopen(rig.url + "/events", timeout=10) as r:
        assert r.headers["Content-Type"] == "text/event-stream"
        validator = jsonschema.Draft202012Validator(json.loads(gen_schema.OUT.read_text()))
        first = json.loads(r.readline().decode()[len("data: ") :])
        validator.validate(first)
        assert first["t"] == "full" and first["state"]["live"] == "attached"
        assert r.readline() == b"\n"
        move_kick_bus(rig, 0.3)
        for _ in range(50):
            line = r.readline().decode()
            if line.startswith("data: "):
                m = json.loads(line[6:])
                validator.validate(m)  # every message the pager and the server send fits the contract
                if m["t"] == "v" and m["key"] == "Kick bus/volume":
                    break
        else:
            pytest.fail("no value message for the move")


# ---- bad requests --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/page", {}),
        ("/api/page", {"page": "two"}),
        ("/api/toggle", {"slot": "b1"}),
        ("/api/transport", {}),
        ("/api/transport", {"action": "seek"}),
        ("/api/transport", {"action": "seek", "beat": "soon"}),
        ("/api/transport", {"action": "seek", "beat": "nan"}),
        ("/api/transport", {"action": "loop"}),
        ("/api/surface/save", {}),
        ("/api/revert", {}),
        ("/api/revert", {"to": "../x"}),
        ("/api/revert", {"to": "nope"}),
        ("/api/revert", {"to": "nope", "keys": "Kick bus/volume"}),
    ],
)
def test_a_bad_body_is_a_400_that_says_what_is_wrong(rig, path, body):
    code, out = rig.post(path, body)
    assert code == 400 and out["error"]


def test_a_body_that_is_not_a_json_object_is_a_400_and_an_unknown_route_a_404(rig):
    assert rig.post("/api/page", raw=b"{not json")[0] == 400
    assert rig.post("/api/page", raw=b"[1]")[0] == 400
    assert rig.post("/api/nope") == (404, {"error": "not found"})


def test_revert_all_to_a_missing_checkpoint_changes_nothing(rig):
    rig.post("/api/monitor", {"slot": "A"})
    assert rig.post("/api/revert", {"to": "nope", "all": True})[0] == 400
    assert rig.get("/api/history")[1]["checkpoints"] == []  # no before-revert checkpoint was made
    assert rig.state()["monitor"]["slot"] == "A"  # and the monitor was not switched


def test_the_state_carries_the_loudness_match_for_the_page(rig):
    gains = rig.state()["gains"]
    assert gains["C1"] == {"A": -3.0, "B": -2.0, "C": 0.0} and set(gains) == {"C1", "C2", "C3", "C4"}


def test_history_entries_say_who_made_them(rig):
    rig.post("/api/checkpoint", {"name": "base"})
    move_kick_bus(rig, 0.4)
    wait_for(lambda: rig.get("/api/compare?a=base")[1])
    rig.post("/api/revert", {"to": "base", "all": True})
    entries = rig.get("/api/history")[1]["entries"]
    made = [(e["k"], e.get("name", ""), e["who"]) for e in entries]
    assert made[:2] == [("checkpoint", "base", "you"), ("move", "", "you")]  # the page's checkpoint, a move in Live
    assert made[2][0] == "checkpoint" and made[2][1].startswith("before-revert-")
    assert made[2][2] == "sys" and made[3][::2] == ("revert", "you")  # the desk's own checkpoint, then the page's


# ---- the routes are shared: a second page, another set's desk file ------------------------------------------------


def test_a_second_page_shares_every_route(rig, tmp_path):
    import threading

    import server

    second = tmp_path / "second.html"
    second.write_text("<!doctype html><title>second</title>")
    pages = {**server.PAGES, "/second/": second}
    http = server.DeskHTTPServer(("127.0.0.1", 0), rig.desk, pages)
    threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    url = f"http://127.0.0.1:{http.server_address[1]}"
    try:
        with urllib.request.urlopen(url + "/second/", timeout=10) as r:
            assert r.read() == second.read_bytes() and r.headers["Content-Type"].startswith("text/html")
        with urllib.request.urlopen(url + "/api/state", timeout=10) as r:
            assert json.loads(r.read())["attached"] is True
        with urllib.request.urlopen(url + "/", timeout=10) as r:
            assert b"<script>" in r.read()
    finally:
        http.shutdown()
        http.server_close()
    assert rig.get("/second/")[0] == 404  # the desk's own server serves only its own pages


def test_the_desk_file_is_a_setting(rig, tmp_path):
    import dataclasses

    import server

    other = tmp_path / "other-desk.json"
    other.write_text(
        json.dumps({"pages": [{"name": "Only", "controls": {"f1": {"track": "Kick bus", "param": "volume"}}}]})
    )
    desk = server.Desk(dataclasses.replace(rig.desk.settings, desk_file=other))
    assert [p["name"] for p in desk.cfg()["pages"]] == ["Only"]
    assert rig.desk.settings.desk_file == server.HERE / "desk.json"
