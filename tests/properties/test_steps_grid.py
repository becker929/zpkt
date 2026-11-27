"""Property tests of zpkt.live.steps: the step grid's arithmetic (a pattern to notes and back), then taps, painting
and erasing on FakeLive against what a hand would keep."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zpkt.live import steps
from zpkt.live.testing import FakeLive, fake_set

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
    # so the hash of the grid a page holds is the hash of the clip it was read from
    assert steps.content_hash(steps.to_notes(back, beats)) == steps.content_hash(steps.to_notes(p, beats))


@given(p=patterns(), beats=BEATS_PER_BAR)
def test_any_pattern_read_back_and_written_again_gives_the_same_notes(p, beats):
    notes = steps.to_notes(p, beats)
    pitches = [r["pitch"] for r in p["rows"]]
    back = steps.from_notes(notes, p["bars"], p["steps_per_bar"], beats, pitches, swing=p["swing"])
    assert back["off_grid"] == 0
    assert [r["steps"] for r in back["rows"]] == [r["steps"] for r in p["rows"]]
    assert steps.to_notes(back, beats) == approx(notes)  # lengths come back to four decimals of a step


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


# --------------------------------------------------------------------------- on FakeLive

PITCHES = [36, 38, 42]


def drums(clips: list[dict] | None = None) -> FakeLive:
    return FakeLive(fake_set({"tracks": [{"name": "Drums", "type": "midi", "clips": clips or []}]}))


def clips_of(live: FakeLive) -> list[tuple]:
    track = live.song.tracks[0]
    return [
        (c.start_time, c.end_time, c.name, sorted((n.pitch, n.start_time, n.duration, n.velocity) for n in c._notes))
        for c in track.arrangement_clips
    ]


@given(
    taps=st.lists(st.tuples(st.sampled_from(PITCHES), st.integers(0, 31), st.integers(1, 127)), max_size=24),
    swing=st.sampled_from([0.0, 0.5]),
)
def test_taps_leave_in_live_the_grid_a_hand_would_keep(taps, swing):
    with drums() as live:
        grid: dict[tuple[int, int], int] = {}
        for pitch, step, velocity in taps:
            got = steps.toggle(live, "Drums", 2, 2, 16, pitch, step, velocity=velocity, swing=swing)
            if (pitch, step) in grid:
                del grid[(pitch, step)]
                assert (got["on"], got["velocity"]) == (False, 0)
            else:
                grid[(pitch, step)] = velocity
                assert (got["on"], got["velocity"]) == (True, velocity)
        found = steps.read(live, "Drums", 2, 2, 16, PITCHES, swing=swing)
        assert found["off_grid"] == 0
        assert {(r["pitch"], k): v for r in found["pattern"]["rows"] for k, v in enumerate(r["steps"]) if v} == grid
        assert len(clips_of(live)) == (1 if taps else 0)
        assert not any(c.readbacks for c in live.calls)


@given(
    there=st.lists(st.tuples(st.integers(0, 15), st.sampled_from([1, 2, 3])), max_size=6),
    bars=st.sampled_from([1, 2]),
    targets=st.lists(st.integers(1, 16), max_size=12),
    data=st.data(),
)
def test_paint_and_erase_never_cut_or_overlap_a_clip_and_account_for_every_bar(there, bars, targets, data):
    """Clips of one to three bars lie about the track (never over bar 20 and on, where the pattern is). Painting it
    over any bars, then erasing any bars, leaves every clip either as it was, replaced whole, or gone whole."""
    laid: list[dict] = []
    for bar, length in there:
        start, end = bar * 4.0, (bar + length) * 4.0
        if all(end <= c["start"] or start >= c["start"] + c["length"] for c in laid):
            laid.append({"start": start, "length": end - start, "name": f"was {bar}", "notes": [[36, 0.0, 0.25, 1]]})
    with drums(laid) as live:
        total = 16 * bars
        mine = {"bars": bars, "steps_per_bar": 16, "length": 1.0, "rows": [{"pitch": 38, "steps": [90] * total}]}
        source = steps.write(live, "Drums", 21, mine, name="mine")
        before = clips_of(live)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(steps, "COPY_PAUSE_S", 0.0)
            done = steps.paint(live, "Drums", 21, bars, targets)
        after = clips_of(live)
        assert sorted(done["painted"] + [s["bar"] for s in done["skipped"]]) == sorted(set(targets))
        assert all(a[1] <= b[0] for a, b in itertools.pairwise(after))
        copies = {(b - 1) * 4.0 for b in done["painted"]}
        gone = {(k["bar"] - 1) * 4.0 for k in done["replaced"]}
        assert [c for c in after if c[0] not in copies] == [c for c in before if c[0] not in gone]
        assert all(c[2] == "mine" and c[1] - c[0] == bars * 4.0 for c in after if c[0] in copies)
        assert gone <= copies and all(len(k["notes"]) == 1 for k in done["replaced"])
        stamped = {c["bar"]: c["hash"] for c in steps.painted(live, "Drums", bars, 64)}
        assert all(stamped[b] == source["hash"] for b in done["painted"])

        wipe = data.draw(st.lists(st.integers(1, 22), max_size=8))
        erased = steps.erase(live, "Drums", wipe, bars)
        left = clips_of(live)
        assert sorted([k["bar"] for k in erased["erased"]] + [s["bar"] for s in erased["skipped"]]) == sorted(set(wipe))
        starts = {(k["bar"] - 1) * 4.0 for k in erased["erased"]}
        assert left == [c for c in after if c[0] not in starts]
        assert all(c[1] - c[0] == bars * 4.0 for c in after if c[0] in starts)
        assert not any(c.readbacks for c in live.calls)
