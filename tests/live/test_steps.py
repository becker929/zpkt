"""zpkt.live.steps: the step grid's arithmetic (no Live), then every function on FakeLive: a pattern read from and
written to an Arrangement clip, one step flipped, the clip painted across bars, erased, and found again."""

from __future__ import annotations

import pytest

from zpkt.live import steps

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
