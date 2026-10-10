"""hands.plans offline: knob ids, canonical plans and keys, write-ahead, packing into kit batches, the cache with
nearest neighbours, the A/B file, and `hands plan` end to end with stand-in renders (no Live)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
sf = pytest.importorskip("soundfile")
pytest.importorskip("pyloudnorm")

from hands.plans.abfile import build, integrated  # noqa: E402
from hands.plans.cache import Cache  # noqa: E402
from hands.plans.model import KnobId, KnobInfo, Plan, distance, write_ahead  # noqa: E402
from hands.plans.render import FakeRenderer, Planner  # noqa: E402

DRIVE = "rumble|plugin:Decapitator|Drive"
EQ = "chord|Eq8:0|Bands.1/ParameterA/Gain"
INFO = {DRIVE: KnobInfo(0.27, 0.0, 1.0), EQ: KnobInfo(3.1, -15.0, 15.0)}


def fake_reader(kit, knobs):
    return {k: INFO[k] for k in knobs}


@pytest.fixture
def kit_dirs(tmp_path, monkeypatch):
    kits, sets = tmp_path / "kits", tmp_path / "sets"
    kits.mkdir()
    sets.mkdir()
    (kits / "t4.json").write_text(json.dumps({"kit": "t4", "set": "kit_t4", "lead": 8.0, "pattern_beats": 32.0, "P": 4}))
    xml = b'<?xml version="1.0"?><Ableton><LiveSet><MainTrack><DeviceChain><Mixer><Tempo><Manual Value="160" />' \
          b'</Tempo></Mixer></DeviceChain></MainTrack></LiveSet></Ableton>'
    (sets / "kit_t4.als").write_bytes(gzip.compress(xml))
    monkeypatch.setenv("HANDS_KITS", str(kits))
    monkeypatch.setenv("HANDS_SETS", str(sets))
    monkeypatch.setenv("HANDS_PLANS", str(tmp_path / "plans"))
    return kits, sets


@pytest.fixture
def planner(kit_dirs, tmp_path):
    return Planner(cache=Cache(tmp_path / "plans"), renderer=FakeRenderer(tmp_path / "work"), reader=fake_reader)


# --- the model ---------------------------------------------------------------------------------------------------

def test_knob_ids_parse_and_resolve():
    assert KnobId.parse(DRIVE).resolve_args() == ("rumble", ("plugin", "Decapitator"), "Drive")
    assert KnobId.parse(EQ).resolve_args() == ("chord", ("Eq8", 0), "Bands.1/ParameterA/Gain")
    assert KnobId.parse("S01 kick group|Mixer|Volume").resolve_args() == ("S01 kick group", "Mixer", "Volume")
    assert KnobId.parse("x|Eq8:-1|Gain").resolve_args() == ("x", ("Eq8", -1), "Gain")
    for bad in ("rumble|Drive", "a|Eq8|Gain", "a|Eq8:x|Gain", "|Mixer|Volume"):
        with pytest.raises(ValueError):
            KnobId.parse(bad)


def test_the_canonical_plan_ignores_knobs_at_the_kits_value_and_rounding_noise():
    a = Plan("t4", {DRIVE: 0.5, EQ: 3.1})
    b = Plan("t4", {DRIVE: 0.50000001})
    assert a.canonical(INFO) == {DRIVE: 0.5}
    assert a.key("v1", INFO) == b.key("v1", INFO)
    assert a.key("v1", INFO) != a.key("v2", INFO), "a rebuilt kit gets new keys"
    assert Plan("t4", {}).key("v1", INFO) == Plan("t4", {EQ: 3.1}).key("v1", INFO)


def test_distances_are_scaled_to_each_knobs_range():
    # 0.1 of Drive's 0-1 range and 3 dB of the EQ's 30 dB range are the same distance.
    assert distance({DRIVE: 0.37}, {DRIVE: 0.27}, INFO) == pytest.approx(distance({EQ: 6.1}, {EQ: 3.1}, INFO))
    assert distance({DRIVE: 0.27}, {}, INFO) == 0.0


def test_write_ahead_guesses_more_and_the_other_end_within_range():
    a, b = Plan("t4", {DRIVE: 0.4}, "drive 40%"), Plan("t4", {DRIVE: 0.5}, "drive 50%")
    more, other = write_ahead(a, b, INFO)
    assert more.knobs[DRIVE] == pytest.approx(0.6) and more.label == "more: drive 50%"
    assert other.knobs[DRIVE] == pytest.approx(0.3) and other.label == "the other end: drive 40%"
    clamped = write_ahead(Plan("t4", {DRIVE: 0.2}), Plan("t4", {DRIVE: 0.9}), INFO)
    assert [g.knobs[DRIVE] for g in clamped] == [1.0, 0.0]
    assert write_ahead(a, a, INFO) == []
    # A knob only B moves: "the other end" pushes it below the kit's value.
    guesses = write_ahead(Plan("t4", {}), Plan("t4", {EQ: 9.1}), INFO)
    assert [g.knobs[EQ] for g in guesses] == pytest.approx([15.0, -2.9])


# --- packing and the cache ---------------------------------------------------------------------------------------

def test_plans_are_packed_into_one_render_per_P_and_kept(planner):
    plans = [Plan("t4", {DRIVE: v}) for v in (0.3, 0.4, 0.5)]
    r = planner.ensure(plans)
    assert len(planner.renderer.calls) == 1, "three plans fit one 4-pattern batch"
    patterns = planner.renderer.calls[0]
    assert [p[DRIVE] for p in patterns] == [0.3, 0.4, 0.5, 0.3], "the spare pattern repeats the first plan"
    assert len(r.rendered) == 3 and all(e.audio.is_file() for e in r.entries)

    again = planner.ensure(plans)
    assert len(planner.renderer.calls) == 1, "all cached: nothing renders"
    assert sorted(again.cached) == sorted(r.rendered)

    six = [Plan("t4", {DRIVE: v}) for v in (0.6, 0.7, 0.8, 0.9, 1.0, 0.0)]
    planner.ensure(six)
    assert len(planner.renderer.calls) == 3, "six new plans: two batches"


def test_an_ab_renders_its_write_ahead_in_the_same_pass(planner):
    a, b = Plan("t4", {DRIVE: 0.4}), Plan("t4", {DRIVE: 0.5})
    r = planner.ensure([a, b], ahead_of=(a, b))
    assert len(planner.renderer.calls) == 1
    assert sorted(p[DRIVE] for p in planner.renderer.calls[0]) == pytest.approx([0.3, 0.4, 0.5, 0.6])
    assert [e.plan.label[:4] for e in r.ahead] == ["more", "the "]
    # "More" is then already rendered: the next A/B (B against more) renders only its own guesses.
    more = r.ahead[0].plan
    planner.ensure([b, more])
    assert len(planner.renderer.calls) == 1


def test_lookup_finds_exact_hits_and_near_neighbours(planner):
    planner.ensure([Plan("t4", {DRIVE: 0.5, EQ: 6.1})])
    assert planner.lookup(Plan("t4", {DRIVE: 0.5, EQ: 6.1}))["hit"] is True
    near = planner.lookup(Plan("t4", {DRIVE: 0.52, EQ: 6.1}))
    assert near["hit"] is False and near["nearest"]["distance"] == pytest.approx(0.02)
    assert "nearest" not in planner.lookup(Plan("t4", {DRIVE: 0.9}))


# --- the A/B file --------------------------------------------------------------------------------------------------

def tone(path: Path, hz: float, amp: float, bars: int, bar_s: float, sr: int = 44_100) -> Path:
    t = np.arange(int(bars * bar_s * sr)) / sr
    y = amp * np.sin(2 * np.pi * hz * t)
    sf.write(path, np.stack([y, y], axis=1).astype(np.float32), sr, subtype="FLOAT")
    return path


def dominant(x: np.ndarray, sr: int) -> float:
    spec = np.abs(np.fft.rfft(x[:, 0] * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / sr)[np.argmax(spec)])


def test_the_ab_file_alternates_every_bar_at_one_loudness(tmp_path):
    bar_s, sr = 0.5, 44_100
    a = tone(tmp_path / "a.wav", 330, 0.05, 8, bar_s)            # quiet
    b = tone(tmp_path / "b.wav", 550, 0.5, 8, bar_s)             # 20 dB louder
    f = build(a, b, tmp_path / "ab.flac", bar_s)
    assert f.bars == 7, "the first bar (the previous pattern's tail) is dropped"
    assert f.loudness["B"] - f.loudness["A"] == pytest.approx(20, abs=0.5)
    assert f.present("drive 40%", "drive 50%") == {"bar_seconds": 0.5, "bars": 7, "first": "A", "every": 1,
                                                   "a": "drive 40%", "b": "drive 50%"}
    y, rate = sf.read(tmp_path / "ab.flac", always_2d=True)
    assert len(y) == 7 * int(bar_s * sr)
    bar = int(bar_s * sr)
    sides = [dominant(y[k * bar + 2000:(k + 1) * bar - 2000], rate) for k in range(7)]
    assert [round(s, -1) for s in sides] == [330, 550, 330, 550, 330, 550, 330]
    louds = [integrated(y[k * bar:(k + 1) * bar], rate) for k in (0, 1)]
    assert abs(louds[0] - louds[1]) < 0.5, "both sides at the same loudness"
    assert np.max(np.abs(np.diff(y[:, 0]))) < 0.2, "no clicks at the joins"


def test_switching_every_two_bars_starting_with_b(tmp_path):
    a = tone(tmp_path / "a.wav", 330, 0.2, 9, 0.25)
    b = tone(tmp_path / "b.wav", 550, 0.2, 9, 0.25)
    f = build(a, b, tmp_path / "ab.wav", 0.25, first="B", every=2)
    y, sr = sf.read(tmp_path / "ab.wav", always_2d=True)
    bar = int(0.25 * sr)
    sides = [round(dominant(y[k * bar + 1000:(k + 1) * bar - 1000], sr), -1) for k in range(f.bars)]
    assert sides == [550, 550, 330, 330, 550, 550, 330, 330]


# --- `hands plan`, end to end with stand-in renders ---------------------------------------------------------------

def test_the_cli_makes_an_ab_and_renders_ahead(kit_dirs, monkeypatch):
    from typer.testing import CliRunner

    import hands.plans.render as R
    from hands.cli import app

    monkeypatch.setattr(R, "KnobReader", lambda: fake_reader)
    runner = CliRunner()
    a = json.dumps({"kit": "t4", "knobs": {DRIVE: 0.4}, "label": "drive 40%"})
    b = json.dumps({"kit": "t4", "knobs": {DRIVE: 0.5}, "label": "drive 50%"})
    res = runner.invoke(app, ["plan", "ab", a, b, "--fake"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    assert Path(out["path"]).is_file() and out["ab"]["a"] == "drive 40%" and out["ab"]["bars"] == 7
    assert out["rendered"] == 4 and [x["label"] for x in out["ahead"]] == ["more: drive 50%", "the other end: drive 40%"]

    more = json.dumps(out["ahead"][0]["plan"])
    res2 = runner.invoke(app, ["plan", "ab", b, more, "--fake", "--no-write-ahead"])
    assert json.loads(res2.output)["rendered"] == 0, "'more' was rendered ahead: it plays at once"

    res3 = runner.invoke(app, ["plan", "lookup", json.dumps({"kit": "t4", "knobs": {DRIVE: 0.41}})])
    assert json.loads(res3.output)["nearest"]["distance"] == pytest.approx(0.01)
