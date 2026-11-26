"""`live.propose`: structure and code wait for the person's tap. The batch is checked whole before anybody is asked,
nothing moves before the tap, and after it the batch is one History row whose undo takes back what it can (values,
added and moved devices) and says what it left (a removed device, a new track, code)."""

from __future__ import annotations

import random

import pytest

from tests.app.test_live_change import GAIN, KICK, VOL, names, param, snapshot
from zpkt.app import history, propose
from zpkt.app.bus import Command
from zpkt.live import chain, newtrack

HATS = "Hats bus"
CODE = "song.tempo = 91.0\nresult = 'tempo set'"
MIXED = {
    "why": "parallel drive",
    "steps": [
        {"set": VOL, "to": 0.5},
        {"new_track": "return", "name": "Drive"},
        {"add": "Saturator", "track": "Drive"},
        {"set": "Drive/Saturator/Drive", "to": 6.0},
        {"set": "Drive/volume", "to": 0.6},
        {"add": "Saturator", "track": HATS, "at": 0},
        {"remove": "desk Sat", "track": HATS},
        {"move": "desk EQ", "track": HATS, "to": 0},
        {"code": CODE, "does": "Sets the tempo to 91."},
    ],
}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(chain.time, "sleep", lambda s: None)
    monkeypatch.setattr(newtrack.time, "sleep", lambda s: None)


def check(rig, args, who="agent"):
    return rig.desk.bus.submit(Command("live.propose.check", who, args))


def run(rig, args, who="agent", approval="user", **kw):
    return rig.desk.bus.submit(Command("live.propose", who, args, approval=approval, **kw))


def whole(rig):
    """Everything a proposal could touch: the usual tracks, the tempo, and which tracks and returns there are."""
    song = rig.live.song
    return (snapshot(rig), song.tempo, [t.name for t in song.tracks], [t.name for t in song.return_tracks])


# ---- the check: every new kind of step, the rails, the limits ------------------------------------------------------


def test_the_check_answers_with_the_card_in_plain_words_and_changes_nothing(rig):
    before = whole(rig)
    code, reply = check(
        rig,
        {
            "why": "  parallel   drive ",
            "steps": [
                *MIXED["steps"],
                {"device": "desk Glue", "track": KICK, "on": False},
                {"set": "Kick bus/mute", "to": 1},
                {"set": "Kick bus/send Space", "to": 0.5},
                {"set": GAIN, "to": 3.0},
            ],
        },
    )
    assert code == 200 and reply["ok"] and reply["why"] == "parallel drive", reply
    texts = [s["text"] for s in reply["steps"]]
    assert texts[0].startswith("Set Kick bus volume to ") and texts[0].endswith(" dB")  # as Live shows it
    assert texts[1:9] == [
        "New return track: Drive",
        "Add Saturator to Drive",
        "Set Saturator Drive on Drive to 6",  # on a device that is not there yet: the raw number
        "Set Drive volume to 0.6",
        "Add Saturator to Hats bus as the first device",
        "Remove desk Sat from Hats bus",
        "Move desk EQ on Hats bus to place 1",
        "Sets the tempo to 91.",
    ]
    assert texts[9:12] == ["Turn off desk Glue on Kick bus", "Mute Kick bus", texts[11]]
    assert texts[11].startswith("Set Kick bus send Space to ") and texts[12].startswith("Set desk EQ 1 Gain A on Kick")
    assert [s["n"] for s in reply["steps"] if s.get("no_undo")] == [2, 7, 9]  # the track, the remove, the code
    assert [s.get("code") for s in reply["steps"] if "code" in s] == [CODE]
    assert whole(rig) == before and rig.desk.history.entries == [] and rig.desk.history.checkpoints() == []
    assert rig.desk.bus.log[-1]["status"] == 200 and rig.desk.bus.table["live.propose.check"].effect == "read"


def test_a_bad_proposal_is_refused_whole_with_every_problem(rig):
    before = whole(rig)
    code, reply = check(
        rig,
        {
            "why": "all wrong",
            "steps": [
                {"set": VOL, "to": 0.4},  # fine
                {"remove": "ghost", "track": KICK},
                {"remove": "desk EQ", "track": "Nobody"},
                {"remove": "desk EQ"},
                {"new_track": "group", "name": "X"},
                {"new_track": "audio"},
                {"new_track": "audio", "name": "a/b"},
                {"new_track": "audio", "name": "Kick bus"},
                {"new_track": "return", "name": "Space"},
                {"code": "song.tempo = ", "does": "Breaks."},
                {"code": "song.tempo = 91.0"},
                {"code": "x = 1", "does": "word " * 40},
                {"remove": "desk Sat", "track": HATS},
                {"set": "Hats bus/desk Sat/Drive", "to": 1.0},  # the device an earlier step removes
                {"remove": "desk EQ", "track": KICK, "set": VOL},
                {"add": "Saturator", "track": "Later"},  # the track is made after this step
                {"new_track": "audio", "name": "Later"},
                {"new_track": "midi", "name": "Later"},
            ],
        },
    )
    assert code == 400 and "nobody was asked" in reply["error"], reply
    numbers = sorted(int(p.split()[1].rstrip(":")) for p in reply["problems"])
    assert numbers == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 16, 18]
    text = "\n".join(reply["problems"])
    for words in (
        'no device "ghost"',
        "Nobody",
        'needs "track"',
        '"audio", "midi" or "return"',
        'needs "name"',
        'no "/"',
        'already has a track or return named "Kick bus"',
        'already has a track or return named "Space"',
        "not Python that parses",
        'needs "does"',
        "at most 140",
        'no device "desk Sat"',
        "exactly one of",
        'no track, return or Main named "Later"',
        'already has a track or return named "Later"',
    ):
        assert words in text, words
    assert whole(rig) == before and rig.desk.history.entries == []
    # the move itself checks the same way, also with the person's word
    code, again = run(rig, {"why": "x", "steps": [{"remove": "ghost", "track": KICK}]})
    assert code == 400 and again["problems"] and whole(rig) == before


RAILED = [
    {"remove": "desk Glue", "track": "Main"},
    {"remove": "zpkt listen", "track": "Main"},
    {"remove": "anything", "track": "mon A"},
    {"new_track": "audio", "name": "mon X"},
    {"new_track": "return", "name": "Mon keys"},
    {"new_track": "midi", "name": "Main"},
    {"code": "find_track('mon A').mute = False", "does": "Unmutes a monitor track."},
    {"code": "n = 'zpkt listen'\nresult = n", "does": "Names the capture device."},
    {"add": "Saturator", "track": "Main"},
    {"set": "mon A/volume", "to": 0.5},
    {"device": "desk Glue", "track": "Main", "on": False},
]


@pytest.mark.parametrize("step", RAILED, ids=[str(s)[:60] for s in RAILED])
def test_the_rails_hold_for_a_proposal_too(rig, step):
    before = whole(rig)
    batch = {"why": "railed", "steps": [{"set": VOL, "to": 0.4}, step]}
    for call in (check, run):
        code, reply = call(rig, batch)
        assert code == 400 and len(reply["problems"]) == 1 and reply["problems"][0].startswith("step 2"), reply
    assert whole(rig) == before and rig.desk.history.entries == []
    assert propose.ONLY_ON_MAIN == ("zpkt listen", "zpkt desk meter")


def test_the_limits(rig):
    step = {"code": "result = 1", "does": "Reads nothing."}
    code, reply = check(rig, {"why": "many", "steps": [step] * 4})
    assert code == 400 and "4 code steps is more than 3" in reply["problems"][0]
    code, reply = check(rig, {"why": "long", "steps": [{"code": "x = 1\n" * 400, "does": "Long."}]})
    assert code == 400 and "more than 2000" in reply["problems"][0]
    tracks = [{"new_track": "audio", "name": f"T{k}"} for k in range(9)]
    code, reply = check(rig, {"why": "many", "steps": tracks})
    assert code == 400 and "9 new tracks is more than 8" in reply["problems"][0]
    code, reply = check(rig, {"why": "many", "steps": [{"set": VOL, "to": 0.4}] * 41})
    assert code == 400 and "more than 40" in reply["problems"][0]
    code, reply = check(rig, {"why": "long name", "steps": [{"new_track": "audio", "name": "n" * 41}]})
    assert code == 400 and "at most 40 characters" in reply["problems"][0]
    assert check(rig, {})[0] == 400 and check(rig, {"steps": [step]})[0] == 400
    assert rig.desk.history.entries == []
    assert (propose.MAX_CODE, propose.CODE_MAX) == (3, 2000)


def test_the_wrong_set_holds_the_check_and_the_run(rig):
    before = whole(rig)
    rig.live.song.file_path = "/Sets/other Project/someone_elses_set.als"
    rig.desk.bus.guard.forget()
    for call in (check, run):
        code, reply = call(rig, MIXED)
        assert code == 409 and "someone_elses_set" in reply["error"]
    assert whole(rig) == before and rig.desk.history.entries == []


# ---- who may run it ------------------------------------------------------------------------------------------------


def test_an_agent_cannot_run_it_without_the_persons_word_and_the_page_cannot_run_it_at_all(rig):
    before = whole(rig)
    code, reply = run(rig, MIXED, approval=None)
    assert code == 403 and "cannot change Live" in reply["error"] and "propose_live" in reply["error"]
    code, reply = rig.command("live.propose", MIXED)  # the web page is "you": it may not run code in Live
    assert code == 403 and "not open to 'you'" in reply["error"]
    code, reply = rig.command("live.propose", MIXED, approval="user")  # and the page's body carries no word
    assert code == 403
    assert whole(rig) == before and rig.desk.history.entries == []
    spec = rig.desk.bus.table["live.propose"]
    assert spec.effect == "move" and not spec.agent_may and spec.guarded and spec.touches_live


# ---- the run, History and undo -------------------------------------------------------------------------------------


def test_an_approved_batch_runs_in_order_and_is_one_row_with_a_version_before_it(rig):
    code, reply = run(rig, MIXED, group="ask-s1")
    assert code == 200 and reply["ok"] and reply["done"] == 9, reply
    song = rig.live.song
    assert [t.name for t in song.return_tracks] == ["A-Space", "B-Echo", "C-Drive"]
    assert names(rig, "C-Drive") == ["Saturator"] and param(rig, "C-Drive", "Saturator", "Drive").value == 6.0
    assert rig.track("C-Drive").mixer_device.volume.value == pytest.approx(0.6)
    assert names(rig, HATS) == ["desk EQ", "Saturator"]  # added first, desk Sat gone, desk EQ first again
    assert rig.track(KICK).mixer_device.volume.value == 0.5 and song.tempo == 91.0
    assert reply["undo"] == "parallel drive (3 controls, 3 devices)"
    assert reply["no_undo"] == ["New return track: Drive", "Removed desk Sat from Hats bus", "Sets the tempo to 91."]
    assert reply["made"] == [{"track": "Drive", "kind": "return"}]
    assert reply["removed"] == [{"track": HATS, "device": "desk Sat"}]
    assert reply["ran"] == [{"step": 9, "ok": True, "result": "tempo set"}]
    assert [a["track"] for a in reply["added"]] == ["Drive", HATS]
    assert set(reply["now"]) == {VOL, "Drive/Saturator/Drive", "Drive/volume"}
    entries = rig.desk.history.entries
    assert [e["k"] for e in entries] == ["checkpoint", "change"]
    cp, row = entries
    assert cp["who"] == "sys" and cp["name"].startswith("before-ask-s1")
    assert row["who"] == "agent" and row["why"] == "parallel drive" and row["group"] == "ask-s1"
    assert [(s["op"], s["words"]) for s in row["stays"]] == [
        ("track", "New return track: Drive"),
        ("remove", "Removed desk Sat from Hats bus"),
        ("code", "Sets the tempo to 91."),
    ]
    assert row["stays"][2]["code"] == CODE and "failed" not in row["stays"][2]
    last = rig.desk.bus.log[-1]
    assert (last["kind"], last["who"], last["status"]) == ("live.propose", "agent", 200)


def test_undo_takes_back_what_it_can_and_names_what_it_left(rig):
    before = whole(rig)
    assert run(rig, MIXED)[0] == 200
    after = whole(rig)
    code, undone = rig.command("history.undo")
    assert code == 200 and undone["missing"] == [] and "notes" not in undone, undone
    assert undone["left"] == ["New return track: Drive", "Removed desk Sat from Hats bus", "Sets the tempo to 91."]
    song = rig.live.song
    # taken back: the values, both Saturators, the move of desk EQ
    assert rig.track(KICK).mixer_device.volume.value == before[0][KICK][0]
    assert names(rig, HATS) == ["desk EQ"] and names(rig, "C-Drive") == []
    # left as they are: the removed device stays removed, the track stays, the code's tempo stays
    assert "desk Sat" not in names(rig, HATS)
    assert [t.name for t in song.return_tracks] == ["A-Space", "B-Echo", "C-Drive"] and song.tempo == 91.0
    code, redone = rig.command("history.redo")
    assert code == 200 and redone["missing"] == [] and "left" not in redone
    assert whole(rig) == after
    assert rig.command("history.undo")[0] == 200 and names(rig, HATS) == ["desk EQ"]
    assert [e["k"] for e in rig.desk.history.entries] == ["checkpoint", "change"]


def test_going_back_to_before_the_batch_names_what_it_left_too(rig):
    assert run(rig, MIXED)[0] == 200
    assert rig.command("mix.set", {"writes": [["Hats bus/volume", 0.3]]})[0] == 200
    row = next(e for e in rig.desk.history.entries if e["k"] == "change")
    code, back = rig.command("history.back", {"entry": row["id"]})
    assert code == 200 and len(back["left"]) == 3 and back["left"][1] == "Removed desk Sat from Hats bus"
    assert names(rig, HATS) == ["desk EQ"] and rig.live.song.tempo == 91.0


def test_a_batch_of_only_code_is_a_row_that_undo_leaves_whole(rig):
    code, reply = run(rig, {"why": "tempo", "steps": [{"code": CODE, "does": "Sets the tempo to 91."}]})
    assert code == 200 and reply["undo"] is None and reply["no_undo"] == ["Sets the tempo to 91."]
    assert [e["k"] for e in rig.desk.history.entries] == ["checkpoint", "change"]
    code, undone = rig.command("history.undo")
    assert code == 200 and undone["left"] == ["Sets the tempo to 91."] and rig.live.song.tempo == 91.0


def test_a_value_on_a_removed_device_is_not_written_to_its_namesake_on_undo(rig):
    """Two Saturators on the kick bus; the batch sets the first one's Drive and then removes it. Undo must not put
    the old Drive on the one that is left."""
    assert rig.command("live.change", {"why": "two", "steps": [{"add": "Saturator", "track": KICK}] * 2})[0] == 200
    second = rig.track(KICK).devices[-1]
    drive = next(p for p in second.parameters if p.name == "Drive")
    drive.value = 9.0
    code, reply = run(
        rig,
        {
            "why": "one less",
            "steps": [
                {"set": "Kick bus/Saturator/Drive", "to": 4.0},
                {"set": "Kick bus/Saturator#2/Drive", "to": 7.0},
                {"remove": "Saturator", "track": KICK},
            ],
        },
    )
    assert code == 200 and reply["removed"] == [{"track": KICK, "device": "Saturator"}], reply
    row = rig.desk.history.entries[-1]
    assert [m["key"] for m in row["moves"]] == ["Kick bus/Saturator/Drive"]  # the one that is left, by its name now
    assert drive.value == 7.0
    code, undone = rig.command("history.undo")
    assert code == 200 and undone["missing"] == [] and drive.value == 9.0  # its own value back, not the other's


def test_a_failing_step_stops_the_batch_and_the_row_keeps_what_was_done(rig):
    code, reply = run(
        rig,
        {
            "why": "half",
            "steps": [
                {"set": VOL, "to": 0.5},
                {"remove": "desk Sat", "track": HATS},
                {"code": "song.tempo = 91.0\nraise ValueError('no such clip')", "does": "Breaks half way."},
                {"new_track": "audio", "name": "Never"},
                {"set": GAIN, "to": 3.0},
            ],
        },
    )
    assert code == 502 and reply["ok"] is False and reply["done"] == 2, reply
    assert reply["failed"]["step"] == 3 and "no such clip" in reply["failed"]["why"] and reply["not_done"] == [3, 4, 5]
    assert "part of the code may have run" in reply["failed"]["why"]
    assert reply["ran"] == [{"step": 3, "ok": False, "result": None}]
    assert reply["undo"] == "half (1 control)"
    assert reply["no_undo"][0] == "Removed desk Sat from Hats bus" and "may have run" in reply["no_undo"][1]
    song = rig.live.song
    assert song.tempo == 91.0  # the fake ran the first line: the app cannot know, so the row says "may have run"
    assert "Never" not in [t.name for t in song.tracks] and param(rig, KICK, "desk EQ", "1 Gain A").value == 0.0
    row = rig.desk.history.entries[-1]
    assert row["k"] == "change" and row["stays"][1]["failed"] is True
    code, undone = rig.command("history.undo")
    assert code == 200 and len(undone["left"]) == 2 and "desk Sat" not in names(rig, HATS)


def test_a_track_that_live_does_not_make_fails_its_step(rig, monkeypatch):
    def refuses(client, kind, pause=None):
        raise newtrack.NewTrackError("Live did not make the audio track (the set had 20 and has 20)")

    monkeypatch.setattr(newtrack, "create", refuses)
    code, reply = run(rig, {"why": "t", "steps": [{"new_track": "audio", "name": "Parallel"}, {"set": VOL, "to": 0.5}]})
    assert code == 502 and reply["done"] == 0 and "did not make" in reply["failed"]["why"]
    assert reply["undo"] is None and reply["no_undo"] == [] and rig.desk.history.entries[-1]["k"] == "checkpoint"


def test_a_proposal_that_changes_nothing_leaves_no_row(rig):
    vol = rig.track(KICK).mixer_device.volume.value
    code, reply = run(rig, {"why": "same", "steps": [{"set": VOL, "to": vol}]})
    assert code == 200 and reply["undo"] is None and reply["no_undo"] == [] and rig.desk.history.entries == []


# ---- the steps of a removed device, taken out of the entry -------------------------------------------------------


def play(chain_: list[str], steps: list[dict]) -> list[str]:
    out = list(chain_)
    for s in steps:
        if s["op"] == "add":
            out.insert(s["at"], s["device"])
        elif s["op"] == "remove":
            assert out.pop(s["at"]) == s["device"]
        else:
            assert out[s["from"]] == s["device"]
            out.insert(s["to"], out.pop(s["from"]))
    return out


def test_taken_out_rewrites_the_steps_as_if_the_device_had_never_been_there():
    rnd = random.Random(7)
    for _ in range(400):
        start = [f"d{k}" for k in range(rnd.randint(1, 5))]
        now, steps = list(start), []
        for k in range(rnd.randint(0, 6)):
            if rnd.random() < 0.5 or len(now) < 2:
                step = {"op": "add", "track": "T", "device": f"n{k}", "at": rnd.randint(0, len(now))}
            else:
                a, b = rnd.sample(range(len(now)), 2)
                step = {"op": "move", "track": "T", "device": now[a], "from": a, "to": b}
            steps.append(step)
            now = play(now, [step])
        other = {"op": "add", "track": "U", "device": "x", "at": 0}  # another track's step is left alone
        gone = rnd.randrange(len(now))
        name = now[gone]
        rest = history.taken_out([*steps, other], "T", gone)
        assert other in rest and all(s["device"] != name for s in rest)
        left = [d for d in now if d != name]
        was = [d for d in start if d != name]
        mine = [s for s in rest if s["track"] == "T"]
        assert play(was, mine) == left, (start, steps, gone)  # a redo lands where the batch left the others
        assert play(left, history.turned(mine)) == was, (start, steps, gone)  # an undo puts the others back
