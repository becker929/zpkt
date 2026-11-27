"""Steps on the bus: the step sequencer's commands (zpkt.app.steps_commands) on FakeLive. A pattern is an
Arrangement MIDI clip; the monitor's tracks are never touched; an agent may read and not change."""

from __future__ import annotations

import pytest

from zpkt.app.bus import Command
from zpkt.live import steps

KICK, SNARE, HAT = 36, 38, 42
KIT = "909 Core Kit"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(steps.time, "sleep", lambda s: None)


def ask(rig, kind, args=None, who="you", **kw):
    return rig.desk.bus.submit(Command(kind, who, args or {}, **kw))


@pytest.fixture()
def drums(rig):
    """The rig with a drum track made the way the page makes it."""
    code, made = ask(rig, "steps.new_track", {"name": "Drums", "kit": KIT})
    assert code == 200, made
    return rig


def notes(rig, name="Drums"):
    """Every note on a track's Arrangement clips: (clip start, pitch, start in the clip, velocity)."""
    track = rig.track(name)
    return sorted((c.start_time, n.pitch, n.start_time, n.velocity) for c in track.arrangement_clips for n in c._notes)


def clips(rig, name="Drums"):
    return [(c.start_time, c.end_time) for c in rig.track(name).arrangement_clips]


# ---- a drum track ---------------------------------------------------------------------------------------------------


def test_the_kits_are_read_once_and_kept(rig):
    code, got = ask(rig, "steps.kits")
    assert code == 200 and got["kits"] == ["606 Core Kit", "707 Core Kit", "808 Core Kit", KIT]
    calls = len(rig.live.calls)
    assert ask(rig, "steps.kits")[1]["kits"] == got["kits"] and len(rig.live.calls) == calls  # kept
    assert ask(rig, "steps.kits", {"fresh": True})[0] == 200 and len(rig.live.calls) == calls + 1
    assert ask(rig, "steps.kits", who="agent")[0] == 200  # a read: an agent may


def test_a_new_drum_track_is_made_before_the_monitor_tracks_and_the_song_gives_it_a_lane(rig):
    assert ask(rig, "steps.tracks")[1]["tracks"] == []  # the set has no MIDI track
    before = [t.name for t in rig.live.song.tracks]
    first_monitor = next(i for i, n in enumerate(before) if n.startswith("mon "))
    code, made = ask(rig, "steps.new_track", {"name": "Drums", "kit": KIT})
    assert code == 200 and made == {
        "ok": True,
        "entry": made["entry"],
        "track": "Drums",
        "index": first_monitor,
        "kit": KIT,
        "device": KIT,
        "no_undo": ["New drum track Drums (909 Core Kit)"],
    }
    after = [t.name for t in rig.live.song.tracks]
    assert after == [*before[:first_monitor], "Drums", *before[first_monitor:]]
    assert ask(rig, "steps.tracks")[1]["tracks"] == [
        {"name": "Drums", "index": first_monitor, "color": "", "drum_rack": True}
    ]
    assert ask(rig, "steps.sounds", {"track": "Drums"})[1]["sounds"][:3] == [
        {"pitch": 36, "name": "Kick"},
        {"pitch": 37, "name": "Rim"},
        {"pitch": 38, "name": "Snare"},
    ]
    # the Song: every track says whether it takes MIDI, so an empty MIDI track can have a lane
    song = ask(rig, "arrangement.read")[1]
    lane = next(t for t in song["tracks"] if t["name"] == "Drums")
    assert (lane["midi"], lane["drum_rack"], lane["regions"]) == (True, True, [])
    assert [t["midi"] for t in song["tracks"] if t["name"] != "Drums"] == [False] * (len(song["tracks"]) - 1)


def test_a_new_track_is_refused_whole_for_a_bad_name_a_missing_kit_or_a_name_that_is_taken(drums):
    rig = drums
    count = len(rig.live.song.tracks)
    for args, code, why in [
        ({"name": "Drums", "kit": KIT}, 400, "already has a track called 'Drums'"),
        ({"name": "Drums 2", "kit": "No such kit"}, 400, "no kit 'No such kit'"),
        ({"name": "mon D", "kit": KIT}, 403, "keeps for itself"),
        ({"name": "Main", "kit": KIT}, 403, "keeps for itself"),
        ({"name": "a/b", "kit": KIT}, 400, "no '/'"),
        ({"name": "", "kit": KIT}, 400, "needs 'name'"),
        ({"name": "Drums 2"}, 400, "needs 'kit'"),
    ]:
        got = ask(rig, "steps.new_track", args)
        assert got[0] == code and why in got[1]["error"], (args, got)
    assert len(rig.live.song.tracks) == count


# ---- reading and flipping steps -------------------------------------------------------------------------------------


def test_read_gives_a_row_for_every_sound_of_the_kit_and_which_bars_hold_a_clip_of_that_length(drums):
    rig = drums
    code, got = ask(rig, "steps.read", {"track": "Drums", "bar": 5, "bars": 1, "total_bars": 40})
    assert code == 200 and got["ok"] and (got["track"], got["bar"], got["bars"]) == ("Drums", 5, 1)
    assert [r["name"] for r in got["pattern"]["rows"]] == ["Kick", "Rim", "Snare", "Clap", "Hat", "Open"]
    assert all(r["steps"] == [0] * 16 for r in got["pattern"]["rows"])
    assert got["sounds"] == [{"pitch": r["pitch"], "name": r["name"]} for r in got["pattern"]["rows"]]
    assert got["drum_rack"] is True and got["clip"] is None and got["blocked"] == [] and got["painted"] == []
    assert got["hash"] == steps.content_hash([]) and got["beats_per_bar"] == 4.0 and got["total_bars"] == 40
    assert ask(rig, "steps.read", {"track": "Drums", "bar": 5, "bars": 1}, who="agent")[0] == 200  # a read


def test_a_toggle_flips_one_step_in_lives_arrangement_clip(drums):
    rig = drums
    span = {"track": "Drums", "bar": 5, "bars": 1}
    code, on = ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": 0})
    assert code == 200 and on == {"ok": True, "on": True, "velocity": 100, "created": True, "entry": on["entry"]}
    assert clips(rig) == [(16.0, 20.0)] and notes(rig) == [(16.0, KICK, 0.0, 100)]
    assert ask(rig, "steps.toggle", {**span, "pitch": HAT, "step": 6, "velocity": 64})[1]["created"] is False
    assert notes(rig) == [(16.0, KICK, 0.0, 100), (16.0, HAT, 1.5, 64)]
    got = ask(rig, "steps.read", span)[1]
    rows = {r["pitch"]: r["steps"] for r in got["pattern"]["rows"]}
    assert rows[KICK][0] == 100 and rows[HAT][6] == 64 and sum(map(sum, rows.values())) == 164
    assert got["clip"]["start"] == 16.0 and got["painted"] == [{"bar": 5, "hash": got["hash"], "name": ""}]
    off = ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": 0})[1]
    assert off["on"] is False and notes(rig) == [(16.0, HAT, 1.5, 64)]


def test_a_track_with_no_drum_rack_offers_the_pitches_with_notes_or_c1_to_g1(rig):
    rig.conn.run("t = song.create_midi_track(0)\nt.name = 'Bass'\nresult = 1")
    got = ask(rig, "steps.read", {"track": "Bass", "bar": 1, "bars": 1})[1]
    assert [r["pitch"] for r in got["pattern"]["rows"]] == list(range(36, 44)) and got["drum_rack"] is False
    assert [r["name"] for r in got["pattern"]["rows"]][:2] == ["C1", "C#1"]
    ask(rig, "steps.toggle", {"track": "Bass", "bar": 1, "bars": 1, "pitch": 50, "step": 2})
    got = ask(rig, "steps.read", {"track": "Bass", "bar": 1, "bars": 1})[1]
    assert [(r["pitch"], r["name"]) for r in got["pattern"]["rows"]] == [(50, "D2")]


def test_clips_in_the_way_refuse_the_toggle_and_nothing_changes(drums):
    rig = drums
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(0.0, 8.0)\nresult = 1")
    code, got = ask(rig, "steps.toggle", {"track": "Drums", "bar": 1, "bars": 1, "pitch": KICK, "step": 0})
    assert code == 409 and got["error"] == "clips are in the way"
    assert [(c["start"], c["end"]) for c in got["blocked"]] == [(0.0, 8.0)]
    assert clips(rig) == [(0.0, 8.0)] and notes(rig) == []
    read = ask(rig, "steps.read", {"track": "Drums", "bar": 1, "bars": 1})[1]
    assert [(c["start"], c["end"]) for c in read["blocked"]] == [(0.0, 8.0)] and read["clip"] is None


# ---- the rails ------------------------------------------------------------------------------------------------------


def test_no_command_touches_a_monitor_track(rig):
    rig.conn.run("t = song.create_midi_track(-1)\nt.name = 'mon X'\nresult = 1")
    assert ask(rig, "steps.tracks")[1]["tracks"] == []  # never offered
    calls = len(rig.live.calls)
    for kind, args in [
        ("steps.sounds", {"track": "mon X"}),
        ("steps.read", {"track": "mon X", "bar": 1, "bars": 1}),
        ("steps.toggle", {"track": "mon X", "bar": 1, "bars": 1, "pitch": KICK, "step": 0}),
    ]:
        code, got = ask(rig, kind, args)
        assert code == 403 and "monitor" in got["error"], kind
    # nothing about that track was sent to Live (the wrong-set guard's own question aside)
    assert not [c for c in rig.live.calls[calls:] if "mon X" in c.code] and rig.track("mon X").arrangement_clips == ()


def test_an_agent_may_read_and_may_not_change(drums):
    rig = drums
    span = {"track": "Drums", "bar": 1, "bars": 1}
    for kind, args in [("steps.tracks", {}), ("steps.sounds", {"track": "Drums"}), ("steps.read", span)]:
        assert ask(rig, kind, args, who="agent")[0] == 200, kind
    for kind, args in [
        ("steps.toggle", {**span, "pitch": KICK, "step": 0}),
        ("steps.new_track", {"name": "Drums 2", "kit": KIT}),
    ]:
        code, got = ask(rig, kind, args, who="agent")
        assert code == 403 and "agent" in got["error"].lower(), kind
    assert notes(rig) == [] and "Drums 2" not in [t.name for t in rig.live.song.tracks]
    assert ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": 0}, who="cli")[0] == 200  # the API's callers may


def test_a_change_is_refused_when_live_has_another_set_open(drums):
    rig = drums
    rig.desk.bus.guard.forget()
    rig.desk.bus.guard.open_set = lambda: "Another set"
    code, got = ask(rig, "steps.toggle", {"track": "Drums", "bar": 1, "bars": 1, "pitch": KICK, "step": 0})
    assert code == 409 and "Another set" in got["error"] and notes(rig) == []
    assert ask(rig, "steps.read", {"track": "Drums", "bar": 1, "bars": 1})[0] == 200  # a read looks at what is open


def test_what_is_asked_wrong_is_a_400_that_says_so(drums):
    rig = drums
    span = {"track": "Drums", "bar": 1, "bars": 1}
    for kind, args, why in [
        ("steps.read", {"track": "Nobody", "bar": 1, "bars": 1}, "no track, return or Main named 'Nobody'"),
        (
            "steps.toggle",
            {"track": "kick", "bar": 1, "bars": 1, "pitch": KICK, "step": 0},
            "'kick' is not a MIDI track",
        ),
        ("steps.read", {"track": "Drums", "bar": 1, "bars": 3}, "1, 2 or 4 bars"),
        ("steps.read", {"track": "Drums", "bar": 0, "bars": 1}, "a bar"),
        ("steps.toggle", {**span, "pitch": KICK, "step": 16}, "a step"),
        ("steps.toggle", {**span, "pitch": KICK}, "needs 'step'"),
        ("steps.toggle", {**span, "pitch": KICK, "step": 0, "velocity": 200}, "a velocity"),
        ("steps.read", {"bar": 1, "bars": 1}, "needs 'track'"),
    ]:
        code, got = ask(rig, kind, args)
        assert code == 400 and why in got["error"], (kind, args, got)
    assert notes(rig) == []


# ---- the focus: what the sequencer is editing, for every page and for the MiniLab ------------------------------------


def heard(q, kind="steps"):
    return [m for m in list(q.queue) if m.get("t") == kind]


def asked(rig):
    """How many times Live was asked, the MiniLab's lights aside: the pager is told the focus's steps on a thread
    of its own (zpkt.app.steps_minilab), whenever that suits it."""
    return len([c for c in rig.live.calls if "m.DESK.steps_layer" not in c.code])


def test_the_focus_holds_the_chosen_sounds_steps_and_reaches_every_page(drums):
    rig = drums
    span = {"track": "Drums", "bar": 5, "bars": 1}
    ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": 0})
    ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": 4, "velocity": 90})
    old_page, shell = rig.desk.subscribe(), rig.desk.subscribe(app=True)  # the MIDI adapter listens as the first does
    code, got = ask(rig, "steps.focus", {**span, "pitch": KICK, "velocity": 110, "length": 2.0, "swing": 0.0})
    want = {
        "track": "Drums",
        "bar": 5,
        "bars": 1,
        "steps_per_bar": 16,
        "view": 0,
        "pitch": KICK,
        "name": "Kick",
        "velocity": 110,
        "length": 2.0,
        "swing": 0.0,
        "steps": [100, 0, 0, 0, 90, *[0] * 11],
        "blocked": False,
        "rev": 1,
    }
    assert code == 200 and got == {"ok": True, "focus": want}
    assert heard(old_page) == heard(shell) == [{"t": "steps", "focus": want}]
    assert rig.state()["steps"] == want  # a page that loads now has it

    # a pad press needs nothing but the focus and a step number
    f = rig.state()["steps"]
    pad = 6
    press = {k: f[k] for k in ("track", "bar", "bars", "pitch", "velocity", "length", "swing")}
    assert ask(rig, "steps.toggle", {**press, "step": f["view"] * f["steps_per_bar"] + pad}, who="minilab")[0] == 200
    after = rig.state()["steps"]
    assert after["steps"][pad] == 110 and after["rev"] == 2  # kept up with no further read
    last = heard(shell)[-1]
    assert last["focus"] == after and last["edit"] == {"track": "Drums", "bar": 5, "bars": 1, "what": "toggle"}
    assert (16.0, KICK, 1.5, 110) in notes(rig)
    ask(rig, "steps.toggle", {**press, "step": pad}, who="minilab")
    assert rig.state()["steps"]["steps"][pad] == 0

    # a part is enough once there is a focus: another sound is read from Live, a knob's value is not
    ask(rig, "steps.toggle", {**span, "pitch": HAT, "step": 2, "velocity": 64})
    calls = asked(rig)
    hat = ask(rig, "steps.focus", {"pitch": HAT, "src": "page-1"})[1]["focus"]
    assert (hat["name"], hat["steps"][2], hat["velocity"], hat["bar"]) == ("Hat", 64, 110, 5)
    assert asked(rig) == calls + 1 and heard(shell)[-1]["src"] == "page-1"
    calls = asked(rig)
    softer = ask(rig, "steps.focus", {"velocity": 70})[1]["focus"]
    assert softer["velocity"] == 70 and softer["steps"] == hat["steps"] and asked(rig) == calls
    # a page that has just read the pattern hands the steps over, and Live is not asked
    given = ask(rig, "steps.focus", {**span, "bar": 6, "pitch": KICK, "steps": [0] * 16, "blocked": False})[1]["focus"]
    assert given["bar"] == 6 and given["steps"] == [0] * 16 and asked(rig) == calls

    # {} lets it go
    code, got = ask(rig, "steps.focus", {})
    assert code == 200 and got["focus"] is None and rig.state()["steps"] is None
    assert heard(shell)[-1] == {"t": "steps", "focus": None}
    assert ask(rig, "steps.focus", {"pitch": HAT})[0] == 400  # a part of nothing is not a focus


def test_the_focus_is_the_persons_and_never_on_a_monitor_track(drums):
    rig = drums
    whole_focus = {"track": "Drums", "bar": 1, "bars": 1, "pitch": KICK}
    assert ask(rig, "steps.focus", whole_focus, who="agent")[0] == 403
    assert ask(rig, "steps.focus", {**whole_focus, "track": "mon A"})[0] == 403
    for wrong, why in [
        ({**whole_focus, "bars": 3}, "1, 2 or 4 bars"),
        ({**whole_focus, "view": 1}, "'view' is a bar of the pattern"),
        ({**whole_focus, "velocity": 0}, "a velocity"),
        ({**whole_focus, "swing": 0.9}, "swing"),
        ({**whole_focus, "track": "Nobody"}, "no track"),
    ]:
        code, got = ask(rig, "steps.focus", wrong)
        assert code == 400 and why in got["error"], wrong
    assert rig.state()["steps"] is None


def test_the_loop_goes_to_the_patterns_bars_and_back(drums):
    rig = drums
    song = rig.live.song
    before = (song.loop, song.loop_start, song.loop_length)
    code, got = ask(rig, "steps.loop", {"bar": 5, "bars": 2})
    assert code == 200 and got["was"] == {"on": before[0], "start": before[1], "length": before[2]}
    assert (song.loop, song.loop_start, song.loop_length) == (True, 16.0, 8.0)
    assert [e["what"] for e in rig.desk.history.entries] == ["track"]  # the transport: no row of its own
    assert ask(rig, "steps.loop", {"was": got["was"]})[0] == 200
    assert (song.loop, song.loop_start, song.loop_length) == before
    assert ask(rig, "steps.loop", {"bar": 5, "bars": 2}, who="agent")[0] == 403
    assert ask(rig, "steps.loop", {"bar": 0})[0] == 400 and ask(rig, "steps.loop", {"was": 3})[0] == 400


def test_an_agent_reads_the_focus_in_the_desks_state(asked, monkeypatch):
    rig = asked.rig
    assert ask(rig, "desk.state", who="agent")[1]["steps"] is None
    ask(rig, "steps.new_track", {"name": "Drums", "kit": KIT})
    ask(rig, "steps.focus", {"track": "Drums", "bar": 2, "bars": 1, "pitch": SNARE})
    got = ask(rig, "desk.state", who="agent")[1]["steps"]
    assert (got["track"], got["bar"], got["name"], got["steps"]) == ("Drums", 2, "Snare", [0] * 16)


# ---- painting the pattern along the track ---------------------------------------------------------------------------


def beat(rig, bar=1, steps_on=(0, 4, 8, 12), pitch=KICK):
    for step in steps_on:
        assert (
            ask(rig, "steps.toggle", {"track": "Drums", "bar": bar, "bars": 1, "pitch": pitch, "step": step})[0] == 200
        )


def test_paint_stamps_the_clip_and_the_reply_says_which_bars_hold_the_pattern(drums):
    rig = drums
    beat(rig)
    mine = ask(rig, "steps.read", {"track": "Drums", "bar": 1, "bars": 1})[1]["hash"]
    code, got = ask(
        rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2, 3, 5, 1], "total_bars": 40}
    )
    assert code == 200 and got["painted"] == [2, 3, 5] and got["replaced"] == []
    assert got["skipped"] == [{"bar": 1, "why": "the bars painted from"}]
    assert got["clips"] == [{"bar": b, "hash": mine, "name": ""} for b in (1, 2, 3, 5)]
    assert clips(rig) == [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0), (16.0, 20.0)]
    # another pattern on bar 3: the same length, another hash; painting over it replaces it
    ask(rig, "steps.toggle", {"track": "Drums", "bar": 3, "bars": 1, "pitch": SNARE, "step": 4})
    other = ask(rig, "steps.read", {"track": "Drums", "bar": 3, "bars": 1})[1]
    assert other["hash"] != mine and {c["bar"]: c["hash"] for c in other["painted"]}[3] == other["hash"]
    again = ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [3]})[1]
    assert again["painted"] == [3] and again["replaced"] == [3]
    assert {c["bar"]: c["hash"] for c in again["clips"]} == dict.fromkeys((1, 2, 3, 5), mine)


def test_erase_deletes_the_copies_and_skips_what_is_not_one(drums):
    rig = drums
    beat(rig)
    ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2, 3, 4]})
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(16.0, 8.0)\nresult = 1")
    code, got = ask(rig, "steps.erase", {"track": "Drums", "bars": [3, 4, 5, 9], "length": 1})
    assert code == 200 and got["erased"] == [3, 4]
    assert [(k["bar"], k["why"]) for k in got["skipped"]] == [
        (5, "a clip of another length is in the way"),
        (9, "no clip there"),
    ]
    assert [c["bar"] for c in got["clips"]] == [1, 2] and clips(rig) == [(0.0, 4.0), (4.0, 8.0), (16.0, 24.0)]
    # painting onto the long clip's bars skips them: a clip is never cut
    over = ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [5, 6, 7]})[1]
    assert over["painted"] == [7] and [k["bar"] for k in over["skipped"]] == [5, 6]


def test_paint_needs_a_clip_to_paint_from_and_the_usual_rails_hold(drums):
    rig = drums
    code, got = ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2]})
    assert code == 409 and got["error"] == "no MIDI clip covers exactly the bars to paint from" and clips(rig) == []
    beat(rig)
    for kind, args in [
        ("steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2]}),
        ("steps.erase", {"track": "Drums", "bars": [1], "length": 1}),
    ]:
        assert ask(rig, kind, args, who="agent")[0] == 403, kind
        assert ask(rig, kind, {**args, "track": "mon A"})[0] == 403, kind
    assert ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": []})[0] == 400
    assert ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": list(range(2, 70))})[0] == 400
    assert ask(rig, "steps.erase", {"track": "Drums", "bars": "all", "length": 1})[0] == 400
    assert clips(rig) == [(0.0, 4.0)]


def test_the_focus_follows_a_paint_over_the_pattern_in_hand(drums):
    rig = drums
    beat(rig)
    ask(rig, "steps.focus", {"track": "Drums", "bar": 3, "bars": 1, "pitch": KICK})
    assert rig.state()["steps"]["steps"] == [0] * 16
    shell = rig.desk.subscribe(app=True)
    ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2, 3], "src": "page-9"})
    assert rig.state()["steps"]["steps"] == [100, 0, 0, 0] * 4
    told = heard(shell)[-1]
    assert told["edit"] == {"track": "Drums", "bar": 2, "bars": 2, "what": "paint"} and told["src"] == "page-9"
    ask(rig, "steps.erase", {"track": "Drums", "bars": [3], "length": 1})
    assert rig.state()["steps"]["steps"] == [0] * 16 and heard(shell)[-1]["edit"]["what"] == "erase"


# ---- a step's velocity and length; the whole pattern (swing, clear, another length) -------------------------------


def pattern_of(rig, bar=1, bars=1, **more):
    return ask(rig, "steps.read", {"track": "Drums", "bar": bar, "bars": bars, **more})[1]["pattern"]


def test_set_changes_one_steps_velocity_or_length(drums):
    rig = drums
    span = {"track": "Drums", "bar": 1, "bars": 1}
    beat(rig, steps_on=(0, 4))
    code, got = ask(rig, "steps.set", {**span, "pitch": KICK, "step": 4, "velocity": 61})
    assert code == 200 and got == {"ok": True, "on": True, "velocity": 61, "length": 1.0, "entry": got["entry"]}
    assert notes(rig) == [(0.0, KICK, 0.0, 100), (0.0, KICK, 1.0, 61)]
    got = ask(rig, "steps.set", {**span, "pitch": KICK, "step": 4, "length": 2.0})[1]
    assert got["velocity"] == 61 and got["length"] == 2.0
    clip = rig.track("Drums").arrangement_clips[0]
    assert sorted((n.start_time, n.duration) for n in clip._notes) == [(0.0, 0.25), (1.0, 0.5)]
    code, got = ask(rig, "steps.set", {**span, "pitch": KICK, "step": 5, "velocity": 61})
    assert code == 409 and got["error"] == "no note on that step"
    assert ask(rig, "steps.set", {**span, "pitch": KICK, "step": 4})[0] == 400  # neither a velocity nor a length
    assert ask(rig, "steps.set", {**span, "pitch": KICK, "step": 4, "velocity": 61}, who="agent")[0] == 403
    assert ask(rig, "steps.set", {**span, "track": "mon A", "pitch": KICK, "step": 4, "velocity": 61})[0] == 403


def test_write_puts_the_whole_pattern_swing_and_clear(drums):
    rig = drums
    beat(rig, steps_on=(0, 1, 2, 3))
    beat(rig, steps_on=(4,), pitch=SNARE)
    pattern = pattern_of(rig)
    code, got = ask(rig, "steps.write", {"track": "Drums", "bar": 1, "pattern": {**pattern, "swing": 0.5}})
    assert code == 200 and got["created"] is False and got["pattern"]["swing"] == 0.5 and got["off_grid"] == 0
    clip = rig.track("Drums").arrangement_clips[0]
    assert sorted(n.start_time for n in clip._notes if n.pitch == KICK) == [0.0, 0.375, 0.5, 0.875]  # every 2nd late
    # the swing is remembered for that pattern, so a read with no word of it puts the late steps where they are
    again = pattern_of(rig)
    assert again["swing"] == 0.5 and again["off_grid"] == 0
    assert next(r for r in again["rows"] if r["pitch"] == KICK)["steps"][:4] == [100] * 4
    # and a toggle that says nothing of swing lands a late step where the pattern has it
    ask(rig, "steps.toggle", {"track": "Drums", "bar": 1, "bars": 1, "pitch": KICK, "step": 5})
    assert 1.375 in [n.start_time for n in clip._notes if n.pitch == KICK]
    # clear one sound: its row empty, the other as it was
    cleared = {**again, "rows": [{**r, "steps": [0] * 16} if r["pitch"] == KICK else r for r in again["rows"]]}
    got = ask(rig, "steps.write", {"track": "Drums", "bar": 1, "pattern": cleared})[1]
    assert [n.pitch for n in clip._notes] == [SNARE] and got["hash"] != steps.content_hash([])
    # clear all: the clip stays, empty
    empty = {**again, "rows": [{**r, "steps": [0] * 16} for r in again["rows"]]}
    assert ask(rig, "steps.write", {"track": "Drums", "bar": 1, "pattern": empty})[1]["hash"] == steps.content_hash([])
    assert clips(rig) == [(0.0, 4.0)] and notes(rig) == []
    assert ask(rig, "steps.write", {"track": "Drums", "bar": 1, "pattern": {"bars": 3, "rows": []}})[0] == 400
    assert ask(rig, "steps.write", {"track": "Drums", "bar": 1})[0] == 400
    assert ask(rig, "steps.write", {"track": "Drums", "bar": 1, "pattern": empty}, who="agent")[0] == 403


def longer(pattern, bars):
    total = 16 * bars
    rows = [{**r, "steps": (r["steps"] + [0] * total)[:total]} for r in pattern["rows"]]
    return {**pattern, "bars": bars, "rows": [{k: v for k, v in r.items() if k != "lengths"} for r in rows]}


def test_write_changes_a_patterns_length_when_only_its_own_clip_is_in_the_way(drums):
    rig = drums
    beat(rig, bar=3)
    one = pattern_of(rig, bar=3)
    # 1 bar becomes 2: the one-bar clip goes and a two-bar clip with the same notes takes its place
    code, got = ask(rig, "steps.write", {"track": "Drums", "bar": 3, "pattern": longer(one, 2), "from_bars": 1})
    assert code == 200 and got["bars"] == 2 and got["clip"] == {"name": "", "start": 8.0, "end": 16.0}
    assert clips(rig) == [(8.0, 16.0)] and [n[2] for n in notes(rig)] == [0.0, 1.0, 2.0, 3.0]
    # 2 bars become 4 with bar 7 taken by another clip: refused, and the two-bar clip is still there
    ask(rig, "steps.toggle", {"track": "Drums", "bar": 6, "bars": 1, "pitch": SNARE, "step": 0})
    two = pattern_of(rig, bar=3, bars=2)
    code, got = ask(rig, "steps.write", {"track": "Drums", "bar": 3, "pattern": longer(two, 4), "from_bars": 2})
    assert code == 409 and got["error"] == "clips are in the way" and len(got["blocked"]) == 2
    assert clips(rig) == [(8.0, 16.0), (20.0, 24.0)] and len(notes(rig)) == 5
    # back to 1 bar: the second bar's notes are not in the pattern any more
    code, got = ask(rig, "steps.write", {"track": "Drums", "bar": 3, "pattern": longer(two, 1), "from_bars": 2})
    assert code == 200 and clips(rig) == [(8.0, 12.0), (20.0, 24.0)]


# ---- History: every change is one row, and undo puts the notes back --------------------------------------------------


def rows(rig):
    """The history's step rows, oldest first: (what, track, bar, bars, count)."""
    return [
        (e["what"], e["track"], e["bar"], e["bars"], e["count"]) for e in rig.desk.history.entries if e["k"] == "steps"
    ]


def undo(rig, who="you"):
    return ask(rig, "history.undo", who=who)


def redo(rig):
    return ask(rig, "history.redo")


def test_a_run_of_toggles_on_one_pattern_is_one_row_and_one_undo(drums):
    rig = drums
    t = [1000.0]
    rig.desk.history.clock = lambda: t[0]
    span = {"track": "Drums", "bar": 5, "bars": 1}
    for step in (0, 4, 8):
        ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": step})
        t[0] += 1.0
    ask(rig, "steps.set", {**span, "pitch": KICK, "step": 4, "velocity": 60})
    assert rows(rig) == [("track", "Drums", 1, 1, 1), ("edit", "Drums", 5, 1, 4)]  # the taps and the knob: one row
    t[0] += 20.0  # a pause: the next tap starts another row
    ask(rig, "steps.toggle", {**span, "pitch": HAT, "step": 2})
    t[0] += 1.0
    ask(
        rig, "steps.toggle", {"track": "Drums", "bar": 6, "bars": 1, "pitch": HAT, "step": 2}
    )  # another pattern: its own
    assert rows(rig)[1:] == [("edit", "Drums", 5, 1, 4), ("edit", "Drums", 5, 1, 1), ("edit", "Drums", 6, 1, 1)]
    full = notes(rig)
    assert len(full) == 5 and clips(rig) == [(16.0, 20.0), (20.0, 24.0)]

    code, got = undo(rig)  # bar 6's tap made its clip: the clip goes
    assert code == 200 and "notes" not in got and clips(rig) == [(16.0, 20.0)]
    undo(rig)  # the hat on bar 5
    assert notes(rig) == [(16.0, KICK, 0.0, 100), (16.0, KICK, 1.0, 60), (16.0, KICK, 2.0, 100)]
    undo(rig)  # the whole run of four: the clip it made goes too
    assert clips(rig) == [] and notes(rig) == []
    redo(rig)
    assert notes(rig) == [(16.0, KICK, 0.0, 100), (16.0, KICK, 1.0, 60), (16.0, KICK, 2.0, 100)]
    redo(rig)
    redo(rig)
    assert notes(rig) == full and clips(rig) == [(16.0, 20.0), (20.0, 24.0)]
    assert redo(rig)[1]["entry"] is None  # nothing more to redo
    # a tap by another hand is a row of its own
    ask(rig, "steps.toggle", {**span, "pitch": HAT, "step": 3}, who="minilab")
    t[0] += 1.0
    ask(rig, "steps.toggle", {**span, "pitch": HAT, "step": 5})
    assert [e["who"] for e in rig.desk.history.entries][-2:] == ["minilab", "you"]


def test_undo_of_a_paint_takes_the_copies_away_and_puts_a_replaced_clip_back(drums):
    rig = drums
    beat(rig)
    ask(rig, "steps.toggle", {"track": "Drums", "bar": 3, "bars": 1, "pitch": SNARE, "step": 4, "velocity": 77})
    other = notes(rig)[-1]
    assert other == (8.0, SNARE, 1.0, 77)
    before = (clips(rig), notes(rig))
    got = ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2, 3, 4]})[1]
    assert got["painted"] == [2, 3, 4] and got["replaced"] == [3] and other not in notes(rig)
    painted = (clips(rig), notes(rig))
    assert rows(rig)[-1] == ("paint", "Drums", 1, 1, 3)
    code, got = undo(rig)
    assert code == 200 and (clips(rig), notes(rig)) == before  # bars 2 and 4 are free again, bar 3 has its snare
    redo(rig)
    assert (clips(rig), notes(rig)) == painted
    mine = ask(rig, "steps.read", {"track": "Drums", "bar": 1, "bars": 1})[1]
    assert {c["bar"]: c["hash"] for c in mine["painted"]} == dict.fromkeys(
        (1, 2, 3, 4), mine["hash"]
    )  # still the pattern


def test_undo_of_an_erase_puts_the_clips_back_with_their_names(drums):
    rig = drums
    beat(rig)
    ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2, 3]})
    rig.conn.run(
        "t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.arrangement_clips[1].name = 'mine'\nresult = 1"
    )
    before = (clips(rig), notes(rig))
    assert ask(rig, "steps.erase", {"track": "Drums", "bars": [2, 3], "length": 1})[1]["erased"] == [2, 3]
    assert clips(rig) == [(0.0, 4.0)] and rows(rig)[-1] == ("erase", "Drums", 2, 1, 2)
    undo(rig)
    assert (clips(rig), notes(rig)) == before
    assert [c.name for c in rig.track("Drums").arrangement_clips] == ["", "mine", ""]
    redo(rig)
    assert clips(rig) == [(0.0, 4.0)]


def test_undo_of_a_write_and_of_a_change_of_length(drums):
    rig = drums
    t = [1000.0]
    rig.desk.history.clock = lambda: t[0]
    beat(rig, bar=3)
    t[0] += 60.0
    one = pattern_of(rig, bar=3)
    was = (clips(rig), notes(rig))
    empty = {**one, "rows": [{**r, "steps": [0] * 16} for r in one["rows"]]}
    ask(rig, "steps.write", {"track": "Drums", "bar": 3, "pattern": empty})  # clear
    assert notes(rig) == [] and rows(rig)[-1] == ("edit", "Drums", 3, 1, 1)
    undo(rig)
    assert (clips(rig), notes(rig)) == was
    t[0] += 60.0
    ask(rig, "steps.write", {"track": "Drums", "bar": 3, "pattern": longer(one, 2), "from_bars": 1})
    assert clips(rig) == [(8.0, 16.0)] and rows(rig)[-1] == ("length", "Drums", 3, 2, 1)
    ask(rig, "steps.toggle", {"track": "Drums", "bar": 3, "bars": 2, "pitch": SNARE, "step": 20})
    assert len(notes(rig)) == 5
    undo(rig)  # the tap in the second bar
    undo(rig)  # the length: the two-bar clip goes, the one-bar clip is back
    assert (clips(rig), notes(rig)) == was
    redo(rig)
    redo(rig)
    assert clips(rig) == [(8.0, 16.0)] and len(notes(rig)) == 5


def test_going_back_to_before_a_step_takes_every_later_pattern_change_back_as_one(drums):
    rig = drums
    t = [1000.0]
    rig.desk.history.clock = lambda: t[0]
    beat(rig)
    t[0] += 60.0
    first = (clips(rig), notes(rig))
    ask(rig, "steps.paint", {"track": "Drums", "from_bar": 1, "bars": 1, "to": [2, 3]})
    target = rig.desk.history.entries[-1]["id"]
    t[0] += 60.0
    ask(rig, "steps.toggle", {"track": "Drums", "bar": 2, "bars": 1, "pitch": SNARE, "step": 4})
    t[0] += 60.0
    ask(rig, "steps.erase", {"track": "Drums", "bars": [3], "length": 1})
    later = (clips(rig), notes(rig))
    assert ask(rig, "history.back", {"entry": target})[0] == 200
    assert (clips(rig), notes(rig)) == first  # as it was before the paint
    assert rig.desk.history.entries[-1]["k"] == "revert" and len(rig.desk.history.entries[-1]["spans"]) == 2
    undo(rig)  # one undo reverses the going back
    assert (clips(rig), notes(rig)) == later


def test_a_new_track_is_a_row_that_undo_leaves_and_says_so(drums):
    rig = drums
    entry = rig.desk.history.entries[-1]
    assert (entry["k"], entry["what"], entry["track"], entry["kit"]) == ("steps", "track", "Drums", KIT)
    assert entry["stays"] == [
        {"op": "track", "kind": "midi", "name": "Drums", "words": "New drum track Drums (909 Core Kit)"}
    ]
    code, got = undo(rig)
    assert code == 200 and got["left"] == ["New drum track Drums (909 Core Kit)"]
    assert "Drums" in [t.name for t in rig.live.song.tracks]  # still there


def test_an_undo_that_finds_clips_in_the_way_leaves_that_span_and_says_so(drums):
    rig = drums
    beat(rig, bar=2)
    ask(rig, "steps.erase", {"track": "Drums", "bars": [2], "length": 1})
    rig.conn.run("t = [t for t in song.tracks if t.name == 'Drums'][0]\nt.create_midi_clip(0.0, 8.0)\nresult = 1")
    code, got = undo(rig)
    assert code == 200 and got["notes"] == ["Drums, bar 2: clips are in the way"]
    assert clips(rig) == [(0.0, 8.0)]  # the long clip is as it was


def test_an_undo_tells_the_pages_and_keeps_the_focus_true(drums):
    rig = drums
    span = {"track": "Drums", "bar": 1, "bars": 1}
    ask(rig, "steps.focus", {**span, "pitch": KICK})
    ask(rig, "steps.toggle", {**span, "pitch": KICK, "step": 0})
    assert rig.state()["steps"]["steps"][0] == 100
    shell = rig.desk.subscribe(app=True)
    undo(rig)
    assert rig.state()["steps"]["steps"] == [0] * 16
    told = [m for m in heard(shell) if m.get("edit")]
    assert (
        told and told[-1]["edit"] == {"track": "Drums", "bar": 1, "bars": 1, "what": "undo"} and "src" not in told[-1]
    )
    assert any(m["t"] == "hist" for m in list(shell.queue))
    assert undo(rig, who="agent")[0] == 403  # an agent does not undo either
