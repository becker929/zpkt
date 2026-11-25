"""Property tests of the pure arithmetic: the unit conversions and the desk's loudness match."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from zpkt.app import deskstate
from zpkt.live import units

unit_fraction = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@given(lo=st.floats(0.01, 100), span=st.floats(0.5, 1000), u=unit_fraction)
def test_lin_and_log_round_trip(lo, span, u):
    for unit in (units.Lin(lo, lo + span), units.Log(lo, lo + span * 2)):
        assert unit.to_lom(unit.from_lom(u)) == pytest.approx(u, abs=1e-6)


@given(u=st.floats(-1.0, 1.0))
def test_utility_gain_round_trips_through_the_lom(u):
    unit = units.Db35()
    assert unit.to_lom(unit.from_lom(u)) == pytest.approx(u, abs=1e-9)


@given(v=st.floats(-1e6, 1e6, allow_nan=False))
def test_utility_gain_in_the_lom_stays_in_range(v):
    assert -1.0 <= units.Db35().to_lom(v) <= 1.0


@given(v=st.floats(0.0, 4.0))
def test_width_round_trips(v):
    unit = units.Sqrt()
    assert unit.from_lom(unit.to_lom(v)) == pytest.approx(v, abs=1e-9)


@given(r=st.floats(1.0, 100.0))
def test_ratio_round_trips(r):
    unit = units.Ratio()
    assert unit.from_lom(unit.to_lom(r)) == pytest.approx(r, rel=1e-6)


@given(v=st.booleans())
def test_switches_round_trip(v):
    assert units.BOOL.from_lom(units.BOOL.to_lom(v)) is v


@given(db=st.floats(-90.0, 6.0))
def test_fader_display_text_round_trips_to_gain(db):
    gain = 10 ** (db / 20)
    text = f"{units.FADER.to_lom(gain):.2f} dB"
    assert units.FADER.from_lom(text) == pytest.approx(gain, rel=0.01)


def sources(lufs: dict[str, float]) -> dict[str, dict]:
    return {k: {"sections": {"drop": {"lufs": v}}} for k, v in lufs.items()}


levels = st.floats(-40.0, 0.0)


@given(a=levels, b=levels, ref=levels, slot=st.sampled_from(["A", "B", "C"]))
def test_matched_sources_all_land_on_the_quietest_drop(a, b, ref, slot):
    src = sources({"A": a, "B": b, "C1": ref})
    gains = {s: deskstate.matched_gain_db(src, s, "C1", True) for s in ("A", "B", "C")}
    heard = {"A": a + gains["A"], "B": b + gains["B"], "C": ref + gains["C"]}
    assert all(h == pytest.approx(min(a, b, ref)) for h in heard.values())
    assert all(g <= 1e-9 for g in gains.values())  # matching only turns things down
    assert gains[slot] == deskstate.matched_gain_db(src, slot, "C1", True)


@given(a=levels, b=levels, ref=levels, slot=st.sampled_from(["A", "B", "C", "W"]))
def test_no_gain_for_the_working_mix_or_with_the_match_off(a, b, ref, slot):
    src = sources({"A": a, "B": b, "C1": ref})
    assert deskstate.matched_gain_db(src, "W", "C1", True) == 0.0
    assert deskstate.matched_gain_db(src, slot, "C1", False) == 0.0


@given(slot=st.sampled_from(["A", "B", "C"]))
def test_no_gain_while_a_source_is_not_analysed(slot):
    assert deskstate.matched_gain_db(sources({"A": -10.0, "B": -9.0}), slot, "C1", True) == 0.0


@given(a=levels, b=levels, ref=levels)
def test_the_published_gains_are_the_per_reference_matches(a, b, ref):
    src = sources({"A": a, "B": b, "C1": ref})
    got = deskstate.matched_gains(src)
    assert set(got) == {"C1"} and set(got["C1"]) == {"A", "B", "C"}
    assert all(math.isfinite(g) and g <= 1e-3 for g in got["C1"].values())


@given(
    page=st.integers(0, 3),
    slot=st.sampled_from(["k1", "f1", "f3"]),
    n=st.floats(0, 1),
    pos=st.floats(0, 1000),
    playing=st.booleans(),
)
def test_reducing_a_message_never_changes_the_state_it_was_given(page, slot, n, pos, playing):
    state = deskstate.initial()
    before = repr(state)
    deskstate.reduce(state, {"t": "v", "page": page, "slot": slot, "n": n, "s": "x", "r": n, "key": "k"}, 1.0)  # type: ignore[arg-type]
    out = deskstate.reduce(state, {"t": "pos", "b": pos, "p": playing}, 1.0)  # type: ignore[arg-type]
    assert repr(state) == before
    assert out["pos"] == pos and out["playing"] is playing
