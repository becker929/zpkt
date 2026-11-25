"""The API adapter: the token, who may call, and each job through a real HTTP request on FakeLive."""

from __future__ import annotations

import http.client
import json
import os
import stat
import threading
import time

import pytest

from zpkt.app import jobs, token
from zpkt.app.adapters import AppContext, discover
from zpkt.app.adapters.api import ROUTES, ApiAdapter, parse_request
from zpkt.app.bus import BadRequest, Command

# ---- the token -----------------------------------------------------------------------------------------------------


def test_the_token_file_is_made_with_mode_0600_in_a_private_folder(tmp_path):
    made = token.ensure_token(tmp_path / "cfg")
    path = token.token_path(tmp_path / "cfg")
    assert len(made) >= 32 and path.read_text().strip() == made
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_token_that_exists_is_kept_and_a_loose_file_is_tightened(tmp_path):
    first = token.ensure_token(tmp_path)
    token.token_path(tmp_path).chmod(0o644)
    assert token.ensure_token(tmp_path) == first
    assert stat.S_IMODE(token.token_path(tmp_path).stat().st_mode) == 0o600


def test_an_empty_token_file_is_filled(tmp_path):
    token.token_path(tmp_path).write_text("")
    assert token.ensure_token(tmp_path)


def test_the_config_folder_can_be_named_by_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ZPKT_CONFIG_DIR", str(tmp_path / "x"))
    assert token.token_path() == tmp_path / "x" / "app-token"
    assert token.read_token() is None
    token.ensure_token()
    assert token.read_token()


def test_starting_the_adapter_makes_the_token_file(api):
    assert token.read_token(api.config_dir) == api.token
    assert stat.S_IMODE(token.token_path(api.config_dir).stat().st_mode) == 0o600


# ---- access --------------------------------------------------------------------------------------------------------


def test_health_is_open_and_everything_else_wants_the_token(api):
    assert api.get("/health", token=None) == (200, {"ok": True, "app": "zpkt", "api": 1})
    for method, path in (("GET", "/api/v1/commands"), ("POST", "/api/v1/live/run")):
        assert api.call(method, path, {}, token=None)[0] == 401
        assert api.call(method, path, {}, token="wrong")[0] == 401
    assert api.get("/commands")[0] == 200


def test_a_request_for_another_host_name_is_turned_away(api):
    conn = http.client.HTTPConnection("127.0.0.1", api.adapter.port, timeout=10)
    conn.request("GET", "/api/v1/health", headers={"Host": "evil.example"})
    r = conn.getresponse()
    assert r.status == 403 and "localhost" in json.loads(r.read())["error"]


def test_the_server_listens_on_localhost_only(api):
    assert api.adapter.server.server_address[0] == "127.0.0.1"


def test_the_token_is_never_printed(api, capsys):
    api.run("song.tempo")
    api.get("/commands", token="wrong")
    out = capsys.readouterr()
    assert api.token not in out.out + out.err


# ---- the request ---------------------------------------------------------------------------------------------------


def test_who_is_one_of_the_api_callers_and_defaults_to_cli():
    assert parse_request({"kind": "x"}).who == "cli"
    for who in ("you", "minilab", "sys", "gemini"):
        with pytest.raises(BadRequest, match="'who' is one of"):
            parse_request({"kind": "x", "who": who})


def test_an_agent_cannot_say_the_user_approved():
    with pytest.raises(BadRequest, match="cannot say the user approved"):
        parse_request({"kind": "x", "who": "agent", "approval": "user"})
    assert parse_request({"kind": "x", "who": "agent", "approval": "option:7"}).approval == "option:7"
    assert parse_request({"kind": "x", "who": "cli", "approval": "user"}).approval == "user"


@pytest.mark.parametrize("body", [[], {"args": 1, "kind": "x"}, {"kind": 5}, {"kind": "x", "group": 3}])
def test_a_bad_request_is_a_400(body):
    with pytest.raises(BadRequest):
        parse_request(body)


def test_bad_json_and_unknown_routes(api):
    conn = http.client.HTTPConnection("127.0.0.1", api.adapter.port, timeout=10)
    conn.request("POST", "/api/v1/command", body=b"{", headers={"Authorization": f"Bearer {api.token}"})
    r = conn.getresponse()
    assert r.status == 400 and "not JSON" in json.loads(r.read())["error"]
    assert api.post("/nowhere")[0] == 404
    assert api.call("POST", "/elsewhere", {})[0] == 404
    assert api.post("/command", {"kind": "nope"})[0] == 404


def test_the_adapter_is_found_by_the_registry():
    assert "api" in discover()


def test_every_named_route_is_a_command_on_the_bus(rig):
    assert set(ROUTES.values()) <= set(rig.desk.bus.kinds("cli"))


def test_the_listing_says_who_may_ask(api):
    _, body = api.get("/commands")
    by_kind = {c["kind"]: c for c in body["commands"]}
    assert by_kind["live.run"]["callers"] == ["agent", "booth", "demo", "cli"]
    assert by_kind["live.run"]["effect"] == "move" and by_kind["live.run"]["touches_live"]
    assert by_kind["mix.set"]["callers"] == []  # anyone


# ---- the web page may not use the jobs -----------------------------------------------------------------------------


def test_the_web_page_cannot_run_code_in_live(rig):
    code, body = rig.command("live.run", {"code": "song.tempo = 90"})
    assert code == 403 and "not open to 'you'" in body["error"]
    assert "live.run" not in rig.get("/api/commands")[1]["commands"]


# ---- who is stamped, and the agent rule ----------------------------------------------------------------------------


def test_a_run_goes_through_the_bus_with_who_and_group(api, rig):
    code, body = api.run("song.tempo = 97.0", who="booth", group="render-1")
    assert code == 200 and body["ok"] and body["reply"]["status"] == "ok"
    assert rig.live.song.tempo == 97.0
    last = rig.desk.bus.log[-1]
    assert (last["kind"], last["who"], last["group"], last["status"]) == ("live.run", "booth", "render-1", 200)


def test_a_run_answers_what_live_said_when_live_refuses(api):
    code, body = api.run("song.nonsense_attribute")
    assert code == 200 and not body["ok"] and body["reply"]["status"] == "error" and body["reply"]["error"]


def test_an_agent_needs_an_option_or_the_users_word_to_run_code(api, rig):
    code, body = api.run("song.tempo = 91.0", who="agent")
    assert code == 403 and "cannot change Live" in body["error"]
    assert api.run("song.tempo = 91.0", who="agent", approval="user")[0] == 400
    assert rig.live.song.tempo != 91.0
    code, body = api.run("song.tempo = 91.0", who="agent", approval="option:3", group="ask-1")
    assert code == 200 and rig.live.song.tempo == 91.0


def test_an_agent_may_read_and_read_refuses_code_that_changes(api, rig):
    code, body = api.post("/live/read", {"who": "agent", "args": {"code": "result = song.tempo"}})
    assert code == 200 and body["reply"]["result"] == rig.live.song.tempo
    code, body = api.post("/live/read", {"who": "agent", "args": {"code": "song.tempo = 80.0"}})
    assert code == 400 and "live.run" in body["error"]


def test_read_cannot_be_used_to_change_live_by_a_route_the_write_check_misses(api, rig):
    before = rig.live.song.tempo
    for code_text in ("setattr(song, 'tempo', 80.0)", "f = song.stop_playing\nf()", "exec('song.tempo = 80.0')"):
        code, _ = api.post("/live/read", {"who": "agent", "args": {"code": code_text}})
        assert code == 400, code_text
    assert rig.live.song.tempo == before


def test_a_missing_code_is_a_400(api):
    assert api.post("/live/run", {"args": {}})[0] == 400


# ---- the lock ------------------------------------------------------------------------------------------------------


def test_a_job_waits_its_turn_and_says_so_when_live_stays_busy(api, rig):
    held, release = threading.Event(), threading.Event()

    def hold():
        with rig.conn.exclusive():
            held.set()
            release.wait(20)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    try:
        bus = rig.desk.bus
        bus._lock = lambda: rig.conn.exclusive(wait_s=0.2)  # not five seconds in a test
        code, body = api.run("song.tempo")
        assert code == 503 and "Live is busy" in body["error"]
    finally:
        release.set()
        t.join()
    assert api.run("song.tempo")[0] == 200


# ---- the named jobs ------------------------------------------------------------------------------------------------


def test_set_tempo_and_its_range(api, rig):
    assert api.post("/live/tempo", {"who": "demo", "args": {"bpm": 133.5}})[0] == 200
    assert rig.live.song.tempo == 133.5
    assert api.post("/live/tempo", {"args": {"bpm": 5}})[0] == 400
    assert api.post("/live/tempo", {"args": {"bpm": "fast"}})[0] == 400
    assert api.post("/live/tempo", {"args": {"bpm": True}})[0] == 400


def test_transport_plays_stops_seeks_and_loops(api, rig):
    song = rig.live.song
    assert api.post("/live/transport", {"args": {"action": "play"}})[0] == 200 and song.is_playing
    assert api.post("/live/transport", {"args": {"action": "stop"}})[0] == 200 and not song.is_playing
    assert api.post("/live/transport", {"args": {"action": "seek", "beat": 8.0}})[0] == 200
    assert song.current_song_time == 8.0
    assert api.post("/live/transport", {"args": {"action": "loop", "start": 4.0, "length": 16.0}})[0] == 200
    assert song.loop and song.loop_start == 4.0 and song.loop_length == 16.0
    assert api.post("/live/transport", {"args": {"action": "dance"}})[0] == 400
    assert api.post("/live/transport", {"args": {"action": "seek"}})[0] == 400


def test_state_take_then_put_puts_the_mix_back(api):
    code, body = api.post("/state/take", {"args": {}})
    assert code == 200 and body["state"]["tracks"]
    before = body["state"]
    code, put = api.post("/state/put", {"who": "cli", "args": {"state": before}})
    assert code == 200 and isinstance(put["left"], list)
    assert api.post("/state/put", {"args": {"state": "nope"}})[0] == 400
    assert api.post("/state/put", {"args": {"state": {"x": 1}}})[0] == 400


def test_state_take_only_some_tracks(api):
    _, all_of_it = api.post("/state/take", {"args": {}})
    first = next(iter(all_of_it["state"]["tracks"]))
    code, some = api.post("/state/take", {"args": {"only": [first]}})
    assert code == 200 and list(some["state"]["tracks"]) == [first]
    assert api.post("/state/take", {"args": {"only": "x"}})[0] == 400


def test_describe_says_what_is_there_and_what_is_missing(api):
    code, body = api.post("/describe", {"args": {"keys": ["Kick bus/volume", "Nobody/volume"]}})
    assert code == 200 and not body["ok"]
    assert body["found"]["Kick bus/volume"]["kind"] == "continuous" and "Nobody/volume" in body["missing"]
    assert api.post("/describe", {"args": {"keys": []}})[0] == 400


def test_open_set_calls_the_session_and_makes_the_guard_ask_again(api, rig, monkeypatch):
    seen = []
    monkeypatch.setattr(
        jobs.session, "open_set", lambda live, name, save_current: seen.append((name, save_current)) or 4.25
    )
    rig.desk.bus.guard._seen = (time.monotonic(), "old")
    code, body = api.post("/live/open-set", {"args": {"name": "other.als", "save_current": False}})
    assert code == 200 and body == {"ok": True, "name": "other", "seconds": 4.25}
    assert seen == [("other", False)]
    assert rig.desk.bus.guard._seen is None


def test_open_set_turns_a_guard_into_a_409(api, monkeypatch):
    def stop(*a, **k):
        raise jobs.session.Guard("open: already open")

    monkeypatch.setattr(jobs.session, "open_set", stop)
    code, body = api.post("/live/open-set", {"args": {"name": "x"}})
    assert code == 409 and "already open" in body["error"]


def test_open_set_is_not_held_by_the_desks_set_guard(api, rig, monkeypatch):
    """The wrong-set guard is for the desk's page; opening a set is how to get to the right one."""
    monkeypatch.setattr(jobs.openset, "open_set_name", lambda live: "some_other_set")
    monkeypatch.setattr(jobs.session, "open_set", lambda live, name, save_current: 1.0)
    assert api.post("/live/open-set", {"args": {"name": "x"}})[0] == 200
    assert api.run("song.tempo")[0] == 200  # a booth render on its own set is not held either


def test_a_caller_that_names_its_set_is_refused_when_live_has_another(api, rig, monkeypatch):
    monkeypatch.setattr(jobs.openset, "open_set_name", lambda live: "booth_set")
    code, body = api.post("/live/tempo", {"args": {"bpm": 120, "expect_set": "other_set"}})
    assert code == 409 and "booth_set" in body["error"] and "Open that set first" in body["error"]
    assert api.post("/live/tempo", {"args": {"bpm": 120, "expect_set": "booth_set.als"}})[0] == 200
    monkeypatch.setattr(jobs.openset, "open_set_name", lambda live: "")  # an unsaved set passes
    assert api.post("/live/tempo", {"args": {"bpm": 121, "expect_set": "anything"}})[0] == 200


def test_render_loop_hands_the_range_to_the_export(api, rig, tmp_path, monkeypatch):
    from zpkt.live import render

    asked = []
    monkeypatch.setattr(
        render, "export", lambda live, path, start, length, **kw: asked.append((path, start, length, kw)) or [path]
    )
    code, body = api.post("/live/render-loop", {"who": "booth", "args": {"out": "loop.wav", "start": 0, "length": 32}})
    assert code == 200
    path, start, length, kw = asked[0]
    assert path.name == "loop.wav" and path.parent == rig.tmp / "renders"  # a bare name goes to the renders folder
    assert (start, length) == (0.0, 32.0) and kw == {"mode": "Main", "bits": 32, "sample_rate": 44100}
    assert body["files"] == [str(path)]
    assert api.post("/live/render-loop", {"args": {"out": "x.wav", "start": 1}})[0] == 400
    assert api.post("/live/render-loop", {"args": {}})[0] == 400


def test_render_loop_says_why_an_export_failed(api, monkeypatch):
    from zpkt.live import render

    def refuse(*a, **k):
        raise ValueError("x.mp3: export writes ['.aif']")

    monkeypatch.setattr(render, "export", refuse)
    code, body = api.post("/live/render-loop", {"args": {"out": "x.mp3"}})
    assert code == 409 and "export failed" in body["error"]


def test_page_apply_says_when_there_is_no_such_panel(api, tmp_path):
    code, body = api.post("/page/apply", {"args": {"name": "ghost", "out": str(tmp_path)}})
    assert code == 409 and "no panel 'ghost'" in body["error"]
    assert api.post("/page/apply", {"args": {"name": "x", "state": [1]}})[0] == 400


def test_page_apply_runs_the_panels_apply(api, tmp_path, monkeypatch):
    from zpkt.live import panel

    (tmp_path / "p.json").write_text("{}")
    monkeypatch.setattr(panel, "_file", lambda out, name: out / "p.json")
    seen = []
    monkeypatch.setattr(panel, "apply", lambda live, name, out, **kw: seen.append((name, kw)) or "applied")
    code, body = api.post("/page/apply", {"args": {"name": "p", "out": str(tmp_path), "state": {"a": 1}}})
    assert code == 200 and body["text"] == "applied"
    assert seen[0][0] == "p" and seen[0][1]["state_values"] == {"a": 1} and seen[0][1]["force"] is False


def test_the_environment_names_the_port(rig, monkeypatch):
    monkeypatch.setenv("ZPKT_API_PORT", "0")
    a = ApiAdapter(AppContext(rig.desk.bus, rig.desk, rig.desk.settings), config_dir=rig.tmp / "c")
    assert a.wanted_port == 0
    with pytest.raises(RuntimeError, match="has not started"):
        _ = a.port
    assert os.environ["ZPKT_API_PORT"] == "0"


def test_the_command_object_is_what_the_bus_gets(api, rig):
    api.run("song.tempo", who="demo", group="g")
    assert rig.desk.bus.log[-1]["who"] == "demo"
    assert isinstance(Command("x"), Command)
