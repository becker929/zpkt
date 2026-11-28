"""The wrong-set check on every command that moves Live. A job that names no set is held to the set the app last
saw open; one that names its set is held to that one. Live is FakeLive, whose set file a test names."""

from __future__ import annotations

import pytest

from zpkt.app import effects, jobs
from zpkt.app.bus import Bus, Command, Refused, SetGuard, Spec
from zpkt.live import session
from zpkt.live.app_transport import AppTransport

PAGE_SET = "HW002_121_pp_finish"


def live_has(rig, name: str | None) -> None:
    rig.live.song.file_path = f"/Sets/{name} Project/{name}.als" if name else ""
    rig.desk.bus.guard.forget()


@pytest.fixture()
def app_env(api, monkeypatch):
    monkeypatch.setenv("ZPKT_APP_URL", api.url)
    return api


# every move a caller of the API can ask for, with arguments that would work on the right set
MOVES = {
    "live.run": {"code": "song.tempo = 91.0"},
    "live.set_tempo": {"bpm": 91.0},
    "live.transport": {"action": "play"},
    "live.render_loop": {"out": "x.wav"},
    "state.put": {"state": {}},
    "page.apply": {"name": "ghost"},
    "panel.apply": {"name": "ghost"},
}


def test_every_job_that_moves_is_in_the_list_above(rig):
    table = rig.desk.bus.table
    moving_jobs = {k for k in jobs.JOBS if table[k].effect == "move"}
    assert moving_jobs == set(MOVES)


@pytest.mark.parametrize("kind", sorted(MOVES))
def test_a_move_that_names_no_set_is_refused_when_live_has_another_than_the_app_last_saw(rig, kind):
    live_has(rig, "someone_elses_set")
    calls = len(rig.live.calls)
    code, body = rig.desk.bus.submit(Command(kind, "cli", MOVES[kind]))
    assert code == 409, (kind, body)
    assert "someone_elses_set" in body["error"] and PAGE_SET in body["error"] and "expect_set" in body["error"]
    assert len(rig.live.calls) == calls + 1  # the one question about the open set; nothing was sent after it


def test_every_move_on_the_bus_passes_the_wrong_set_check_but_opening_a_set(asked):
    """By the table: a move is held by the page's guard or by the job's own; only the moves that change which set is
    open are let through (live.open_set, and the songs: zpkt.app.songs), since they are how to get to the right set.
    song.save checks itself that Live has the desk's set in front."""
    unguarded = {
        kind for kind, spec in asked.rig.desk.bus.table.items() if effects.EFFECTS[kind] == "move" and not spec.guarded
    }
    assert unguarded == {"live.open_set", "song.new", "song.open", "song.save", "song.save_as"}


@pytest.mark.parametrize("kind", ["mix.set", "page.arm", "pager.restart", "tempo.set", "transport", "history.undo"])
def test_the_desks_moves_are_for_the_pages_set(rig, kind):
    live_has(rig, "someone_elses_set")
    code, body = rig.desk.bus.submit(Command(kind, "you", {}))
    assert code == 409 and "this page is for" in body["error"], (kind, body)


def test_a_read_that_names_no_set_looks_at_whatever_is_open(rig):
    live_has(rig, "someone_elses_set")
    code, body = rig.desk.bus.submit(Command("live.read", "cli", {"code": "result = song.tempo"}))
    assert code == 200 and body["ok"]
    code, body = rig.desk.bus.submit(Command("live.read", "cli", {"code": "result = 1", "expect_set": "mine"}))
    assert code == 409 and "this call is for mine" in body["error"]


def test_a_job_on_the_set_the_app_last_saw_passes(rig):
    live_has(rig, PAGE_SET)
    assert rig.desk.bus.submit(Command("live.set_tempo", "cli", {"bpm": 92.0}))[0] == 200
    assert rig.live.song.tempo == 92.0


def test_naming_the_open_set_tells_the_app_which_one_is_open(rig):
    """A caller that says which set it is for, and is right, has shown the app the set: the next call that names
    none is held to that one."""
    live_has(rig, "booth_set")
    assert rig.desk.bus.submit(Command("live.set_tempo", "booth", {"bpm": 93.0}))[0] == 409
    assert rig.desk.bus.submit(Command("live.set_tempo", "booth", {"bpm": 93.0, "expect_set": "booth_set"}))[0] == 200
    assert rig.desk.bus.guard.believed == "booth_set"
    assert rig.desk.bus.submit(Command("live.set_tempo", "booth", {"bpm": 94.0}))[0] == 200
    live_has(rig, PAGE_SET)
    code, body = rig.desk.bus.submit(Command("live.set_tempo", "booth", {"bpm": 95.0}))
    assert code == 409 and "last saw booth_set" in body["error"]
    assert rig.live.song.tempo == 94.0


def test_opening_a_set_through_the_app_makes_it_the_set_the_app_believes_is_open(rig, monkeypatch):
    def opened(live, name, save_current):
        rig.live.song.file_path = f"/Sets/{name} Project/{name}.als"
        return 1.0

    monkeypatch.setattr(jobs.session, "open_set", opened)
    assert rig.desk.bus.submit(Command("live.open_set", "booth", {"name": "booth_set"}))[0] == 200
    assert rig.desk.bus.guard.believed == "booth_set"
    assert rig.desk.bus.submit(Command("live.run", "booth", {"code": "song.tempo = 96.0"}))[0] == 200
    code, body = rig.desk.bus.submit(Command("mix.set", "you", {"writes": [["Kick bus/volume", 0.5]]}))
    assert code == 409 and "this page is for" in body["error"]  # the desk's page is still for its own set


def test_asking_the_app_to_open_the_set_live_already_has_tells_it_so(rig, monkeypatch):
    """Live will not reopen the front set, so the answer is still 409; but the app now knows which set it is."""

    def already(live, name, save_current):
        raise session.Guard(f"open: {name} is already open")

    monkeypatch.setattr(jobs.session, "open_set", already)
    live_has(rig, "by_hand")
    assert rig.desk.bus.submit(Command("live.open_set", "cli", {"name": "by_hand"}))[0] == 409
    assert rig.desk.bus.guard.believed == "by_hand"
    assert rig.desk.bus.submit(Command("live.open_set", "cli", {"name": "another"}))[0] == 409
    assert rig.desk.bus.guard.believed == "by_hand"  # only what Live really has open


def test_a_set_opened_by_a_client_through_the_transport_is_told_to_the_app(app_env, rig, monkeypatch):
    """`zpkt live open` and the booth run zpkt.live.session.open_set themselves, with the app's transport. The
    session tells the transport, and the transport tells the app."""
    transport = AppTransport("booth")
    live_has(rig, "booth_set")
    assert transport.execute("song.tempo = 97.0").status == "error"
    session.tell_opened(transport, "booth_set")
    assert rig.desk.bus.guard.believed == "booth_set"
    assert transport.execute("song.tempo = 97.0").status == "ok" and rig.live.song.tempo == 97.0
    session.tell_opened(object(), "anything")  # a transport with nothing to tell (a direct LiveClient) is fine


def test_the_transport_sends_code_that_only_reads_as_a_read(app_env, rig):
    """So a client waiting for a set to come up (`result = 1`) is not held by the check it is about to satisfy."""
    transport = AppTransport("booth")
    live_has(rig, "not_yet_known")
    assert transport.run("result = 1") == 1
    assert rig.desk.bus.log[-1]["kind"] == "live.read"
    assert transport.execute("song.tempo = 98.0").status == "error"
    assert rig.desk.bus.log[-1]["kind"] == "live.run"


# ---- the guard on its own --------------------------------------------------------------------------------------------


def guard(have: list[str]) -> SetGuard:
    return SetGuard("page_set", lambda: have[0])


def test_a_named_set_is_asked_of_live_afresh_and_a_set_live_does_not_name_passes():
    have = ["a"]
    g = guard(have)
    g.check_job("a.als")
    have[0] = "b"  # no five-second memory for a job: Live is asked each time
    with pytest.raises(Refused, match="Live has b open; this call is for a"):
        g.check_job("a")
    have[0] = ""
    g.check_job("anything")
    g.check_job(None)
    assert g.believed == "a"


def test_an_unnamed_job_is_held_to_the_set_last_seen_which_starts_as_the_pages():
    have = ["other"]
    g = guard(have)
    with pytest.raises(Refused, match="last saw page_set") as refused:
        g.check_job(None)
    assert refused.value.code == 409
    have[0] = "page_set"
    g.check_job(None)


def test_the_bus_checks_a_job_inside_the_lock_and_never_runs_its_handler_when_refused():
    ran: list[str] = []
    bus = Bus(guard=guard(["other"]))
    bus.register("job.move", Spec(lambda cmd: (ran.append("move"), (200, {}))[1], "move", own_set=True))
    bus.register("job.read", Spec(lambda cmd: (ran.append("read"), (200, {}))[1], "read", own_set=True))
    assert bus.submit(Command("job.move", "cli"))[0] == 409
    assert bus.submit(Command("job.read", "cli"))[0] == 200
    assert bus.submit(Command("job.move", "cli", {"expect_set": "other"}))[0] == 200
    assert bus.submit(Command("job.move", "cli", {"expect_set": 7}))[0] == 400
    assert ran == ["read", "move"]
