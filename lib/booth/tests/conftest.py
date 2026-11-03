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
    def __init__(self, value=0.0, name=""):
        self.value, self.name = value, name

    def str_for_value(self, v):
        return f"{v:.1f} dB"


class Clip:
    def __init__(self, start, length):
        self.start_time, self.end_time, self.notes = start, start + length, []

    def add_new_notes(self, specs):
        self.notes.extend(specs)

    def get_notes_extended(self, p0, pn, t0, tn):
        return list(self.notes)


class AudioClip:
    """Live's arrangement audio clip, as far as the booth uses it. Like Live: a new clip is auto-warped at a tempo it
    guesses (100 BPM here) and looped; unwarping moves the start marker to the first transient (0.12 s here); markers
    are clip beats when warped and file seconds when not; an unwarped clip's transpose plays it faster, like tape.
    warp_markers ends in Live's shadow marker: 1/32 beat after the last real one, at the tempo before it, and it can't
    be deleted (Live 12.4, 2026-11-03)."""

    GUESS_BPM, TRANSIENT_S = 100.0, 0.12

    def __init__(self, song, path, start):
        self.song, self.file_path, self.start_time = song, str(path), float(start)
        self.seconds = sf.info(str(path)).duration
        self.is_audio_clip, self.looping, self.pitch_coarse, self.warp_mode = True, True, 0, 0
        self._warping = True
        self._wm = [WarpMarker(0.0, 0.0), WarpMarker(self.seconds, self.seconds * self.GUESS_BPM / 60)]
        self.start_marker = self.loop_start = 0.0
        self.end_marker = self.loop_end = self._wm[-1].beat_time

    SHADOW = 1 / 32

    @property
    def warp_markers(self):
        if not self._wm:
            return []
        last = self._wm[-1]
        rate = ((last.beat_time - self._wm[-2].beat_time) / (last.sample_time - self._wm[-2].sample_time)
                if len(self._wm) > 1 and last.sample_time > self._wm[-2].sample_time else self.GUESS_BPM / 60)
        if rate <= 0:
            return list(self._wm)
        return [*self._wm, WarpMarker(last.sample_time + self.SHADOW / rate, last.beat_time + self.SHADOW)]

    @property
    def warping(self):
        return self._warping

    @warping.setter
    def warping(self, on):
        if bool(on) == self._warping:
            return
        self._warping = bool(on)
        if on:
            self.start_marker = self.loop_start = 0.0
            self.end_marker = self.loop_end = self.seconds * self.GUESS_BPM / 60
        else:
            self.start_marker = self.loop_start = self.TRANSIENT_S
            self.end_marker = self.loop_end = self.seconds

    @property
    def end_time(self):
        span = self.end_marker - self.start_marker
        if self._warping:
            return self.start_time + span
        return self.start_time + span * self.song.tempo / 60 / 2 ** (self.pitch_coarse / 12)

    def add_warp_marker(self, w):
        self._wm = sorted([*self._wm, w], key=lambda m: m.beat_time)

    def remove_warp_marker(self, beat):
        if not any(abs(m.beat_time - beat) < 1e-9 for m in self._wm):
            raise RuntimeError("The shadow marker can't be deleted." if abs(self.warp_markers[-1].beat_time - beat) < 1e-9
                               else "The specified warp marker doesn't exist")
        self._wm = [m for m in self._wm if abs(m.beat_time - beat) > 1e-9]

    def move_warp_marker(self, beat, distance):
        for m in self._wm:
            if abs(m.beat_time - beat) < 1e-9:
                m.beat_time += distance

    def copy(self, start):
        c = AudioClip.__new__(AudioClip)
        c.__dict__.update(self.__dict__, start_time=float(start), _wm=[WarpMarker(m.sample_time, m.beat_time) for m in self._wm])
        return c


class WarpMarker:
    def __init__(self, sample_time, beat_time):
        self.sample_time, self.beat_time = sample_time, beat_time


class Track:
    def __init__(self, song=None, audio=False):
        self.song = song
        self.name, self.devices, self.arrangement_clips = "", [], []
        self.has_midi_input = not audio
        self.mixer_device = types.SimpleNamespace(panning=Param(), volume=Param(), sends=[Param(), Param()])

    def delete_clip(self, c):
        self.arrangement_clips.remove(c)

    def create_midi_clip(self, start, length):
        if not self.has_midi_input:
            raise RuntimeError("create_midi_clip on an audio track")
        self.arrangement_clips.append(Clip(start, length))

    def create_audio_clip(self, path, start):
        if self.has_midi_input:
            raise RuntimeError("create_audio_clip on a MIDI track")
        self.arrangement_clips.append(AudioClip(self.song, path, start))
        return self.arrangement_clips[-1]

    def duplicate_clip_to_arrangement(self, clip, start):
        self.arrangement_clips.append(clip.copy(start))


class Sample:
    def __init__(self, path):
        self.file_path, self.warping, self.slicing_style, self._slices = str(path), True, 0, [0]

    @property
    def slices(self):
        return list(self._slices)

    def clear_slices(self):
        self._slices = [0]

    def insert_slice(self, frame):
        if frame not in self._slices:
            self._slices = sorted([*self._slices, int(frame)])


class Simpler:
    def __init__(self):
        self.name, self.can_have_drum_pads, self.can_have_chains, self.parameters = "Simpler", False, False, []
        self.sample, self.playback_mode = None, 0

    def replace_sample(self, path):
        self.sample = Sample(path)


class Song:
    def __init__(self, master=("EQ Eight", "Glue Compressor", "Limiter")):
        self.tracks, self.tempo = [], 120.0
        self.signature_numerator = self.signature_denominator = 4
        self.master_track = types.SimpleNamespace(devices=[types.SimpleNamespace(name=n, parameters=[Param(6.0, "Input Gain")])
                                                           for n in master])
        self.return_tracks = [types.SimpleNamespace(name="A-Reverb"), types.SimpleNamespace(name="B-Delay")]

    def create_midi_track(self, index):
        self.tracks.append(Track(self))

    def create_audio_track(self, index):
        t = Track(self, audio=True)
        self.tracks.insert(len(self.tracks) if index == -1 else index, t)

    def delete_track(self, index):
        if len(self.tracks) < 2:
            raise RuntimeError("Live keeps one track")
        del self.tracks[index]


class FakeLive:
    """run(code) the way the Remote Script does: an expression, else statements that set `result`."""

    def __init__(self, song=None):
        self.song = song or Song()
        self.calls: list[str] = []
        self.live_mod = types.SimpleNamespace(Clip=types.SimpleNamespace(MidiNoteSpecification=lambda **k: k, WarpMarker=WarpMarker))
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

    def __init__(self, live: FakeLive, *, export_silent=False, devices_override=None, level=0.3):
        self.live, self.export_silent, self.devices_override = live, export_silent, devices_override
        self.level = level                       # the render's sine amplitude
        self.loads, self.sets, self.mixes, self.exports = [], [], [], []

    def _track(self, path):
        return eval(path, {"song": self.live.song})

    def load_item(self, path, root, folder, name):
        self.loads.append((path, root, folder, name))
        if (root, name) == ("instruments", "Simpler"):
            self._track(path).devices.append(Simpler())
            return
        self._track(path).devices.append(types.SimpleNamespace(name=name.rsplit(".", 1)[0], can_have_drum_pads=False,
                                                               can_have_chains=False, parameters=[]))

    def devices(self, path):
        if self.devices_override:
            return self.devices_override
        return [d.name for d in self._track(path).devices]

    def setp(self, dev, params):
        self.sets.append((dev, dict(params)))
        if dev.startswith("song.master_track") and "Input Gain" in params:
            db = float(params["Input Gain"].split()[0])
            self._track(dev).parameters[0].value = db
            self.level = min(0.9, self.level * 10 ** ((db - 6.0) / 20))

    def mixer(self, track, vol_db=None, sends=(), pan=None):
        self.mixes.append((track, vol_db, tuple(sends), pan))
        self._track(track).mixer_device.panning.value = float(pan or 0.0)

    def export(self, out, start_beat, length_beats, bits=24):
        sr = 44100
        seconds = length_beats * 60 / self.live.song.tempo
        t = np.arange(int(sr * seconds)) / sr
        self.exports.append(Path(out).name)
        y = np.zeros_like(t) if self.export_silent else self.level * np.sin(2 * np.pi * 110 * t) * (0.4 + 0.6 * (t > seconds / 2))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        sf.write(out, np.stack([y, y], 1), sr, subtype="PCM_24")
        return Path(out)


def make_sample(seconds: float = 2.0, *, hits: int = 4, sr: int = 44100, seed: int = 1) -> dict:
    """A sample in the booth's store without ffmpeg: decaying noise bursts, `hits` of them, evenly spaced."""
    from booth import samples as S
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    y = np.zeros(n)
    for k in range(hits):
        a = int(k * n / hits)
        m = min(n - a, int(0.25 * sr))
        y[a:a + m] += 0.5 * rng.standard_normal(m) * np.exp(-np.arange(m) / (0.04 * sr))
    S.DIR.mkdir(parents=True, exist_ok=True)
    sid = f"{seed:04x}{int(seconds * 1000):06x}{hits:06x}"[:16]
    wav = S.DIR / f"{sid}.wav"
    sf.write(wav, np.stack([y, y], 1), sr, subtype="PCM_24")
    meta = {**S._measure(wav), "sample": sid, "format": "wav", "bytes": wav.stat().st_size, "added": 0}
    (S.DIR / f"{sid}.json").write_text(json.dumps(meta))
    return meta


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """(live, ops): booth.live's Builder wired to the fakes, the guard always passing, sets in tmp_path."""
    from booth import live as booth_live
    from hands.live import session
    lv = FakeLive()
    fo = FakeOps(lv)
    monkeypatch.setattr(booth_live, "ops", lambda client=None: fo)
    monkeypatch.setattr(session, "check", lambda client, where, **k: k.get("expect_front") or "booth_x")
    def open_set(client, name, **k):     # a set opens fresh from its file: the template's one empty track
        lv.song = Song()
        lv.song.create_midi_track(-1)
        lv.song.tracks[0].name = "p1"
        return 1.0
    monkeypatch.setattr(session, "open_set", open_set)
    monkeypatch.setattr(session, "copy_set", lambda a, b: tmp_path / f"{b}.als")
    monkeypatch.setattr(session, "_front", lambda *a, **k: None)   # asks macOS (osascript); CI runs on Linux
    template = session.config.rig().set_path("booth_template")
    template.parent.mkdir(parents=True, exist_ok=True)
    template.write_text("")
    return lv, fo
