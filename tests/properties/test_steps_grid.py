"""Property tests of the step grid's arithmetic (zpkt.live.steps): a pattern to notes and back."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zpkt.live import steps

BEATS_PER_BAR = st.sampled_from([4.0, 3.0, 2.0, 3.5, 5.0])  # 4/4, 3/4 and 6/8, 2/4, 7/8, 5/4


@st.composite
def patterns(draw, plain: bool = False):
    """Any valid pattern; `plain`: one whose notes all fit (no note cut short by the end or by its delay)."""
    bars = draw(st.sampled_from(steps.BARS))
    per_bar = draw(st.sampled_from(steps.STEPS_PER_BAR))
    total = bars * per_bar
    swing = draw(st.sampled_from([0.0, 0.25, 0.5, 0.75]) if plain else st.floats(0.0, steps.MAX_SWING))
    lengths = st.sampled_from([1.0, 1.5, 2.0]) if plain else st.floats(steps.MIN_LENGTH, float(total))
    rows = []
    for pitch in draw(st.lists(st.integers(0, 127), unique=True, max_size=4)):
        cells = draw(st.lists(st.sampled_from([0, 0, 0, 1, 64, 127]), min_size=total, max_size=total))
        if plain:  # the last two steps stay empty, so every note ends inside the pattern
            cells[-2:] = [0, 0]
        made = {"pitch": pitch, "name": steps.note_name(pitch), "steps": cells}
        if not plain and draw(st.booleans()):
            made["lengths"] = [draw(st.sampled_from([0.0, 0.25, 0.5, 3.0])) if v else 0.0 for v in cells]
        rows.append(made)
    return {"bars": bars, "steps_per_bar": per_bar, "rows": rows, "length": draw(lengths), "swing": swing}


def approx(notes):
    return [(p, pytest.approx(s, abs=1e-4), pytest.approx(d, abs=1e-4), v) for p, s, d, v in notes]


@given(p=patterns(plain=True), beats=BEATS_PER_BAR)
def test_a_plain_pattern_comes_back_from_its_notes_as_it_was(p, beats):
    pitches = [r["pitch"] for r in p["rows"]]
    back = steps.from_notes(steps.to_notes(p, beats), p["bars"], p["steps_per_bar"], beats, pitches, swing=p["swing"])
    assert back["off_grid"] == 0 and back["rows"] == p["rows"] and back["swing"] == p["swing"]
    if any(any(r["steps"]) for r in p["rows"]):
        assert back["length"] == p["length"]


@given(p=patterns(), beats=BEATS_PER_BAR)
def test_any_pattern_read_back_and_written_again_gives_the_same_notes(p, beats):
    notes = steps.to_notes(p, beats)
    pitches = [r["pitch"] for r in p["rows"]]
    back = steps.from_notes(notes, p["bars"], p["steps_per_bar"], beats, pitches, swing=p["swing"])
    assert back["off_grid"] == 0
    assert [r["steps"] for r in back["rows"]] == [r["steps"] for r in p["rows"]]
    assert steps.to_notes(back, beats) == approx(notes)
    assert steps.content_hash(steps.to_notes(back, beats)) == steps.content_hash(notes)


@given(p=patterns(), beats=BEATS_PER_BAR)
def test_every_note_starts_and_ends_inside_the_pattern_in_order(p, beats):
    notes = steps.to_notes(p, beats)
    end = p["bars"] * beats
    step = beats / p["steps_per_bar"]
    assert notes == sorted(notes, key=lambda n: (n[1], n[0]))
    assert len(notes) == sum(1 for r in p["rows"] for v in r["steps"] if v)
    for _pitch, start, duration, velocity in notes:
        assert 0.0 <= start < end and start + duration <= end + 1e-5
        assert duration >= steps.MIN_LENGTH * step - 1e-5 and 1 <= velocity <= 127


@given(
    notes=st.lists(
        st.tuples(st.integers(0, 127), st.floats(-2.0, 20.0), st.floats(0.01, 4.0), st.integers(1, 127)), max_size=24
    ),
    bars=st.sampled_from(steps.BARS),
    per_bar=st.sampled_from(steps.STEPS_PER_BAR),
)
def test_every_note_is_either_on_the_grid_or_counted(notes, bars, per_bar):
    found = steps.from_notes(notes, bars, per_bar, 4.0)
    shown = sum(1 for r in found["rows"] for v in r["steps"] if v)
    assert shown + found["off_grid"] == len(notes)
    steps.check(found)  # what it gives is a valid pattern
