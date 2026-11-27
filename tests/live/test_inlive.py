"""zpkt.live.inlive: the helpers that run in hands and inside Live. Each is tested three ways: imported, loaded by
file path with nothing but the stdlib (as the mix desk's pager loads it in Live), and sent as source in a code string
to FakeLive (as hands sends it)."""

from __future__ import annotations

import ast
import importlib.util
import math
import sys
from pathlib import Path

import pytest

from zpkt.live import inlive
from zpkt.live.inlive import shown, tracks
from zpkt.live.testing import FakeLive, fake_set, hw002_like

SET = {
    "tracks": [{"name": "Kick bus"}, {"name": "X-Ray"}, {"name": "Space"}],
    "returns": [{"name": "Space"}, {"name": "Echo"}],
}


@pytest.mark.parametrize("module", inlive.MODULES)
def test_each_module_is_stdlib_python_311_and_loads_by_path_alone(module, monkeypatch):
    text = inlive.source(module)
    tree = ast.parse(text, feature_version=(3, 11))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= set(sys.stdlib_module_names), imported
    assert "__future__" not in text  # it is pasted above other code in a code string
    monkeypatch.setattr(sys, "path", [p for p in sys.path if not Path(p, "zpkt").is_dir()])
    spec = importlib.util.spec_from_file_location(f"inlive_{module}", inlive.path(module))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    assert callable(next(v for k, v in vars(loaded).items() if not k.startswith("_") and callable(v)))


def test_an_unknown_module_is_refused():
    with pytest.raises(ValueError, match="no inlive module 'nope'; there are tracks, shown, keys, find, steps"):
        inlive.path("nope")


# --------------------------------------------------------------------------- tracks


def test_main_names_and_short_return_names():
    assert tracks.is_main("Main") and tracks.is_main(" master ") and not tracks.is_main("Main bus")
    assert tracks.short_name("A-Space", True) == "Space" and tracks.short_name("A-Space", False) == "A-Space"
    assert tracks.short_name("A-", True) == "A-"


def test_find_track_prefers_exact_names_then_returns_without_their_letter():
    song = fake_set(SET)
    assert tracks.find_track(song, "main") is song.master_track
    assert tracks.find_track(song, "Space") is song.tracks[2]  # an exact name wins over a return's short name
    assert tracks.find_track(song, "B-Echo") is song.return_tracks[1]
    assert tracks.find_track(song, "Echo") is song.return_tracks[1]
    with pytest.raises(LookupError, match="no track, return or Main named 'Ray'"):
        tracks.find_track(song, "Ray")  # only a return's letter is dropped, not a track's prefix


def test_the_expression_finds_what_find_track_finds():
    with FakeLive(fake_set(SET)) as live:
        names = ["Kick bus", "X-Ray", "Space", "A-Space", "Echo", "B-Echo", "Main", "MASTER"]
        code = inlive.with_source(
            f"result = [[find_track(song, n).name, eval(track_expr(n)).name] for n in {names!r}]", "tracks"
        )
        for by_function, by_expression in live.run(code):
            assert by_function == by_expression
        with pytest.raises(Exception, match="StopIteration"):
            live.run(f"result = {tracks.track_expr('Ray')}.name")


# --------------------------------------------------------------------------- shown


class Param:
    """A parameter with a display law, the way Live's look from the LOM."""

    def __init__(self, show, lo=0.0, hi=1.0, value=0.0, items=None, name="p"):
        self.name, self.min, self.max, self.value, self._show = name, lo, hi, value, show
        self.value_items, self.is_quantized = list(items or []), bool(items)

    def str_for_value(self, v):
        return self.value_items[round(v - self.min)] if self.value_items else self._show(v)


def freq(v):  # 10 Hz .. 22 kHz, log, as EQ Eight shows it
    f = 10 * 2200**v
    return f"{f / 1000:.2f} kHz" if f >= 1000 else f"{f:.1f} Hz"


def test_shown_numbers_share_a_base_unit():
    assert shown.shown_number("1.73 kHz") == pytest.approx(1730)
    assert shown.shown_number("2.5 ms") == pytest.approx(0.0025) and shown.shown_number("1 s") == 1.0
    assert shown.shown_number("-inf dB") == -1e9 and shown.shown_number("inf") == 1e9
    assert shown.shown_number("35 %") == 35 and shown.shown_number("Saw D") is None


def test_raw_for_bisects_what_live_shows():
    p = Param(freq)
    assert freq(shown.raw_for(p, "1.2 kHz")) == "1.20 kHz"
    assert freq(shown.raw_for(p, "200 Hz")) == "200.0 Hz"
    falling = Param(lambda v: f"{-60 * v:.1f} dB")  # a display that falls as the value rises
    assert falling.str_for_value(shown.raw_for(falling, "-30 dB")) == "-30.0 dB"
    assert shown.raw_for(p, "min") == 0.0 and shown.raw_for(p, "MAX") == 1.0
    p.value = 0.3
    assert shown.raw_for(p, "current") == 0.3
    assert shown.raw_for(p, "loud") is None


def test_raw_for_finds_list_items_by_name():
    wave = Param(None, 0.0, 3.0, items=["Sine", "Saw D", "Square D", "Noise White"])
    assert shown.raw_for(wave, "Saw D") == 1.0 and shown.raw_for(wave, "square d") == 2.0
    assert shown.raw_for(wave, "Triangle") is None


def test_set_shown_writes_text_numbers_and_says_what_failed():
    p = Param(lambda v: f"{20 * math.log10(v) if v > 0 else -math.inf:.1f} dB", 0.0, 2.0)
    assert shown.set_shown(p, "-6 dB") is None and p.str_for_value(p.value) == "-6.0 dB"
    assert shown.set_shown(p, 5) is None and p.value == 2.0  # a raw number is clamped to the range
    wave = Param(None, 0.0, 3.0, items=["Sine", "Saw D", "Square D", "Noise White"], name="Osc-A Wave")
    assert shown.set_shown(wave, "Triangle") == "Osc-A Wave=Triangle? Sine|Saw D|Square D|Noise White"
    assert shown.set_shown(p, "loud", "Gain") == "Gain=loud? not a value it shows"


def test_set_shown_in_fakelive_sets_what_live_shows():
    with FakeLive(hw002_like()) as live:
        code = inlive.with_source(
            "d = next(d for d in find_track(song, 'Kick bus').devices if d.name == 'desk EQ')\n"
            "p = next(p for p in d.parameters if p.name == '1 Frequency A')\n"
            "result = set_shown(p, '120 Hz')",
            "tracks",
            "shown",
        )
        assert live.run(code) is None
        read = code.replace("result = set_shown(p, '120 Hz')", "result = str(p)")
        assert live.run(read).startswith("120")
        assert not any(c.readbacks for c in live.calls)
