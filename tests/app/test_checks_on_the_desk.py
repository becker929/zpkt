"""The bus's checks on the real desk: the wrong-set guard, the agent rule and the agent's automatic version."""

from __future__ import annotations

from tests.app.conftest import wait_for
from tests.app.test_web import first_control
from zpkt.app.bus import Command
from zpkt.live import state as S


def test_a_move_is_refused_when_live_has_another_set_open_and_nothing_is_sent(rig):
    _, key, _ = first_control(rig, "f")
    before = S.flatten(S.take(rig.conn))[key]
    rig.live.song.file_path = "/Sets/HW002_121_pp_B Project/HW002_121_pp_B.als"
    rig.desk.bus.guard.forget()
    calls = len(rig.live.calls)
    code, reply = rig.command("mix.set", {"norms": [[key, 0.1]]})
    assert code == 409 and "Live has HW002_121_pp_B open; this page is for HW002_121_pp_finish" in reply["error"]
    assert len(rig.live.calls) == calls + 1  # the one question to Live, no write
    assert S.flatten(S.take(rig.conn))[key].raw == before.raw
    assert rig.desk.history.entries == []
    # the old routes are the same commands, so they are guarded too; and reading is not
    assert rig.post("/api/transport", {"action": "play"})[0] == 409
    assert rig.get("/api/state")[0] == 200


def test_the_right_set_passes(rig):
    rig.live.song.file_path = "/Sets/HW002_121_pp_finish Project/HW002_121_pp_finish.als"
    rig.desk.bus.guard.forget()
    assert rig.post("/api/transport", {"action": "play"})[0] == 200


def test_an_agent_cannot_move_live_on_its_own_but_can_with_your_word_or_an_option(rig):
    _, key, _ = first_control(rig, "f")
    ask = {"norms": [[key, 0.1]]}
    code, _ = rig.desk.bus.submit(Command("mix.set", "agent", ask))
    assert code == 403 and rig.desk.history.entries == []
    assert rig.desk.bus.submit(Command("mix.set", "agent", ask, approval="option:fader-10"))[0] == 403
    rig.desk.bus.option_picked = lambda option: option == "fader-10"
    assert rig.desk.bus.submit(Command("mix.set", "agent", ask, approval="option:fader-10"))[0] == 200


def test_an_agent_group_saves_a_version_first_and_undoes_as_one(rig):
    keys = [v["key"] for k, v in rig.state()["values"].items() if v.get("key") and k.startswith("0:f")][:3]
    start = {k: S.flatten(S.take(rig.conn))[k].raw for k in keys}
    for k in keys:
        reply = rig.desk.bus.submit(
            Command("mix.set", "agent", {"norms": [[k, 0.15]]}, approval="user", group="make the kick sit back")
        )
        assert reply[0] == 200
    versions = [e for e in rig.desk.history.entries if e["k"] == "checkpoint"]
    assert len(versions) == 1 and versions[0]["who"] == "sys" and versions[0]["name"].startswith("before-make-the-kick")
    moves = [e for e in rig.desk.history.entries if e["k"] == "move"]
    assert len(moves) == 1 and moves[0]["who"] == "agent" and moves[0]["group"] == "make the kick sit back"
    assert len(moves[0]["moves"]) == len(keys)
    changed = {k: S.flatten(S.take(rig.conn))[k].raw for k in keys}
    assert all(changed[k] != start[k] for k in keys)
    assert rig.post("/api/undo")[0] == 200  # one undo takes the whole group back
    assert wait_for(lambda: {k: S.flatten(S.take(rig.conn))[k].raw for k in keys} == start)


def test_changes_go_to_the_stream_grouped_by_gesture_and_by_who(rig):
    _, key, _ = first_control(rig, "f")
    rig.command("mix.set", {"norms": [[key, 0.3]]})
    rig.desk.bus.submit(Command("mix.set", "minilab", {"norms": [[key, 0.6]]}))
    rig.post("/api/undo")
    _, body = rig.get("/api/changes")
    who = [c["who"] for c in body["changes"]]
    assert who[:2] == ["you", "minilab"] and body["changes"][-1]["group"].startswith("undo-of-")
    assert body["changes"][0]["group"].startswith("gesture-")
    assert [c["n"] for c in body["changes"]] == list(range(1, len(who) + 1))
    assert rig.get(f"/api/changes?since={body['last']}")[1]["changes"] == []


def test_a_failed_write_leaves_no_entry_behind(rig, monkeypatch):
    _, key, _ = first_control(rig, "f")
    monkeypatch.setattr(rig.desk, "write", lambda pairs: (_ for _ in ()).throw(OSError("Live went away")))
    code, reply = rig.command("mix.set", {"norms": [[key, 0.3]]})
    assert code == 503 and "Live went away" in reply["error"]
    assert rig.desk.history.entries == []
    assert rig.desk.history.cur[key][1] == S.flatten(S.take(rig.conn))[key].raw


def test_tempo_and_folders_are_settings_not_literals(monkeypatch, tmp_path):
    from zpkt.app import desk

    assert desk.beats_per_s({"bpm": 150}) == 2.5
    monkeypatch.setenv("ZPKT_DESK_BPM", "90")
    assert desk.beats_per_s({}) == 1.5
    monkeypatch.setenv("ZPKT_MIXDESK_DIR", str(tmp_path))
    (tmp_path / "sources.json").write_text('{"ref_align_s": 10, "bpm": 120, "set": "s", "dir": "d", "refs": []}')
    assert desk.default_align_beat() == 20.0
    monkeypatch.setenv("ZPKT_ASK_DIR", str(tmp_path / "ask"))
    assert desk.default_ask_dir() == tmp_path / "ask"


def test_surface_model_is_read_at_call_time(monkeypatch):
    from zpkt.app import surfaces

    monkeypatch.setenv("MIXDESK_MODEL", "opus")
    assert surfaces.model() == "opus"
    monkeypatch.delenv("MIXDESK_MODEL")
    assert surfaces.model() == "sonnet"
