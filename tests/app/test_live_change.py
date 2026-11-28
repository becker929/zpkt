"""`live.change`: an agent changes Live itself, in batches. The whole batch is checked before anything moves, it is
one History row with a version before it, and one undo takes it back: values, added devices and moved ones."""

from __future__ import annotations

import pytest

from zpkt.app import change
from zpkt.app.bus import Command
from zpkt.live import chain

KICK = "Kick bus"
VOL = "Kick bus/volume"
GAIN = "Kick bus/desk EQ/1 Gain A"
BATCH = {
    "why": "warmer kick",
    "steps": [
        {"set": VOL, "to": 0.5},
        {"add": "Saturator", "track": KICK, "at": 0},
        {"set": "Kick bus/Saturator/Drive", "to": 6.0},
        {"device": "desk Glue", "track": KICK, "on": False},
        {"move": "desk EQ", "track": KICK, "to": 3},
    ],
}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)


def run(rig, args, who="agent", **kw):
    return rig.desk.bus.submit(Command("live.change", who, args, **kw))


def names(rig, track=KICK):
    return [d.name for d in rig.track(track).devices]


def param(rig, track, device, name):
    dev = next(d for d in rig.track(track).devices if d.name == device)
    return next(p for p in dev.parameters if p.name == name)


def snapshot(rig):
    """Everything a batch could touch on the tracks these tests use."""
    out = {}
    for t in (KICK, "Main", "mon A", "Hats bus"):
        track = rig.track(t)
        out[t] = (
            track.mixer_device.volume.value,
            [(d.name, [p.value for p in d.parameters]) for d in track.devices],
        )
    return out


def test_an_agents_batch_runs_with_no_approval_and_is_one_row_with_a_version_before_it(rig):
    code, reply = run(rig, BATCH, group="ask-s1")
    assert code == 200, reply
    assert reply["ok"] and reply["done"] == 5 and reply["undo"] == "warmer kick (3 controls, 2 devices)"
    assert names(rig) == ["Saturator", "desk Sat", "desk Glue", "desk EQ"]
    assert rig.track(KICK).mixer_device.volume.value == 0.5
    assert param(rig, KICK, "Saturator", "Drive").value == 6.0
    assert param(rig, KICK, "desk Glue", "Device On").value == 0.0
    assert reply["added"] == [{"track": KICK, "device": "Saturator", "at": 0}]
    assert set(reply["now"]) == {VOL, "Kick bus/Saturator/Drive", "Kick bus/desk Glue/Device On"}
    assert reply["now"][VOL][1] == 0.5 and isinstance(reply["now"][VOL][0], str)
    entries = rig.desk.history.entries
    assert [e["k"] for e in entries] == ["checkpoint", "change"]  # the version, then the one row
    cp, row = entries
    assert cp["who"] == "sys" and cp["name"].startswith("before-ask-s1") and rig.desk.history.has_checkpoint(cp["name"])
    assert row["who"] == "agent" and row["why"] == "warmer kick" and row["group"] == "ask-s1"
    assert [m["key"] for m in row["moves"]] == [VOL, "Kick bus/Saturator/Drive", "Kick bus/desk Glue/Device On"]
    assert [(d["op"], d["device"]) for d in row["devices"]] == [
        ("add", "Saturator"),  # Live puts a loaded device last
        ("move", "Saturator"),  # so "at": 0 is a move of its own
        ("move", "desk EQ"),
    ]
    assert rig.desk.bus.log[-1]["who"] == "agent" and rig.desk.bus.log[-1]["status"] == 200


def test_one_undo_takes_the_whole_batch_back_and_redo_puts_it_on_again(rig):
    before = snapshot(rig)
    assert run(rig, BATCH)[0] == 200
    after = snapshot(rig)
    assert after != before
    code, undone = rig.command("history.undo")
    assert code == 200 and undone["missing"] == [] and "notes" not in undone
    assert snapshot(rig) == before  # values back, the Saturator gone, desk EQ first again
    code, redone = rig.command("history.redo")
    assert code == 200 and redone["missing"] == []
    assert snapshot(rig) == after
    assert rig.command("history.undo")[0] == 200 and snapshot(rig) == before
    assert [e["k"] for e in rig.desk.history.entries] == ["checkpoint", "change"]


def test_going_back_to_before_a_batch_takes_its_devices_off_too_and_undoes_as_one(rig):
    before = snapshot(rig)
    assert run(rig, BATCH)[0] == 200
    assert rig.command("mix.set", {"writes": [["Hats bus/volume", 0.3]]})[0] == 200
    after = snapshot(rig)
    row = next(e for e in rig.desk.history.entries if e["k"] == "change")
    code, _ = rig.command("history.back", {"entry": row["id"]})
    assert code == 200 and snapshot(rig) == before
    assert rig.command("history.undo")[0] == 200 and snapshot(rig) == after


def test_a_bad_batch_is_refused_whole_with_every_problem_and_nothing_changes(rig):
    before, calls = snapshot(rig), len(rig.desk.history.entries)
    code, reply = run(
        rig,
        {
            "why": "all wrong",
            "steps": [
                {"set": VOL, "to": 0.4},  # fine: and still not written
                {"set": "Kick bus/desk EQ/No such", "to": 1},
                {"set": GAIN, "to": 400},
                {"set": "Nobody/volume", "to": 0.5},
                {"add": "Saturatr", "track": KICK},
                {"add": "Saturator", "track": "Nobody"},
                {"device": "ghost", "track": KICK, "on": False},
                {"move": "desk EQ", "track": KICK, "to": 9},
                {"add": "Saturator", "track": KICK, "at": 7},
                {"set": VOL},
                {"remove": "desk EQ", "track": KICK},
                "nonsense",
            ],
        },
    )
    assert code == 400 and "nothing changed" in reply["error"]
    assert [int(p.split()[1].rstrip(":")) for p in reply["problems"]] == [10, 11, 12, 2, 3, 4, 5, 6, 7, 8, 9]
    text = "\n".join(reply["problems"])
    for words in ("No such", "outside its range", "Nobody", '"Saturatr"', 'no device "ghost"', "past the end", '"to"'):
        assert words in text, words
    assert snapshot(rig) == before and len(rig.desk.history.entries) == calls  # no version, no row
    assert rig.desk.history.checkpoints() == []


def test_the_limits_and_the_shape(rig):
    assert run(rig, {})[0] == 400 and run(rig, {"why": "x", "steps": []})[0] == 400
    code, reply = run(rig, {"steps": [{"set": VOL, "to": 0.4}]})
    assert code == 400 and '"why"' in reply["problems"][0]
    code, reply = run(rig, {"why": "many", "steps": [{"set": VOL, "to": 0.4}] * 41})
    assert code == 400 and "more than 40" in reply["problems"][0]
    code, reply = run(rig, {"why": "many", "steps": [{"add": "Saturator", "track": KICK}] * 9})
    assert code == 400 and "more than 8" in reply["problems"][0]
    code, reply = run(rig, {"why": "a list", "steps": [{"set": "Kick bus/desk EQ/1 Filter On A", "to": 0.5}]})
    assert code == 400 and "between two steps" in reply["problems"][0]
    assert rig.desk.history.entries == []


RAILED = [
    {"set": "mon A/volume", "to": 0.5},
    {"add": "Saturator", "track": "mon A"},
    {"device": "desk Glue", "track": "Main", "on": False},
    {"set": "Main/desk headroom/Output", "to": 0.0},
    {"set": "Main/desk Utility/Gain", "to": 0.0},
    {"device": "zpkt listen", "track": "Main", "on": False},
    {"device": "zpkt desk meter", "track": "main", "on": False},
    {"move": "desk Glue", "track": "Main", "to": 2},
    {"add": "Saturator", "track": "Main"},
]


@pytest.mark.parametrize("step", RAILED, ids=[str(s) for s in RAILED])
def test_the_rails_hold_the_monitor_tracks_and_mains_desk_devices(rig, step):
    before = snapshot(rig)
    for who in ("agent", "you"):
        code, reply = run(rig, {"why": "railed", "steps": [{"set": VOL, "to": 0.4}, step]}, who=who)
        assert code == 400 and len(reply["problems"]) == 1 and reply["problems"][0].startswith("step 2"), reply
    assert snapshot(rig) == before and rig.desk.history.entries == []
    assert set(change.RAILED_ON_MAIN) == {
        "desk headroom",
        "desk Glue",
        "desk Utility",
        "zpkt listen",
        "zpkt desk meter",
    }


def test_mains_own_volume_is_not_railed(rig):
    code, _ = run(rig, {"why": "main down", "steps": [{"set": "Main/volume", "to": 0.7}]})
    assert code == 200 and rig.track("Main").mixer_device.volume.value == pytest.approx(0.7)


def test_the_wrong_set_guard_holds_the_batch(rig):
    before = snapshot(rig)
    rig.live.song.file_path = "/Sets/other Project/someone_elses_set.als"
    rig.desk.bus.guard.forget()
    code, reply = run(rig, BATCH)
    assert code == 409 and "someone_elses_set" in reply["error"]
    assert snapshot(rig) == before and rig.desk.history.entries == []


@pytest.mark.parametrize(
    ("kind", "args"),
    [
        ("live.run", {"code": "song.tempo = 91.0"}),
        ("mix.set", {"writes": [[VOL, 0.3]]}),
        ("transport", {"action": "play"}),
        ("history.undo", {}),
        ("page.compare", {"id": "x", "state": 1}),
        ("meter.install", {}),
    ],
)
def test_every_other_move_of_an_agent_is_still_refused(rig, kind, args):
    tempo, vol = rig.live.song.tempo, rig.track(KICK).mixer_device.volume.value
    code, reply = rig.desk.bus.submit(Command(kind, "agent", args))
    assert code == 403 and "cannot change Live" in reply["error"] and "change_live" in reply["error"]
    assert (rig.live.song.tempo, rig.track(KICK).mixer_device.volume.value) == (tempo, vol)


def test_only_live_change_and_what_the_person_kept_are_open_to_an_agent_on_its_own(asked):
    table = asked.rig.desk.bus.table
    assert {k for k, s in table.items() if s.agent_may} == {"live.change", "ability.run", "render.bounce"}
    assert table["live.change"].effect == "move" and table["live.change"].guarded and table["live.change"].touches_live


def test_a_step_that_fails_in_live_stops_the_batch_and_the_reply_says_what_was_done(rig, monkeypatch):
    before = snapshot(rig)
    real = chain.load_effect

    def fails(client, track, device, *a, **kw):
        if device == "Echo":
            raise chain.ChainError(f"Live did not load {device!r} on {track!r}")
        return real(client, track, device, *a, **kw)

    monkeypatch.setattr(chain, "load_effect", fails)
    code, reply = run(
        rig,
        {
            "why": "half",
            "steps": [
                {"set": VOL, "to": 0.5},
                {"add": "Saturator", "track": KICK},
                {"add": "Echo", "track": KICK},
                {"set": GAIN, "to": 3.0},
            ],
        },
    )
    assert code == 502 and reply["ok"] is False and reply["done"] == 2
    assert reply["failed"]["step"] == 3 and "did not load" in reply["failed"]["why"] and reply["not_done"] == [3, 4]
    assert "step 3" in reply["error"] and reply["undo"] == "half (1 control, 1 device)"
    assert names(rig)[-1] == "Saturator" and rig.track(KICK).mixer_device.volume.value == 0.5
    assert param(rig, KICK, "desk EQ", "1 Gain A").value == 0.0  # the step after the failure was not run
    assert [e["k"] for e in rig.desk.history.entries] == ["checkpoint", "change"]
    assert rig.command("history.undo")[0] == 200 and snapshot(rig) == before  # undo covers what was done


def test_a_value_on_a_device_the_batch_adds_is_checked_when_its_step_comes(rig):
    code, reply = run(
        rig,
        {
            "why": "too hot",
            "steps": [{"add": "Saturator", "track": KICK}, {"set": "Kick bus/Saturator/Drive", "to": 999.0}],
        },
    )
    assert code == 502 and reply["done"] == 1 and "outside its range" in reply["failed"]["why"]
    assert names(rig)[-1] == "Saturator"
    assert rig.command("history.undo")[0] == 200 and "Saturator" not in names(rig)


def test_a_batch_that_changes_nothing_leaves_no_row_and_no_version(rig):
    vol = rig.track(KICK).mixer_device.volume.value
    code, reply = run(rig, {"why": "same", "steps": [{"set": VOL, "to": vol}]})
    assert code == 200 and reply["done"] == 1 and reply["undo"] is None and reply["now"] == {}
    assert rig.desk.history.entries == []


def test_the_person_may_send_a_batch_too_and_it_is_theirs(rig):
    code, reply = rig.command("live.change", {"why": "mine", "steps": [{"set": VOL, "to": 0.45}]})
    assert code == 200 and reply["undo"] == "mine (1 control)"
    row = rig.desk.history.entries[-1]
    assert row["k"] == "change" and row["who"] == "you"


def test_a_second_device_of_a_name_is_named_with_its_count(rig):
    code, reply = run(
        rig,
        {
            "why": "two",
            "steps": [
                {"add": "Saturator", "track": KICK},
                {"add": "Saturator", "track": KICK},
                {"set": "Kick bus/Saturator#2/Drive", "to": 3.0},
                {"move": "Saturator#2", "track": KICK, "to": 0},
            ],
        },
    )
    assert code == 200, reply
    assert [a["device"] for a in reply["added"]] == ["Saturator", "Saturator#2"]
    assert names(rig) == ["Saturator", "desk EQ", "desk Sat", "desk Glue", "Saturator"]
    assert param(rig, KICK, "Saturator", "Drive").value == 3.0  # the one moved first is the one that was set
    assert rig.command("history.undo")[0] == 200 and names(rig) == ["desk EQ", "desk Sat", "desk Glue"]


def test_the_tool_reaches_the_bus_through_the_ask_gate_as_the_agent(asked):
    rig, gate = asked.rig, asked.ask.gate
    body = {"session": "s1", "token": gate.token("s1"), "tool": "change_live", "args": BATCH}
    code, reply = rig.post("/app/ask/api/tool", body)
    assert code == 200 and reply["ok"] and reply["done"] == 5, reply
    last = rig.desk.bus.log[-1]
    assert (last["kind"], last["who"], last["status"]) == ("live.change", "agent", 200)
    row = rig.desk.history.entries[-1]
    assert row["k"] == "change" and row["who"] == "agent" and row["group"] == "ask-s1"
    code, bad = rig.post(
        "/app/ask/api/tool", {**body, "args": {"why": "x", "steps": [{"set": "mon A/volume", "to": 0}]}}
    )
    assert code == 400 and bad["problems"]
    assert rig.post("/app/ask/api/tool", {**body, "token": "wrong"})[0] == 403
    # a second batch of the same session is a row of its own, with a version of its own
    code, _ = rig.post("/app/ask/api/tool", {**body, "args": {"why": "again", "steps": [{"set": VOL, "to": 0.3}]}})
    assert code == 200
    assert [e["k"] for e in rig.desk.history.entries] == ["checkpoint", "change", "checkpoint", "change"]


def test_a_main_without_the_desks_devices_takes_one(rig):
    """A song of its own has none of the desk's devices on Main: a limiter may go there like on any track (the
    persona walkthrough, 27 November 2026: the mix ended at -20.9 LUFS and Main could take no limiter)."""
    main = rig.track("Main")
    main._devices = [d for d in main._devices if change.base_name(d.name) not in change.RAILED_ON_MAIN]
    code, reply = run(rig, {"why": "a limiter on Main", "steps": [{"add": "Saturator", "track": "Main"}]})
    assert code == 200, reply
    assert [d.name for d in main.devices][-1].startswith("Saturator")
