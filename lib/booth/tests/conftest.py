"""A fake Live for the booth's tests: the LOM code the booth generates really runs, against a small model of a song,
so a typo in a generated call fails here and not in Live."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

os.environ.setdefault("BOOTH_HOME", tempfile.mkdtemp(prefix="booth-test-"))

EXAMPLES = Path(__file__).resolve().parents[1] / "palettes" / "examples"


def example(name: str = "clockwork") -> dict:
    return json.loads((EXAMPLES / f"{name}.json").read_text())


class Param:
    def __init__(self, value=0.0):
        self.value = value


class Clip:
    def __init__(self, start, length):
        self.start_time, self.end_time, self.notes = start, start + length, []

    def add_new_notes(self, specs):
        self.notes.extend(specs)

    def get_notes_extended(self, p0, pn, t0, tn):
        return list(self.notes)


class Track:
    def __init__(self):
        self.name, self.devices, self.arrangement_clips = "", [], []
        self.mixer_device = types.SimpleNamespace(panning=Param(), volume=Param(), sends=[Param(), Param()])

    def delete_clip(self, c):
        self.arrangement_clips.remove(c)

    def create_midi_clip(self, start, length):
        self.arrangement_clips.append(Clip(start, length))


class Song:
    def __init__(self, master=("EQ Eight", "Glue Compressor", "Limiter")):
        self.tracks, self.tempo = [], 120.0
        self.signature_numerator = self.signature_denominator = 4
        self.master_track = types.SimpleNamespace(devices=[types.SimpleNamespace(name=n) for n in master])
        self.return_tracks = [types.SimpleNamespace(name="A-Reverb"), types.SimpleNamespace(name="B-Delay")]

    def create_midi_track(self, index):
        self.tracks.append(Track())


class FakeLive:
    """run(code) the way the Remote Script does: an expression, else statements that set `result`."""

    def __init__(self, song=None):
        self.song = song or Song()
        self.calls: list[str] = []
        self.live_mod = types.SimpleNamespace(Clip=types.SimpleNamespace(MidiNoteSpecification=lambda **k: k))
        sys.modules.setdefault("Live", self.live_mod)

    def run(self, code):
        self.calls.append(code)
        g = {"song": self.song, "Live": self.live_mod}
        try:
            return eval(compile(code, "<lom>", "eval"), g)
        except SyntaxError:
            exec(compile(code, "<lom>", "exec"), g)
            return g.get("result")


class FakeOps:
    """Stands in for liveops' GUI and browser helpers."""

    def __init__(self, live: FakeLive, *, export_silent=False, devices_override=None):
        self.live, self.export_silent, self.devices_override = live, export_silent, devices_override
        self.loads, self.sets, self.mixes = [], [], []

    def _track(self, path):
        return eval(path, {"song": self.live.song})

    def load_item(self, path, root, folder, name):
        self.loads.append((path, root, folder, name))
        self._track(path).devices.append(types.SimpleNamespace(name=name.rsplit(".", 1)[0]))

    def devices(self, path):
        if self.devices_override:
            return self.devices_override
        return [d.name for d in self._track(path).devices]

    def setp(self, dev, params):
        self.sets.append((dev, dict(params)))

    def mixer(self, track, vol_db=None, sends=(), pan=None):
        self.mixes.append((track, vol_db, tuple(sends), pan))
        self._track(track).mixer_device.panning.value = float(pan or 0.0)

    def export(self, out, start_beat, length_beats, bits=24):
        sr = 44100
        seconds = length_beats * 60 / self.live.song.tempo
        t = np.arange(int(sr * seconds)) / sr
        y = np.zeros_like(t) if self.export_silent else 0.3 * np.sin(2 * np.pi * 110 * t) * (0.4 + 0.6 * (t > seconds / 2))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, np.stack([y, y], 1), sr, subtype="PCM_24")
        return Path(out)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """(live, ops): booth.live's Builder wired to the fakes, the guard always passing, sets in tmp_path."""
    from booth import live as booth_live
    from hands.live import session
    lv = FakeLive()
    fo = FakeOps(lv)
    monkeypatch.setattr(booth_live, "ops", lambda client=None: fo)
    monkeypatch.setattr(session, "check", lambda client, where, **k: k.get("expect_front") or "booth_x")
    def open_set(client, name, **k):     # a set opens fresh from its file: the template is empty
        lv.song = Song()
        return 1.0
    monkeypatch.setattr(session, "open_set", open_set)
    monkeypatch.setattr(session, "copy_set", lambda a, b: tmp_path / f"{b}.als")
    template = session.config.rig().set_path("booth_template")
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("")
    return lv, fo
