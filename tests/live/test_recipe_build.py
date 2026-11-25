"""zpkt.live.recipe_build: the plan for the mix set (pure) and its stops. The Live steps are pinned by the arranger's
goldens through mixset.py, and by the Song's build test on FakeLive."""

from __future__ import annotations

from pathlib import Path

import pytest

from zpkt.live import recipe_build as rb

LOOPS = {
    "lanes": [
        {"id": "kick", "title": "Kick", "group": "kick"},
        {"id": "chord", "title": "Chord", "group": "sfx"},
        {"id": "unused", "title": "Unused", "group": "perc"},
    ],
    "clips": [],
}


def arrangement(**more):
    return {
        "bars": 8,
        "regions": [
            {"lane": "kick", "clip": "k", "start": 0, "len": 8},
            {"lane": "chord", "clip": "c", "start": 4, "len": 4},
        ],
        **more,
    }


def test_channels_are_the_lanes_in_use_and_the_kinds_of_transition_laid_over_them():
    arr = arrangement(
        transitions=[{"kind": "riser", "mode": "add"}, {"kind": "scoop", "mode": "replace", "lane": "kick"}]
    )
    assert [c["id"] for c in rb.channels(LOOPS, arr)] == ["kick", "chord", "fx-riser"]
    assert rb.used_buses(rb.channels(LOOPS, arr)) == ["kick", "sfx", "fx"]  # the buses' order, none for perc


def test_a_loop_that_stops_short_of_a_whole_pass_stops_the_build_and_says_which():
    clips = {"k": {"kind": "loop", "bars": 3, "file": "k.flac"}, "c": {"kind": "once", "bars": 2, "file": "c.flac"}}
    with pytest.raises(rb.Stopped, match="does not fill whole passes"):
        rb.clip_placements(arrangement(), clips, {}, Path("/d"))


def test_whole_passes_a_tail_where_nothing_follows_and_a_picked_transition():
    clips = {
        "k": {"kind": "loop", "bars": 4, "file": "k.flac", "tail": "kt.flac"},
        "c": {"kind": "once", "bars": 2, "file": "c.flac"},
    }
    arr = arrangement(
        regions=[
            {"lane": "kick", "clip": "k", "start": 0, "len": 8},
            {"lane": "chord", "clip": "c", "start": 4, "len": 2},
        ],
        transitions=[{"id": "t1", "kind": "riser", "mode": "add", "startBeat": 24.0, "gainDb": -3.0}],
    )
    got = rb.clip_placements(arr, clips, {"t1": {"file": "r.flac"}}, Path("/d"))
    assert got == [
        ("kick", "/d/audio/k.flac", 0.0, None),
        ("kick", "/d/audio/k.flac", 16.0, None),
        ("chord", "/d/audio/c.flac", 16.0, None),
        ("fx-riser", "/d/fx/audio/r.flac", 24.0, -3.0),
    ]  # the kick's tail does not show: its region runs to the end of the arrangement


def test_eq_values_for_bells_and_for_cuts():
    assert rb.bell_eq_values([[40.0, 8.0, 0.7]])["2 Frequency A"] == "40.0 Hz"
    assert rb.cuts_eq_values({"cuts": [{"on": False}]}) is None
    cut = rb.cuts_eq_values(
        {"hp": {"on": True, "freq": 30}, "cuts": [{"on": True, "freq": 300, "gainDb": 4.0, "q": 1}]}
    )
    assert cut and cut["1 Filter Type A"] == "High Pass 12dB" and cut["2 Gain A"] == "0.0 dB"  # never a boost


def test_a_target_that_is_no_track_stops():
    assert rb.target_track({"kick": 4, "Kick bus": 0}, "bus-kick") == "song.tracks[0]"
    with pytest.raises(rb.Stopped, match="no track for 'bus-hats'"):
        rb.target_track({"kick": 4}, "bus-hats")
