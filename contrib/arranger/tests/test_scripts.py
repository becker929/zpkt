"""The other scripts' tables and Live steps: fxset's candidates and recipes, bounce's solo states, kickfuzz's
option changes and their undo, shorts' canonical arrangement, and kickiso's EQ fit. Goldens pin what each makes."""

from __future__ import annotations

import dataclasses
import os

import fxset
import kickfuzz
import mixset
import numpy as np
import pytest
import shorts
from samples import RecordingLive, assert_golden


def test_fx_candidates():
    rows = [{k: v for k, v in dataclasses.asdict(c).items()} | {"seam_beat": c.seam_beat} for c in fxset.candidates()]
    assert_golden("fxset-candidates", rows)
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids))
    assert {i for v in fxset.SHORTLIST.values() for i in v} <= set(ids)


def test_fx_recipes():
    assert_golden("fxset-recipes", {c.id: fxset.recipe(c) for c in fxset.candidates()})


def test_fx_states():
    live = RecordingLive(tracks=[f"t{i}" for i in range(20)] + ["fx noise", "fx tone", "fx kit"])
    assert_golden("fxset-states", fxset.states(live))


def test_fx_clip_notes_merges_same_pitch_and_start():
    live = RecordingLive()
    fxset.clip_notes(
        live, "song.tracks[2]", 1200.0, 4.0, [(0.0, 36, 0.5, 90), (0.0, 36, 0.25, 120), (1.0, 38, 0.5, 200)]
    )
    assert live.calls == [
        [
            "run",
            "import Live\nt = song.tracks[2]\nc = t.create_midi_clip(1200.0, 4.0)\n"
            "c.add_new_notes(tuple(Live.Clip.MidiNoteSpecification(pitch=p, start_time=s, duration=d, "
            "velocity=v) for p, s, d, v in [(36, 0.0, 0.25, 120.0), (38, 1.0, 0.5, 127.0)]))\nresult = 'ok'",
        ]
    ]


@pytest.fixture
def bounce_module():
    """bounce.py, imported with the environment put back afterwards (it used to set rig variables at import)."""
    saved = dict(os.environ)
    import bounce

    yield bounce
    os.environ.clear()
    os.environ.update(saved)


def test_bounce_states(bounce_module):
    assert_golden("bounce-states", {k: [list(v[0]), list(v[1])] for k, v in bounce_module.STATES.items()})


class SoloLive(RecordingLive):
    def __init__(self) -> None:
        super().__init__()
        self.soloed: list[int] = []
        self.chain: dict[int, int | None] = {}

    def run(self, code: str):
        self.calls.append(["run", code])
        if code.startswith("for i, t in enumerate(song.tracks):"):
            self.soloed = sorted(eval(code.split("t.solo = i in ")[1].split("\n")[0]))
        if code.startswith("result = [i for i, t in enumerate(song.tracks) if t.solo]"):
            return self.soloed
        if code.startswith("for i, c in enumerate(song.tracks["):
            t = int(code.split("song.tracks[")[1].split("]")[0])
            self.chain[t] = eval(code.split("i == ")[1].split("\n")[0])
        if code.startswith("result = [i for i, c in enumerate(song.tracks["):
            t = int(code.split("song.tracks[")[1].split("]")[0])
            return [] if self.chain.get(t) is None else [self.chain[t]]
        return "ok"


def test_bounce_solo_steps(bounce_module, monkeypatch):
    live = SoloLive()
    monkeypatch.setattr(bounce_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(bounce_module, "liveops", live)
    bounce_module.solo((2, 3))
    bounce_module.solo_chain(7, 4)
    bounce_module.solo(())
    bounce_module.solo_chain(None, None)
    assert_golden("bounce-solo", live.calls)


class ParamLive(RecordingLive):
    """Answers the parameter lookups kickfuzz makes: one parameter per name, every value 0.25."""

    def run(self, code: str):
        self.calls.append(["run", code])
        if code.startswith("result = [c.name for c in"):
            return ["060 body", "052 layer"]
        if code.startswith("result = [i for i, p in enumerate("):
            return [3]
        if code.startswith("result = ") and code.endswith(".value"):
            return 0.25
        return "ok"


@pytest.mark.parametrize("option", ["b10", "t-f1s", "t-kdi18", "t-d150-6"])
def test_kickfuzz_apply_and_restore(option):
    live = ParamLive()
    undo = kickfuzz.apply(live, kickfuzz.OPTIONS[option]["set"])
    live.devices_on = {}  # the loaded Roar is deleted again
    kickfuzz.restore(live, undo)
    assert_golden(f"kickfuzz-{option}", {"undo": undo, "calls": live.calls})


def test_kickfuzz_options():
    assert_golden("kickfuzz-options", kickfuzz.OPTIONS)
    assert kickfuzz.eq_values([[40.0, 8.0, 0.7]])["2 Frequency A"] == "40.0 Hz"


def test_short_8d2a2():
    clips = {clip: {"lane": lane} for lane, clip, *_ in shorts.SHORTS["8d2a2"][1]}
    name, regions = shorts.regions_of("8d2a2", clips)
    assert name == "8d2a2 Fast build, slow peak"
    assert_golden("shorts-8d2a2", regions)


def test_short_refuses_a_kick_before_the_drop(monkeypatch):
    rows = [("splash", "splash-d", 17, 20), ("kick", "kick-rumble-a", 9, 40)]
    monkeypatch.setitem(shorts.SHORTS, "bad", ("Bad", rows))
    with pytest.raises(AssertionError, match="kick comes in before the drop"):
        shorts.regions_of("bad", {c: {"lane": lane} for lane, c, *_ in rows})


def test_kickiso_fit():
    import kickiso

    f = np.array(kickiso.THIRDS)
    gap = kickiso.bell(f, 2500.0, 4.0, 1.0) + kickiso.bell(f, 40.0, 8.0, 0.7)
    bells = kickiso.fit(gap)
    assert_golden("kickiso-fit", bells)
    assert bells[0][0] == pytest.approx(39.7, abs=0.1)


def test_mixset_import_has_no_side_effects():
    assert mixset.SET == "HW002_121_pp_mix"
