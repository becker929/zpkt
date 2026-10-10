"""hands.arrange: hat tiling, automation repair logic, and that every generated LOM block compiles."""
from __future__ import annotations

import pytest

from hands.arrange import autostate, fx, hats
from hands.live.transport import McpResult, Transport


class Compiles(Transport):
    """Compiles each block as the Remote Script would, and answers from a list."""

    def __init__(self, answers=()):
        self.answers, self.calls = list(answers), []

    def execute(self, code):
        compile(code, "<lom>", "exec")
        self.calls.append(code)
        return McpResult("ok", self.answers.pop(0) if self.answers else None)


def test_tile_repeats_and_trims_the_pattern():
    notes = [[60, 0.0, 1.0, 100], [61, 2.5, 1.0, 90], [95, 1.0, 0.25, 80]]
    assert hats.tile(4.0, notes, 6.0, {60, 61}) == [
        [60, 0.0, 1.0, 100], [61, 2.5, 1.0, 90], [60, 4.0, 1.0, 100]]
    assert hats.tile(4.0, notes, 3.0, {61}) == [[61, 2.5, 0.5, 90]]          # shortened at the end


def test_rewrite_writes_a_clip_per_track_where_its_layers_play():
    pats = {"perc 1": [4.0, [[95, 0.0, 0.25, 100]]], "perc 2": [4.0, [[60, 0.5, 0.25, 100]]]}
    live = Compiles([0, 0, 4, 8])
    made = hats.rewrite(live, [(0.0, 16.0, "B"), (16.0, 16.0, "AB")], pats)
    assert [(name, start, section) for name, start, _, section, _ in made] == [
        ("perc 1", 0.0, "B"), ("perc 1", 16.0, "AB"), ("perc 2", 16.0, "AB")]


def test_fx_blocks_compile():
    live = Compiles([[0.0, 2.0], [[8.0, 11.0]], [100.0, 108.0, 55.5, 66.0, []], [64.0, 65.0], [0.7, "-6.0 dB"]])
    fx.splash(live, 5, 32.0, 3.0)
    fx.splash_copies(live, 5, 32.0, [8.0], 3.0)
    start, end, end_beat = fx.phrase_at(live, 17, 104.0, 4.0, 96.0, 112.0)
    assert end_beat == pytest.approx(fx.BEATBOX.hold + 4.0)
    fx.tail_slices(live, 17, start, end_beat, [64.0], 0.5)
    assert fx.fader_db(live, 12, -6.0) == [0.7, "-6.0 dB"]
    assert live.calls[-1].rstrip().endswith("v.value = hi")    # the write comes last


def test_restore_fixes_static_parameters_and_checks_again(monkeypatch):
    ref = {"params": [{"track": "kick", "param": "4 Filter On A", "path": [2, 1, 34]},
                      {"track": "Main", "param": "Width", "path": [20, 0, 3]}],
           "values": {"1": [0.0, 1.0], "41": [0.0, 1.0]}}
    readings = iter([{0.0: [1.0, 1.0], 160.0: [0.0, 1.0]},   # the scoop stuck on at the first start
                     {0.0: [0.0, 1.0], 160.0: [0.0, 1.0]}])
    fixed = []
    monkeypatch.setattr(autostate, "values_at", lambda client, params, beats: next(readings))
    monkeypatch.setattr(autostate, "state", lambda client, path: [0, 1.0])
    monkeypatch.setattr(autostate, "set_static", lambda client, path, value: fixed.append((path, value)))
    assert autostate.restore(None, [(1, 40), (41, 48)], ref) == [("kick", "4 Filter On A")]
    assert fixed == [([2, 1, 34], 0.0)]


def test_restore_refuses_what_a_static_value_cannot_fix(monkeypatch):
    ref = {"params": [{"track": "kick", "param": "Gain", "path": [2, 1, 5]}], "values": {"1": [0.0], "41": [0.5]}}
    monkeypatch.setattr(autostate, "values_at", lambda client, params, beats: {b: [0.2] for b in beats})
    monkeypatch.setattr(autostate, "state", lambda client, path: [0, 0.2])
    with pytest.raises(RuntimeError, match="cannot fix"):
        autostate.restore(None, [(1, 40), (41, 48)], ref)


def test_autostate_blocks_compile():
    live = Compiles([[], [0, 0.5]])
    autostate.automated(live)
    assert autostate.state(live, [3, 0, "c", 1, 0, 15]) == [0, 0.5]
    autostate.set_static(live, [3, 1, 2], 0.25)
