"""hands.probe_kit: merging pattern settings, writing batches on the fixture set, and the Live side faked."""
from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf
from planted import TRACK, planted_set

from hands import als, audio
from hands import probe_kit as PK
from hands.live import render as live_render
from hands.live import session, timeops
from hands.live.knobs import Knob
from hands.live.session import Guard
from hands.live.transport import McpResult, MockTransport

GAIN = Knob(TRACK, ("StereoGain", 0), "Gain")
WIDTH = Knob(TRACK, ("StereoGain", 0), "StereoWidth")
DRIVE = Knob(TRACK, ("plugin", "Decapitator"), "Drive")
SPEAKER = Knob(TRACK, "Mixer", "Speaker")


def test_merge_patterns_fills_the_baseline_in_first_seen_order():
    patterns = [[], [(DRIVE, 0.4)], [(DRIVE, 0.5), (WIDTH, 1.5)], [(WIDTH, 2.0), (WIDTH, 3.0)]]
    base = {DRIVE: 0.27, WIDTH: 0.877}
    assert PK.merge_patterns(patterns, 6, base.__getitem__) == [
        (DRIVE, [0.27, 0.4, 0.5, 0.27, 0.27, 0.27]),
        (WIDTH, [0.877, 0.877, 1.5, 3.0, 0.877, 0.877]),     # the last setting in a pattern wins
    ]


def test_merge_patterns_refuses_conflicts():
    with pytest.raises(ValueError, match="already set by the baseline"):
        PK.merge_patterns([[(DRIVE, 0.4)]], 4, lambda k: 0.0, taken=[DRIVE])
    with pytest.raises(ValueError, match="5 patterns for a 4-pattern kit"):
        PK.merge_patterns([[]] * 5, 4, lambda k: 0.0)
    assert PK.constant({SPEAKER: False}, 3) == [(SPEAKER, [False, False, False])]


@pytest.mark.parametrize("v, lo, hi, kind", [(0.3, 0.0, 0.6, "lin"), (120.0, 50.0, 500.0, "log"), (3.0, 1.5, 12.0, "log")])
def test_scale_and_unscale_invert(v, lo, hi, kind):
    assert PK.scale(PK.unscale(v, lo, hi, kind), lo, hi, kind) == pytest.approx(v)


def test_unscale_bounds_and_switches():
    assert PK.scale(0.75, 0, 1, "bool") is True and PK.unscale(False, 0, 1, "bool") == 0.25
    with pytest.raises(ValueError, match="outside"):
        PK.unscale(700.0, 50.0, 500.0, "log")


@pytest.fixture
def kit(rig):
    """A 4-pattern kit made from the planted fixture set: 8 beats of lead, 32-beat patterns."""
    planted_set(rig.set_path("test_kit_t4"))
    made = PK.Kit(kit="t4", set="test_kit_t4", src="test_src", keep=[24.0, 56.0], lead=8.0, pattern_beats=32.0, P=4)
    made.save()
    return made


def test_kit_round_trips_and_knows_its_shape(kit):
    assert PK.Kit.load("t4") == kit
    assert kit.length_beats == 136.0 and kit.step_times() == [0.0, 40.0, 72.0, 104.0]


def test_write_batch_steps_each_knob_per_pattern(kit, rig):
    name = PK.write_batch("t4", "demo", steps=[(DRIVE, [0.27, 0.4, 0.5, 0.6]), (SPEAKER, [True, True, False, True])])
    assert name == "test_x_t4_demo"
    tree = als.load(rig.set_path(name))
    envs = als.envelopes(tree)
    drive = als._steps_of(envs["1-Audio > PluginDevice > ParameterValue"][2])
    assert drive == [(-63072000.0, "0.27"), (0.0, "0.27"), (40.0, "0.4"), (72.0, "0.5"), (104.0, "0.6")]
    speaker = als._steps_of(envs["1-Audio > Speaker"][2])
    assert speaker[-2:] == [(72.0, "false"), (104.0, "true")]
    assert als.check(rig.set_path(name)).problems == []
    with pytest.raises(ValueError, match="3 values for 4 patterns"):
        PK.write_batch("t4", "short", steps=[(DRIVE, [0.1, 0.2, 0.3])])


def test_write_batch_adds_donor_devices(kit, rig):
    planted_set(rig.set_path("test_donor"))
    name = PK.write_batch(kit, "donor", steps=[], devices=[(TRACK, "test_donor", TRACK, "Eq8")])
    tags = [d.tag for d in als.devices(als.find_track(als.load(rig.set_path(name)), TRACK))]
    assert tags == ["StereoGain", "PluginDevice", "Eq8", "Eq8"]


@pytest.fixture
def fake_live(monkeypatch):
    """session and export faked: export writes `level` audio of `seconds` length at 160 BPM."""
    calls = []
    monkeypatch.setattr(session, "check", lambda client, where, **kw: calls.append(("check", where)) or "test_x")
    monkeypatch.setattr(session, "open_set", lambda client, name, **kw: calls.append(("open", name)) or 5.0)

    def export(client, out, start, length, mode="Main"):
        calls.append(("export", start, length, mode))
        seconds = length * 60 / 160 if export.seconds is None else export.seconds
        sf.write(out, np.full((int(seconds * 44100), 2), export.level), 44100, subtype="FLOAT")
        return [out]
    export.level, export.seconds = 0.1, None
    monkeypatch.setattr(live_render, "export", export)
    return calls, export


def test_render_exports_once_checks_and_slices(kit, tmp_path, fake_live):
    calls, _ = fake_live
    man = PK.render(MockTransport([McpResult("ok", 160.0)]), "test_x_t4_demo", "t4", tmp_path / "out")
    assert calls[:3] == [("check", "render:start"), ("open", "test_x_t4_demo"), ("check", "render:loaded")]
    assert ("export", 0.0, 136.0, "Main") in calls
    assert [f.rsplit("/", 1)[1] for f in man["files"]] == [f"pattern_{k:02d}.wav" for k in range(4)]
    assert sf.info(man["files"][0]).duration == pytest.approx(12.0)   # 32 beats at 160 BPM
    assert json.loads((tmp_path / "out" / "manifest.json").read_text())["kit"]["P"] == 4


def test_render_stops_on_a_silent_or_short_render(kit, tmp_path, fake_live):
    _, export = fake_live
    export.level = 0.0
    with pytest.raises(audio.AudioError, match="silent"):
        PK.render(MockTransport([McpResult("ok", 160.0)]), "test_x_t4_demo", kit, tmp_path / "a")
    export.level, export.seconds = 0.1, 40.0
    with pytest.raises(audio.AudioError, match="long, expected 51.000"):
        PK.render(MockTransport([McpResult("ok", 160.0)]), "test_x_t4_demo", kit, tmp_path / "b")


def test_template_trims_and_doubles(rig, monkeypatch):
    planted_set(rig.set_path("test_src"))
    edits, ends = [], iter([200.0, 40.0])
    monkeypatch.setattr(session, "check", lambda client, where, **kw: "test_other")
    monkeypatch.setattr(session, "open_set", lambda client, name, **kw: 6.0)
    monkeypatch.setattr(session, "save", lambda name=None, **kw: edits.append(("save", name)) or True)
    monkeypatch.setattr(timeops, "song_end", lambda client: next(ends))
    monkeypatch.setattr(timeops, "delete", lambda client, start, length, tol: edits.append(("delete", start, length)))
    monkeypatch.setattr(timeops, "duplicate", lambda client, start, length, end, clips_from:
                        edits.append(("duplicate", start, length, end)))
    made = PK.template(MockTransport(), "t4", "test_src", 24.0, 56.0, 4)
    assert edits == [("delete", 56.0, 144.0), ("delete", 8.0, 16.0),
                     ("duplicate", 8.0, 32.0, 72.0), ("duplicate", 8.0, 64.0, 136.0), ("save", "test_kit_t4")]
    assert made == PK.Kit.load("t4") and made.set == "test_kit_t4" and rig.set_path("test_kit_t4").exists()


def test_template_refuses_odd_P_and_an_open_kit(rig, monkeypatch):
    with pytest.raises(ValueError, match="power of two"):
        PK.template(MockTransport(), "t3", "test_src", 0, 32, 3)
    monkeypatch.setattr(session, "check", lambda client, where, **kw: "test_kit_t4")
    with pytest.raises(Guard, match="is open"):
        PK.template(MockTransport(), "t4", "test_src", 24.0, 56.0, 4)
