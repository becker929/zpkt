"""zpkt.live.steps: the step grid's arithmetic (no Live), then every function on FakeLive: a pattern read from and
written to an Arrangement clip, one step flipped, the clip painted across bars, erased, and found again."""

from __future__ import annotations

import itertools

import pytest

from zpkt.live import steps
from zpkt.live.testing import FakeLive, fake_set, lom
from zpkt.live.transport import LiveError

KICK, SNARE, HAT = 36, 38, 42


def row(pitch: int, on: dict[int, int], total: int = 16, name: str | None = None) -> dict:
    return {
        "pitch": pitch,
        "name": name or steps.note_name(pitch),
        "steps": [on.get(k, 0) for k in range(total)],
    }


def pattern(rows: list[dict], bars: int = 1, steps_per_bar: int = 16, **more) -> dict:
    return {"bars": bars, "steps_per_bar": steps_per_bar, "rows": rows, "length": 1.0, **more}


FOUR = pattern([row(KICK, {0: 110, 4: 100, 8: 100, 12: 100}), row(HAT, {2: 80, 6: 80, 10: 80, 14: 60})])


# --------------------------------------------------------------------------- the grid, without Live


def test_a_bar_of_sixteen_steps_in_four_four_is_quarter_beat_notes_in_order():
    assert steps.to_notes(FOUR) == [
        (KICK, 0.0, 0.25, 110),
        (HAT, 0.5, 0.25, 80),
        (KICK, 1.0, 0.25, 100),
        (HAT, 1.5, 0.25, 80),
        (KICK, 2.0, 0.25, 100),
        (HAT, 2.5, 0.25, 80),
        (KICK, 3.0, 0.25, 100),
        (HAT, 3.5, 0.25, 60),
    ]


def test_three_four_time_has_three_beats_to_the_bar():
    waltz = pattern([row(KICK, {0: 100, 4: 90, 8: 90}, total=12)], steps_per_bar=12)
    assert steps.to_notes(waltz, 3.0) == [(KICK, 0.0, 0.25, 100), (KICK, 1.0, 0.25, 90), (KICK, 2.0, 0.25, 90)]
    back = steps.from_notes(steps.to_notes(waltz, 3.0), 1, 12, 3.0)
    assert back["rows"][0]["steps"] == waltz["rows"][0]["steps"] and back["off_grid"] == 0
    # sixteen steps in a bar of three beats: each is 3/16 of a beat
    assert steps.to_notes(pattern([row(KICK, {1: 100, 15: 100})]), 3.0) == [
        (KICK, 0.1875, 0.1875, 100),
        (KICK, 2.8125, 0.1875, 100),
    ]


@pytest.mark.parametrize("bars", [2, 4])
def test_two_and_four_bars_run_on_past_the_first_bar(bars):
    total = 16 * bars
    long = pattern([row(KICK, {0: 100, total - 1: 90}, total=total)], bars=bars, length=2.0)
    notes = steps.to_notes(long)
    assert notes == [(KICK, 0.0, 0.5, 100), (KICK, 4.0 * bars - 0.25, 0.25, 90)]  # the last note stops at the end
    back = steps.from_notes(notes, bars, 16, 4.0)
    assert back["rows"][0]["steps"] == long["rows"][0]["steps"] and back["bars"] == bars


def test_swing_delays_every_second_step_and_the_delayed_note_still_ends_in_its_step():
    swung = pattern([row(HAT, {0: 100, 1: 90, 2: 100, 3: 90})], swing=0.5)
    assert steps.to_notes(swung) == [
        (HAT, 0.0, 0.25, 100),
        (HAT, 0.375, 0.125, 90),
        (HAT, 0.5, 0.25, 100),
        (HAT, 0.875, 0.125, 90),
    ]
    # a short note under a long delay still sounds for a quarter step
    assert steps.to_notes(pattern([row(HAT, {1: 90})], swing=0.75, length=0.25)) == [(HAT, 0.4375, 0.0625, 90)]
    assert steps.late(3, 0.5) == 0.5 and steps.late(4, 0.5) == 0.0


def test_swing_is_not_guessed_back_but_a_known_swing_reads_each_step_where_it_was_put():
    swung = pattern([row(HAT, {0: 100, 1: 90, 2: 100, 3: 90})], swing=0.5)
    notes = steps.to_notes(swung)
    guessed = steps.from_notes(notes, 1, 16, 4.0)
    assert guessed["rows"][0]["steps"][:4] == [100, 0, 100, 0] and guessed["off_grid"] == 2 and guessed["swing"] == 0.0
    known = steps.from_notes(notes, 1, 16, 4.0, swing=0.5)
    assert known == {**steps.check(swung), "off_grid": 0}
    # a little swing stays on the grid without being told
    light = steps.to_notes(pattern([row(HAT, {1: 90})], swing=0.2))
    assert steps.from_notes(light, 1, 16, 4.0)["rows"][0]["steps"][1] == 90


def test_notes_snap_to_the_nearest_step_and_the_rest_is_counted():
    played = [
        (KICK, 0.03, 0.25, 100),  # a little late: step 0
        (KICK, 0.95, 0.25, 90.4),  # a little early: step 4, and Live's velocities are floats
        (KICK, 1.0, 0.25, 70),  # step 4 is taken
        (SNARE, 1.1, 0.25, 80),  # more than a quarter step (0.0625 beat) from steps 4 and 5
        (SNARE, 2.0, 0.25, 80),
        (SNARE, 4.0, 0.25, 80),  # the next bar
        (SNARE, -0.2, 0.25, 80),  # before the pattern
    ]
    found = steps.from_notes(played, 1, 16, 4.0)
    assert [r["pitch"] for r in found["rows"]] == [KICK, SNARE]
    assert found["rows"][0]["steps"] == [100, 0, 0, 0, 90, *[0] * 11]
    assert found["rows"][1]["steps"] == [*[0] * 8, 80, *[0] * 7]
    assert found["off_grid"] == 4 and found["length"] == 1.0
    assert steps.from_notes([(KICK, 0.0625, 0.25, 100)], 1, 16, 4.0)["off_grid"] == 0  # exactly a quarter step off
    assert steps.from_notes([(KICK, 0.07, 0.25, 100)], 1, 16, 4.0)["off_grid"] == 1


def test_rows_follow_the_pitches_asked_for_and_other_pitches_are_counted():
    found = steps.from_notes(steps.to_notes(FOUR), 1, 16, 4.0, pitches=[HAT, SNARE], names={HAT: "Hat"})
    assert [(r["pitch"], r["name"]) for r in found["rows"]] == [(HAT, "Hat"), (SNARE, "D1")]
    assert found["rows"][1]["steps"] == [0] * 16 and found["off_grid"] == 4
    empty = steps.from_notes([], 2, 8, 4.0)
    assert empty == {"bars": 2, "steps_per_bar": 8, "rows": [], "length": 1.0, "swing": 0.0, "off_grid": 0}


def test_the_length_is_the_one_most_notes_have_and_another_note_keeps_its_own():
    notes = [(KICK, 0.0, 0.5, 100), (KICK, 1.0, 0.5, 100), (KICK, 2.0, 1.0, 100), (HAT, 0.5, 0.5, 90)]
    found = steps.from_notes(notes, 1, 16, 4.0)
    assert found["length"] == 2.0
    assert found["rows"][0]["lengths"] == [0, 0, 0, 0, 0, 0, 0, 0, 4.0, 0, 0, 0, 0, 0, 0, 0]
    assert "lengths" not in found["rows"][1]
    assert steps.to_notes(found) == sorted(notes, key=lambda n: (n[1], n[0]))


def test_a_pattern_that_is_not_one_is_refused_with_the_reason():
    for wrong, why in [
        (pattern([], bars=3), "1, 2 or 4 bars"),
        (pattern([], steps_per_bar=10), "8, 12, 16, 24 or 32 steps"),
        (pattern([row(KICK, {})], bars=2), "has 16 steps; the pattern has 32"),
        (pattern([row(KICK, {0: 128})]), "a velocity 1 to 127"),
        (pattern([row(KICK, {0: True})]), "a velocity 1 to 127"),
        (pattern([row(KICK, {}), row(KICK, {})]), "two rows have the pitch 36"),
        (pattern([row(128, {})]), "a pitch is 0 to 127"),
        (pattern([], length=0.1), "a note's length in steps is 0.25 to 16"),
        (pattern([], length=17), "a note's length in steps is 0.25 to 16"),
        (pattern([], swing=0.8), "swing .* is 0 to 0.75"),
        (pattern([{**row(KICK, {}), "lengths": [1.0]}]), "has 1 lengths"),
    ]:
        with pytest.raises(ValueError, match=why):
            steps.to_notes(wrong)
    with pytest.raises(ValueError, match="1, 2 or 4 bars"):
        steps.from_notes([], 8, 16, 4.0)


def test_defaults_names_and_a_blank_pattern():
    filled = steps.check({"bars": 1, "rows": [{"pitch": 60, "steps": [0] * 16}]})
    assert filled == pattern([row(60, {}, name="C3")], swing=0.0)
    assert [steps.note_name(p) for p in (0, 36, 61, 127)] == ["C-2", "C1", "C#3", "G8"]
    assert steps.blank(2, 8, [KICK, HAT], {KICK: "Kick"})["rows"] == [
        row(KICK, {}, total=16, name="Kick"),
        row(HAT, {}, total=16, name="F#1"),
    ]


def test_the_hash_is_of_the_notes_whatever_their_order_and_small_rounding():
    notes = steps.to_notes(FOUR)
    assert (
        steps.content_hash(notes)
        == steps.content_hash(reversed(notes))
        == steps.content_hash([[p, s + 1e-7, d, float(v)] for p, s, d, v in notes])
    )
    assert len(steps.content_hash(notes)) == 8 and steps.content_hash([]) == "811c9dc5"
    louder = [(p, s, d, v + 1) for p, s, d, v in notes]
    assert len({steps.content_hash(n) for n in (notes, louder, notes[1:], [])}) == 4


# --------------------------------------------------------------------------- on FakeLive

KIT = [  # the Drum Rack's pads, given out of order
    {"name": "Snare", "note": SNARE},
    {"name": "Kick", "note": KICK},
    {"name": "Hat", "note": HAT},
]
LONG = [[48, 0.0, 0.25, 100], [50, 4.5, 0.25, 90], [48, 7.75, 0.25, 80]]  # a two-bar clip's notes, in its own time


def rig() -> dict:
    return {
        "tempo": 160,
        "tracks": [
            {"name": "Audio", "clips": [{"start": 0.0, "length": 8.0, "file": "/fake/loop.wav"}]},
            {
                "name": "Drums",
                "type": "midi",
                "color": 0xFF8800,
                "devices": [{"device": "Drum Rack", "name": "Kit", "chains": KIT}, "Saturator"],
            },
            {
                "name": "Bass",
                "type": "midi",
                "devices": ["Operator"],
                "clips": [{"start": 16.0, "length": 8.0, "name": "long", "notes": LONG}],  # bars 5 and 6
            },
            {"name": "Empty", "type": "midi"},
            {"name": "Bus", "type": "group"},
        ],
    }


@pytest.fixture()
def live():
    fake = FakeLive(fake_set(rig()))
    yield fake
    fake.close()


def test_the_sets_midi_tracks_with_their_colour_and_whether_they_play_a_drum_rack(live):
    calls = len(live.calls)
    assert steps.midi_tracks(live) == [
        {"name": "Drums", "index": 1, "color": "#ff8800", "drum_rack": True},
        {"name": "Bass", "index": 2, "color": "", "drum_rack": False},
        {"name": "Empty", "index": 3, "color": "", "drum_rack": False},
    ]
    assert len(live.calls) == calls + 1


def test_sounds_are_a_drum_racks_filled_pads_lowest_first_and_nothing_for_another_instrument(live):
    kit = [{"pitch": KICK, "name": "Kick"}, {"pitch": SNARE, "name": "Snare"}, {"pitch": HAT, "name": "Hat"}]
    assert steps.sounds(live, "Drums") == kit and steps.sounds(live, 1) == kit
    assert steps.sounds(live, "Bass") == [] and steps.sounds(live, "Empty") == [] and steps.sounds(live, "Audio") == []
    with pytest.raises(LiveError, match="no track, return or Main named 'Nobody'"):
        steps.sounds(live, "Nobody")
    with pytest.raises(ValueError, match="a name or an index from 0"):
        steps.sounds(live, -1)


def test_a_full_drum_rack_gives_sixty_four_sounds_at_most():
    full = [{"name": f"pad {n}", "note": n} for n in range(20, 120)]
    spec = {"tracks": [{"name": "Big", "type": "midi", "devices": [{"device": "Drum Rack", "chains": full}]}]}
    with FakeLive(fake_set(spec)) as live:
        found = steps.sounds(live, "Big")
        assert len(found) == 64 and found[0] == {"pitch": 20, "name": "pad 20"} and found[-1]["pitch"] == 83


def track(live, name: str):
    return next(t for t in live.song.tracks if t.name == name)


def held(live, name: str) -> list:
    """Every clip on a track as the fake holds it: (start, end, name, its notes in the clip's own time)."""
    return [
        (c.start_time, c.end_time, c.name, sorted((n.pitch, n.start_time, n.duration, n.velocity) for n in c._notes))
        for c in track(live, name).arrangement_clips
    ]


def tidy(live) -> None:
    """What every step of this module must leave true: no two clips of a track overlap, and no call read back what
    it had just written (ableton-guide rule 1)."""
    for t in live.song.tracks:
        clips = t.arrangement_clips
        assert all(a.end_time <= b.start_time + 1e-9 for a, b in itertools.pairwise(clips)), t.name
    assert [c.readbacks for c in live.calls if c.readbacks] == []
    assert [c.error for c in live.calls if c.status != "ok"] == []


def last_lines(live, n: int) -> list[str]:
    return [c.code.splitlines()[-1] for c in live.calls[-n:]]


def test_a_free_span_reads_as_an_empty_pattern_with_no_clip(live):
    calls = len(live.calls)
    found = steps.read(live, "Drums", 3, 2, pitches=[KICK, HAT])
    assert found == {
        "pattern": {**steps.blank(2, 16, [KICK, HAT], {KICK: "Kick", HAT: "Hat"}), "off_grid": 0},
        "clip": None,
        "off_grid": 0,
        "blocked": [],
        "beats_per_bar": 4.0,
        "hash": steps.content_hash([]),
    }
    assert len(live.calls) == calls + 1
    assert steps.read(live, "Drums", 1, 1)["pattern"]["rows"] == []
    with pytest.raises(ValueError, match="1, 2 or 4 bars"):
        steps.read(live, "Drums", 1, 3)
    with pytest.raises(ValueError, match="a bar .* is 1 to"):
        steps.read(live, "Drums", 0, 1)
    assert len(live.calls) == calls + 2


def test_write_makes_a_clip_on_a_free_span_in_one_call_and_reads_it_in_a_second(live):
    calls = len(live.calls)
    done = steps.write(live, "Drums", 3, FOUR, name="beat")
    assert len(live.calls) == calls + 2
    assert [line.split("(")[0] for line in last_lines(live, 2)] == [
        "result = json.dumps",
        "result = json.dumps",
    ] and ["pattern_put" in last_lines(live, 2)[0], "pattern_look" in last_lines(live, 2)[1]] == [True, True]
    assert done == {
        "pattern": {**steps.check(FOUR), "off_grid": 0},
        "clip": {"name": "beat", "start": 8.0, "end": 12.0},
        "off_grid": 0,
        "blocked": [],
        "beats_per_bar": 4.0,
        "hash": steps.content_hash(steps.to_notes(FOUR)),
        "before": [],
        "created": True,
    }
    assert held(live, "Drums") == [(8.0, 12.0, "beat", sorted(steps.to_notes(FOUR)))]
    # with no pitches asked for, the rows are the notes found, named after the Drum Rack's pads
    assert [(r["pitch"], r["name"]) for r in steps.read(live, "Drums", 3, 1)["pattern"]["rows"]] == [
        (KICK, "Kick"),
        (HAT, "Hat"),
    ]
    tidy(live)


def test_write_replaces_the_notes_of_the_clip_that_covers_exactly_the_span(live):
    steps.write(live, "Drums", 3, FOUR, name="beat")
    clip = track(live, "Drums").arrangement_clips[0]
    other = pattern([row(SNARE, {4: 120, 12: 120}, name="Snare")])
    done = steps.write(live, "Drums", 3, other)
    assert done["created"] is False and done["before"] == steps.to_notes(FOUR)
    assert done["pattern"] == {**steps.check(other), "off_grid": 0} and done["clip"]["name"] == "beat"
    assert track(live, "Drums").arrangement_clips == (clip,)  # the same clip: nothing deleted, nothing made
    assert held(live, "Drums") == [(8.0, 12.0, "beat", sorted(steps.to_notes(other)))]
    # the notes that were there before are enough to put them back
    undone = steps.write(live, "Drums", 3, steps.from_notes(done["before"], 1, 16, 4.0), name="again")
    assert undone["hash"] == steps.content_hash(steps.to_notes(FOUR)) and undone["clip"]["name"] == "again"
    assert steps.write(live, "Drums", 3, pattern([]))["hash"] == steps.content_hash([])  # an empty pattern empties it
    assert held(live, "Drums") == [(8.0, 12.0, "again", [])]
    tidy(live)


@pytest.mark.parametrize(("bar", "bars"), [(5, 1), (6, 1), (3, 4), (5, 4), (6, 2)])
def test_write_does_not_cut_a_clip_that_reaches_into_the_span(live, bar, bars):
    before, calls = held(live, "Bass"), len(live.calls)
    total = 16 * bars
    done = steps.write(live, "Bass", bar, pattern([row(48, {0: 100}, total=total)], bars=bars))
    assert done == {"error": "clips are in the way", "blocked": [{"name": "long", "start": 16.0, "end": 24.0}]}
    assert held(live, "Bass") == before and len(live.calls) == calls + 1  # nothing changed, nothing more asked
    tidy(live)


def test_a_span_inside_a_longer_clip_is_read_but_has_no_clip_of_its_own(live):
    second = steps.read(live, "Bass", 6, 1)  # the long clip's second bar
    assert second["clip"] is None and second["blocked"] == [{"name": "long", "start": 16.0, "end": 24.0}]
    assert [(r["pitch"], r["name"], [k for k, v in enumerate(r["steps"]) if v]) for r in second["pattern"]["rows"]] == [
        (48, "C2", [15]),
        (50, "D2", [2]),
    ]
    both = steps.read(live, "Bass", 5, 2)  # exactly the clip
    assert both["clip"] == {"name": "long", "start": 16.0, "end": 24.0} and both["blocked"] == []
    assert both["hash"] == steps.content_hash(LONG)
    wide = steps.read(live, "Bass", 5, 4)  # the clip and two free bars
    assert wide["clip"] is None and wide["hash"] == both["hash"] and len(wide["blocked"]) == 1


def test_only_a_midi_track_holds_a_pattern(live):
    for name in ("Audio", "Bus", "Main"):
        with pytest.raises(LiveError, match="is not a MIDI track"):
            steps.write(live, name, 1, FOUR)
        with pytest.raises(LiveError, match="is not a MIDI track"):
            steps.read(live, name, 1, 1)
    assert held(live, "Audio") == [(0.0, 8.0, "", [])]


def test_a_bar_is_as_long_as_the_songs_signature_says(live):
    live.song.signature_numerator = 3
    waltz = pattern([row(KICK, {0: 100, 4: 90, 8: 90}, total=12, name="Kick")], steps_per_bar=12)
    done = steps.write(live, "Drums", 2, waltz)
    assert done["clip"] == {"name": "", "start": 3.0, "end": 6.0} and done["beats_per_bar"] == 3.0
    assert done["pattern"] == {**steps.check(waltz), "off_grid": 0}
    assert held(live, "Drums")[0][3] == [(KICK, 0.0, 0.25, 100), (KICK, 1.0, 0.25, 90), (KICK, 2.0, 0.25, 90)]
    live.song.signature_numerator, live.song.signature_denominator = 6, 8  # also three beats
    assert steps.read(live, "Drums", 2, 1, 12)["clip"] is not None
    tidy(live)


def test_a_pattern_written_with_swing_comes_back_as_written_and_reads_off_grid_without_it(live):
    swung = pattern([row(HAT, dict.fromkeys(range(16), 90), name="Hat")], swing=0.5, length=0.5)
    done = steps.write(live, "Drums", 1, swung)
    assert done["pattern"] == {**steps.check(swung), "off_grid": 0}
    assert steps.read(live, "Drums", 1, 1)["off_grid"] == 8
    assert steps.read(live, "Drums", 1, 1, swing=0.5)["off_grid"] == 0


def test_a_clip_cut_from_a_longer_one_is_read_and_written_from_its_start_marker(live):
    with live.main_thread():
        cut = lom.Clip(0.0, 4.0, name="cut", parent=track(live, "Empty"))  # bar 1, playing the second bar of its notes
        cut.add_new_notes([lom.MidiNoteSpecification(60, t, 0.25, 100) for t in (1.0, 4.0, 5.0, 9.0)])
        cut.start_marker, cut.loop_start, cut.loop_end, cut.end_marker = 4.0, 4.0, 8.0, 8.0
        track(live, "Empty")._clips.append(cut)
    found = steps.read(live, "Empty", 1, 1)
    assert found["clip"]["name"] == "cut" and found["pattern"]["rows"][0]["steps"] == [100, 0, 0, 0, 100, *[0] * 11]
    done = steps.write(live, "Empty", 1, pattern([row(60, {8: 70})]))
    assert done["before"] == [(60, 0.0, 0.25, 100), (60, 1.0, 0.25, 100)]
    # the notes outside what the clip plays are not this span's: they stay
    assert held(live, "Empty") == [(0.0, 4.0, "cut", [(60, 1.0, 0.25, 100), (60, 6.0, 0.25, 70), (60, 9.0, 0.25, 100)])]


def test_a_clip_that_loops_inside_itself_is_in_the_way(live):
    with live.main_thread():
        looped = lom.Clip(0.0, 16.0, name="one bar, four times", parent=track(live, "Empty"))
        looped.loop_end = 4.0
        track(live, "Empty")._clips.append(looped)
    assert steps.write(live, "Empty", 1, pattern([], bars=4)) == {
        "error": "clips are in the way",
        "blocked": [{"name": "one bar, four times", "start": 0.0, "end": 16.0}],
    }
    assert steps.read(live, "Empty", 1, 4)["clip"] is None
