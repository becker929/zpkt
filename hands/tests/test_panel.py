"""hands panel: a spec becomes a track, a render and a control panel; the set is left as it was."""
from __future__ import annotations

import json
import math
import types
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from typer.testing import CliRunner

from hands.live import panel
from hands.live.transport import McpResult, Transport


class Param:
    def __init__(self, name, value=0.0, lo=0.0, hi=1.0, items=None, show=None):
        self.name, self.value, self.min, self.max = name, value, lo, hi
        self.value_items, self.is_quantized, self._show = items or [], bool(items), show

    def str_for_value(self, v):
        if self.value_items:
            return self.value_items[int(round(v - self.min))]
        return self._show(v) if self._show else f"{v:.2f}"


def hz(v):   # 20 Hz .. 20 kHz, exponential, shown the way Live does
    f = 20 * 1000 ** v
    return f"{f / 1000:.2f} kHz" if f >= 1000 else f"{f:.0f} Hz"


def operator():
    return types.SimpleNamespace(name="Operator", parameters=[
        Param("Device On", 1.0, items=["Off", "On"]), Param("Osc-A Wave", 0.0, 0.0, 3.0, items=["Sine", "Saw D", "Square D", "Noise White"]),
        Param("Filter Freq", 0.5, show=hz), Param("Filter Res", 0.2, show=lambda v: f"{v * 100:.0f} %"),
        Param("Volume", 0.8, show=lambda v: "-inf dB" if v <= 0 else f"{20 * math.log10(v):.1f} dB"), Param("Tone", 0.3),
        Param("Ae Decay", 0.6), Param("Ae Release", 0.5)])


class Item:
    def __init__(self, name, make=None, children=()):
        self.name, self.make, self.children = name, make, list(children)
        self.is_folder, self.is_loadable = bool(children), make is not None


class Track:
    is_foldable, can_be_armed = False, True

    def __init__(self, name, clips=()):
        self.name, self.devices, self.arm, self.arrangement_clips, self.notes = name, [], False, list(clips), None

    def create_midi_clip(self, start, length):
        clip = types.SimpleNamespace(name="", start_time=start, end_time=start + length, add_new_notes=lambda notes: setattr(self, "notes", notes))
        self.arrangement_clips.append(clip)
        return clip

    def delete_clip(self, clip):
        self.arrangement_clips.remove(clip)


class FakeLive(Transport):
    """A small Live: runs the code the way the Remote Script does (exec, then `result`)."""

    def __init__(self):
        mix = Track("mix", [types.SimpleNamespace(end_time=64.0)])
        mix.arm = True
        s = self.song = types.SimpleNamespace(tracks=[mix], is_playing=False, tempo=160.0, loop=True, start_time=4.0, current_song_time=12.0)
        s.view = types.SimpleNamespace(selected_track=mix)
        s.create_midi_track = lambda i: s.tracks.append(Track("MIDI"))
        s.delete_track = lambda i: s.tracks.pop(i)
        s.stop_playing = lambda: None
        self.browser = types.SimpleNamespace(
            instruments=Item("Instruments", children=[Item("Operator", operator, [Item("Acid Bass.adv", operator)])]),
            plugins=Item("Plug-ins"), sounds=Item("Sounds"), drums=Item("Drums"))
        self.browser.load_item = lambda item: s.view.selected_track.devices.append(item.make())
        self.live = types.SimpleNamespace(Clip=types.SimpleNamespace(MidiNoteSpecification=lambda **kw: kw))
        self.calls = []

    def execute(self, code):
        self.calls.append(code)
        scope = {"song": self.song, "browser": self.browser, "Live": self.live}
        try:
            exec(compile(code, "<lom>", "exec"), scope)
        except Exception as exc:  # noqa: BLE001
            return McpResult("error", error=f"{type(exc).__name__}: {exc}")
        return McpResult("ok", scope.get("result"))


def recorder(seen):
    """A take the way record_span leaves it: 0.5 s of junk, silence for the lead-in, then a tone."""
    def record(*, transport, filename, output_dir, start_beat, duration_beats, tail_beats, tempo, n_tracks, armed, before, after):
        transport.run(before + "\nresult = 'ok'")
        try:
            sr, spb, lead = 8000, 60.0 / tempo, panel.lead_beats(tempo)
            assert transport.song.tempo == tempo and n_tracks == len(transport.song.tracks)
            seen.append({"start": start_beat, "beats": duration_beats, "tempo": tempo, "clips": len(transport.song.tracks[-1].arrangement_clips)})
            n = lambda beats: int(round(beats * spb * sr))  # noqa: E731
            x = np.concatenate([np.full(sr // 2, 0.9), np.zeros(n(lead)), np.full(n(duration_beats - lead + tail_beats), 0.5)])
            path = str(Path(output_dir) / filename)
            sf.write(path, np.column_stack([x, x]), sr, subtype="FLOAT")
            Path(path + ".timing.json").write_text(json.dumps({"song_zero_seconds": 0.5, "clip_start": start_beat, "tempo": tempo}))
            return path
        finally:
            from hands.live.agent import with_prelude
            transport.run(with_prelude(after + "\nresult = 'ok'"))
    return record


SPEC = {"name": "Funk Bass", "instrument": "Operator", "tempo": 100,
        "params": {"Osc-A Wave": "saw", "Filter Freq": "2 kHz", "Filter Res": "40 %", "Tone": "50%", "Volume": 0.7},
        "notes": [["A1", 0, 0.5, 110], ["C2", 1.5, 0.25]], "beats": 8, "controls": ["Filter Freq", {"param": "Osc-A Wave", "label": "Wave"}, "Device On"]}


def spec_of(text):
    return json.loads(text.split("```zpkt-surface\n")[1].split("\n```")[0])


def test_pitch_names_follow_live():
    assert [panel.pitch(p) for p in ("C3", "A1", "C#3", "Bb2", 61, "C-2")] == [60, 45, 61, 58, 61, 0]
    with pytest.raises(panel.PanelError, match="C3 is 60"):
        panel.pitch("H2")


def test_a_pattern_repeats_to_fill_the_riff():
    notes, beats = panel.riff({"notes": [["A1", 0, 0.5, 110], ["C2", 3.5, 1.0]], "beats": 8})
    assert beats == 8 and [(p, s) for p, s, _, _ in notes] == [(45, 0), (48, 3.5), (45, 4), (48, 7.5)]
    assert notes[-1][2] == 0.5 and notes[1][3] == 100          # the last note stops at the end; velocity defaults to 100
    with pytest.raises(panel.PanelError, match="real time"):
        panel.riff({"notes": [[60, 0, 1]], "beats": 4000})
    assert panel.riff({"chords": "Am7,Dm9"})[1] == 8


def test_readings_share_a_base_unit():
    assert panel.reading("1.2 kHz") == (1200.0, "hz") and panel.reading("250 ms") == (250.0, "ms")
    assert panel.reading("1.5 s") == (1500.0, "ms") and panel.reading("-inf dB")[0] == -math.inf and panel.reading("Saw D") is None


def test_make_sets_renders_and_leaves_the_set_as_it_was(tmp_path):
    live, seen = FakeLive(), []
    text = panel.make(live, SPEC, tmp_path, recorder=recorder(seen))
    song = live.song
    track = song.tracks[-1]
    by = {p.name: p for p in track.devices[0].parameters}
    assert track.name == "panel funk-bass" and [t.name for t in song.tracks] == ["mix", "panel funk-bass"]
    assert by["Osc-A Wave"].value == 1 and by["Filter Res"].value == pytest.approx(0.4, abs=1e-4)
    assert 20 * 1000 ** by["Filter Freq"].value == pytest.approx(2000, rel=0.01)
    assert by["Tone"].value == 0.5 and by["Volume"].value == 0.7
    # rendered past the end of the arrangement, at the spec's tempo, with the riff in place
    assert seen == [{"start": 81.0, "beats": 11.0, "tempo": 100.0, "clips": 1}]
    assert len(track.notes) == 4 and track.notes[0]["pitch"] == 45
    # and everything else is back: no clip, tempo, loop, markers, selection, arm states
    assert track.arrangement_clips == [] and (song.tempo, song.loop, song.start_time, song.current_song_time) == (160.0, True, 4.0, 12.0)
    assert song.view.selected_track is song.tracks[0] and [t.arm for t in song.tracks] == [True, False]
    # the file is the riff alone: lead-in cut, as long as beats + tail
    x, sr = sf.read(tmp_path / "funk-bass.wav")
    assert len(x) / sr == pytest.approx(10 * 0.6, abs=0.01) and abs(x[0]).max() == pytest.approx(0.5, abs=1e-3)
    assert not list(tmp_path.glob(".*"))
    surface = spec_of(text)
    freq, wave, on = surface["controls"]
    assert "```audio\n" in text and "funk-bass.wav\n```" in text and surface["panel"] == "funk-bass"
    assert freq["kind"] == "knob" and freq["display"][0] == "20 Hz" and freq["display"][-1] == "20.00 kHz" and len(freq["display"]) == 9
    assert wave == {"kind": "knob", "id": "osc_a_wave", "label": "Wave", "min": 0, "max": 3, "value": 1, "step": 1,
                    "display": ["Sine", "Saw D", "Square D", "Noise White"], "midiSlot": 1}
    assert on == {"kind": "toggle", "id": "device_on", "label": "Device On", "value": True, "midiSlot": 2}


def test_apply_takes_the_page_state_and_makes_a_before_after_deck(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    live, seen = FakeLive(), []
    panel.make(live, SPEC, Path("renders"), recorder=recorder(seen))
    state = {"id": "s/1/0", "title": "x", "values": {"filter_freq": 0.25, "device_on": False, "ab": "b", "gone": 3}}
    text = panel.apply(live, "funk-bass", Path("renders"), state_values=state, spec={"params": {"Filter Res": "10 %"}}, recorder=recorder(seen))
    by = {p.name: p for p in live.song.tracks[-1].devices[0].parameters}
    assert by["Filter Freq"].value == 0.25 and by["Device On"].value == 0 and by["Filter Res"].value == pytest.approx(0.1, abs=1e-4)
    surface = spec_of(text)
    assert surface["controls"][0]["value"] == 0.25 and surface["controls"][2]["value"] is False
    deck = surface["controls"][-1]
    assert deck["kind"] == "ab" and (deck["a"]["src"], deck["b"]["src"]) == ("renders/funk-bass.wav", "renders/funk-bass-2.wav")
    assert deck["a"]["bpm"] == 100 and deck["loop"] == {"startBar": 1, "bars": 2} and "panel funk-bass v2" in text
    assert live.song.tracks[-1].arrangement_clips == [] and live.song.tempo == 160.0


def test_a_wrong_name_fails_with_close_names_and_leaves_nothing(tmp_path):
    live = FakeLive()
    with pytest.raises(panel.PanelError, match="close names: Filter Freq"):
        panel.make(live, {**SPEC, "params": {"Filter Frequency": 0.5}}, tmp_path, recorder=recorder([]))
    assert [t.name for t in live.song.tracks] == ["mix"]
    with pytest.raises(panel.PanelError, match="it has: Sine, Saw D"):
        panel.make(live, {**SPEC, "params": {"Osc-A Wave": "Triangle"}}, tmp_path, recorder=recorder([]))
    with pytest.raises(panel.LiveError if hasattr(panel, "LiveError") else Exception, match="no loadable 'Wavetable'"):
        panel.make(live, {**SPEC, "instrument": "Wavetable"}, tmp_path, recorder=recorder([]))
    assert [t.name for t in live.song.tracks] == ["mix"] and live.song.tempo == 160.0


def test_out_of_range_text_is_clamped_with_a_warning(tmp_path):
    text = panel.make(FakeLive(), {**SPEC, "params": {"Filter Freq": "5 Hz"}}, tmp_path, recorder=recorder([]))
    assert "warning: Filter Freq: 5 hz is outside its range; used 20 Hz" in text


def test_make_refuses_while_live_plays_and_when_the_panel_exists(tmp_path):
    live = FakeLive()
    live.song.is_playing = True
    with pytest.raises(panel.PanelError, match="Live is playing"):
        panel.make(live, SPEC, tmp_path, recorder=recorder([]))
    live.song.is_playing = False
    panel.make(live, SPEC, tmp_path, recorder=recorder([]))
    with pytest.raises(panel.PanelError, match="exists"):
        panel.make(live, SPEC, tmp_path, recorder=recorder([]))
    panel.make(live, {**SPEC, "instrument": "Operator/Acid Bass"}, tmp_path, replace=True, recorder=recorder([]))
    assert [t.name for t in live.song.tracks] == ["mix", "panel funk-bass"]
    assert panel.drop(live, "funk-bass", tmp_path).startswith("deleted") and [t.name for t in live.song.tracks] == ["mix"]


def test_params_lists_from_the_cache_after_the_first_read(tmp_path):
    live = FakeLive()
    text = panel.params(live, "Operator", "filter|wave")
    assert text.splitlines()[1:] == ["Osc-A Wave | 0..3 | 0 = Sine | Sine, Saw D, Square D, Noise White", "Filter Freq | 0..1 | 0.5 = 632 Hz", "Filter Res | 0..1 | 0.2 = 20 %"]
    assert [t.name for t in live.song.tracks] == ["mix"]
    assert "3 of 8" in panel.params(None, "Operator", "filter|wave")       # no Live needed the second time


def test_cli_reads_the_spec_from_stdin(tmp_path, monkeypatch):
    from hands.cli import app
    live = FakeLive()
    monkeypatch.setattr("hands.live.panel_cli.LiveClient", lambda host, port: live)
    monkeypatch.setattr(panel, "_recorder", lambda: recorder([]))
    res = CliRunner().invoke(app, ["panel", "make", "--spec", "-", "--out", str(tmp_path)], input=json.dumps(SPEC))
    assert res.exit_code == 0 and "```zpkt-surface" in res.stdout
    res = CliRunner().invoke(app, ["panel", "make", "--spec", "{nope", "--out", str(tmp_path)])
    assert res.exit_code == 2


def test_a_sequence_climbs_and_rests():
    notes, period = panel.sequence("A B C D", every=4)
    assert [n[0] for n in notes] == [57, 59, 60, 62] and [n[1] for n in notes] == [0, 4, 8, 12] and period == 16
    notes, period = panel.sequence("A1, - , G1 C2", every=0.5, gate=0.5)
    assert [(n[0], n[1], n[2]) for n in notes] == [(45, 0, 0.25), (43, 1.0, 0.25), (48, 1.5, 0.25)] and period == 2
    assert [n[0] for n in panel.sequence("C B A")[0]] == [48, 47, 45]            # nearest, so this one descends
    with pytest.raises(panel.PanelError, match="cannot read the note 'H'"):
        panel.sequence("A H")


def test_plain_words_make_a_panel_with_a_name_of_its_own(tmp_path):
    live, seen = FakeLive(), []
    text = panel.make(live, {"sound": "sawtooth", "seq": "A B C D", "every": 4, "tempo": 120}, tmp_path, recorder=recorder(seen))
    track = live.song.tracks[-1]
    assert track.name == "panel sawtooth-a-b-c-d" and {p.name: p.value for p in track.devices[0].parameters}["Osc-A Wave"] == 1
    assert seen[0]["beats"] == 3 + 16 and [n["start_time"] for n in track.notes] == [0, 4, 8, 12]
    assert [c["label"] for c in spec_of(text)["controls"]] == ["Cutoff", "Resonance", "Decay", "Release"]
    panel.make(live, {"sound": "sawtooth", "seq": "A B C D", "every": 4}, tmp_path, recorder=recorder(seen))
    assert live.song.tracks[-1].name == "panel sawtooth-a-b-c-d-2"
    text = panel.apply(live, "sawtooth-a-b-c-d", tmp_path, spec={"sound": "square", "seq": "A C", "every": 2}, recorder=recorder(seen))
    assert {p.name: p.value for p in live.song.tracks[1].devices[0].parameters}["Osc-A Wave"] == 2 and "4 beats" in text
    with pytest.raises(panel.PanelError, match="no sound 'banjo'"):
        panel.make(live, {"sound": "banjo", "seq": "A"}, tmp_path, recorder=recorder(seen))
