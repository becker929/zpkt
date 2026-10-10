"""hands.live.knobs: canonical ids, measured unit conversions, and the LOM code run on a fake song."""
from __future__ import annotations

import math

import pytest

from hands.live import knobs
from hands.live.knobs import Knob, KnobError
from hands.live.transport import McpResult, Transport

CHORD = "12-2022-06-02-001 [2026-05-25 092256]"


# --------------------------------------------------------------------------- ids

@pytest.mark.parametrize("knob, text", [
    (Knob(CHORD, ("StereoGain", 0), "Gain"), f"{CHORD}/StereoGain#0/Gain"),
    (Knob("S01 kick group", ("Compressor2", 0), "Ratio"), "S01 kick group/Compressor2#0/Ratio"),
    (Knob("Break group", ("plugin", "Dist COLDFIRE"), "Color"), "Break group/plugin:Dist COLDFIRE/Color"),
    (Knob("S01 perc group", "Reverb", "MixDirect"), "S01 perc group/Reverb#-1/MixDirect"),
    (Knob("kick", ("Eq8", 0), "Bands.3/ParameterA/Freq"), "kick/Eq8#0/Bands.3/ParameterA/Freq"),
    (Knob("S01 perc group", "Mixer", "Sends/TrackSendHolder/Send"), "S01 perc group/Mixer/Sends/TrackSendHolder/Send"),
])
def test_ids_round_trip(knob, text):
    assert knob.id == text == str(knob)
    assert Knob.parse(text) == knob


def test_knobs_compare_by_value():
    assert Knob("t", ["Eq8", 1], "Scale") == Knob("t", ("Eq8", 1), "Scale")
    assert len({Knob("t", "Eq8", "Scale"), Knob("t", ("Eq8", -1), "Scale")}) == 1
    assert Knob("t", ("Eq8", 1), "Scale").spec == ("t", ("Eq8", 1), "Scale")
    with pytest.raises(ValueError, match="'/'"):
        Knob("a/b", "Mixer", "Volume")


# --------------------------------------------------------------------------- units

@pytest.mark.parametrize("device, param, als, lom", [
    (("StereoGain", 0), "Gain", 0.4084238708, -0.2222222238779068),
    (("StereoGain", 0), "Gain", 0.7673615217, -0.0657142773270607),
    (("StereoGain", 0), "StereoWidth", 0.8770471215, 0.9365079402923584),
    (("StereoGain", 0), "StereoWidth", 1.0, 1.0),
    (("StereoGain", 0), "BassMonoFrequency", 120.0, 0.3802112340927124),
    (("Eq8", 0), "Bands.0/ParameterA/Freq", 30.9539299, 0.14681440591812134),
    (("Eq8", 0), "Bands.1/ParameterA/Freq", 59.9429665, 0.23268698155879974),
    (("Eq8", 0), "Bands.2/ParameterA/Freq", 269.084961, 0.4278002977371216),
    (("Eq8", 0), "Bands.3/ParameterA/Freq", 5000.00098, 0.8074891567230225),
    (("Eq8", 0), "Bands.0/ParameterA/Q", 2.29257298, 0.60317462682724),
    (("Eq8", 0), "Bands.0/ParameterB/Q", 0.7071067095, 0.37666621804237366),
    (("Eq8", 0), "Bands.0/ParameterA/Gain", -14.2561979, -14.256197929382324),
    (("Compressor2", 0), "Ratio", 3.00000024, 0.6666666865348816),
    (("Compressor2", 0), "Attack", 0.07914755493, 0.1796875),
])
def test_conversions_match_live(device, param, als, lom):
    """Pairs read from the same HW002 devices: the .als Manual value and the LOM value."""
    _, _, unit = knobs.lom_target(Knob("rumble", device, param))
    assert unit.to_lom(als) == pytest.approx(lom, abs=2e-6)
    assert unit.from_lom(lom) == pytest.approx(als, rel=1e-5)


@pytest.mark.parametrize("device, param, target", [
    (("Eq8", 1), "Bands.1/ParameterA/Gain", ("param", "2 Gain A")),
    (("Eq8", 0), "Bands.7/ParameterB/IsOn", ("param", "8 Filter On B")),
    (("PluginDevice", 2), "On", ("param", "Device On")),
    (("plugin", "ValhallaSupermassive"), "Delay_Ms", ("param", "Delay_Ms")),
    (("StereoGain", 0), "Gain", ("param", "Output")),
    ("Mixer", "Volume", ("volume", None)),
    ("Mixer", "Speaker", ("mute", None)),
])
def test_lom_targets(device, param, target):
    assert knobs.lom_target(Knob("t", device, param))[:2] == target


@pytest.mark.parametrize("device, param", [(("Compressor2", 0), "Threshold"), (("Hybrid", 0), "DryWet"),
                                           ("Mixer", "Sends/TrackSendHolder/Send")])
def test_unmeasured_conversions_are_refused(device, param):
    with pytest.raises(KeyError, match="no measured LOM conversion"):
        knobs.lom_target(Knob("t", device, param))


def test_fader_and_switch_values():
    assert knobs.FADER.to_lom(0.5) == pytest.approx(-6.0206, abs=1e-4)
    assert knobs.FADER.to_lom(0.0) == -1000.0
    assert knobs.FADER.from_lom("-6.0 dB") == pytest.approx(0.501187, abs=1e-6)
    assert knobs.FADER.from_lom("-inf dB") == 0.0
    with pytest.raises(TypeError):
        knobs.BOOL.to_lom(1)


# --------------------------------------------------------------------------- the LOM side

class Param:
    def __init__(self, name, value, lo=0.0, hi=1.0, automated=0, show=None, sticky=False):
        self.name, self._value, self.min, self.max = name, value, lo, hi
        self.automation_state, self.show, self.sticky = automated, show, sticky

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if not self.sticky:
            self._value = float(v)

    def str_for_value(self, v):
        return self.show(v) if self.show else f"{v:.2f}"


def fader_db(v):
    return "-inf dB" if v <= 0 else f"{40 * math.log10(v / 0.85):.1f} dB"


class Device:
    def __init__(self, name, class_name, *params):
        self.name, self.class_name = name, class_name
        self.parameters = [Param("Device On", 1.0)] + list(params)


class Track:
    def __init__(self, name, *devices):
        self.name, self.devices, self.mute = name, list(devices), False
        self.mixer_device = type("Mixer", (), {})()
        self.mixer_device.volume = Param("Track Volume", 0.85, show=fader_db)
        self.mixer_device.panning = Param("Track Panning", 0.0, -1.0, 1.0)


def song():
    s = type("Song", (), {})()
    s.tracks = [Track("rumble",
                      Device("Utility", "StereoGain", Param("Stereo Width", 1.0, 0.0, 2.0), Param("Output", 0.0, -1.0, 1.0)),
                      Device("Decapitator", "PluginDevice", Param("Drive", 0.27), Param("Tone", 0.2, automated=1)),
                      Device("EQ Eight", "Eq8", Param("1 Frequency A", 0.5), Param("1 Gain A", 0.0, -15.0, 15.0)))]
    s.return_tracks, s.master_track = [Track("A-Return")], Track("Main")
    return s


class LocalLom(Transport):
    """Runs the code the way the Remote Script does: exec, then return `result`."""

    def __init__(self, song):
        self.song, self.calls = song, []

    def execute(self, code):
        self.calls.append(code)
        scope = {"song": self.song}
        exec(compile(code, "<lom>", "exec"), scope)
        return McpResult("ok", scope.get("result"))


GAIN = Knob("rumble", ("StereoGain", 0), "Gain")
WIDTH = Knob("rumble", ("StereoGain", 0), "StereoWidth")
DRIVE = Knob("rumble", ("plugin", "Decapitator"), "Drive")
FREQ = Knob("rumble", ("Eq8", 0), "Bands.0/ParameterA/Freq")
EQ_ON = Knob("rumble", ("Eq8", 0), "On")
VOLUME = Knob("rumble", "Mixer", "Volume")
SPEAKER = Knob("rumble", "Mixer", "Speaker")
MAIN_PAN = Knob("Main", "Mixer", "Pan")


def test_set_many_writes_every_knob_in_one_call():
    s = song()
    live = LocalLom(s)
    written = knobs.set_many(live, {GAIN: 0.4084238708, DRIVE: 0.4, FREQ: 30.9539299, EQ_ON: False,
                                    VOLUME: 0.5, SPEAKER: False, MAIN_PAN: -0.25})
    assert len(live.calls) == 1
    rumble = s.tracks[0]
    assert rumble.devices[0].parameters[2].value == pytest.approx(-0.2222222, abs=1e-6)
    assert rumble.devices[1].parameters[1].value == 0.4
    assert rumble.devices[2].parameters[1].value == pytest.approx(0.1468144, abs=1e-6)
    assert rumble.devices[2].parameters[0].value == 0.0
    assert fader_db(rumble.mixer_device.volume.value) == "-6.0 dB" and written[VOLUME] == rumble.mixer_device.volume.value
    assert rumble.mute is True and written[SPEAKER] is False
    assert s.master_track.mixer_device.panning.value == -0.25


@pytest.mark.parametrize("values, why", [
    ({DRIVE: 0.5, Knob("rumble", ("plugin", "Decapitator"), "Tone"): 0.5}, "Tone: automated"),
    ({DRIVE: 0.5, Knob("rumble", ("plugin", "Echoboy"), "Mix"): 0.5}, "0 plugins named 'Echoboy'"),
    ({DRIVE: 0.5, WIDTH: 9.0}, "outside the LOM range"),
    ({DRIVE: 0.5, Knob("nope", "Mixer", "Pan"): 0.0}, "0 tracks named 'nope'"),
    ({DRIVE: 0.5, Knob("rumble", ("Eq8", 1), "On"): True}, "no Eq8 #1: the track has 1"),
])
def test_set_many_writes_nothing_when_any_knob_is_refused(values, why):
    s = song()
    with pytest.raises(KnobError, match=why):
        knobs.set_many(LocalLom(s), values)
    assert s.tracks[0].devices[1].parameters[1].value == 0.27


def test_read_many_converts_back_to_als_units():
    live = LocalLom(song())
    knobs.set_many(live, {GAIN: 0.4084238708, VOLUME: 0.5, SPEAKER: False, FREQ: 5000.0})
    got = knobs.read_many(live, [GAIN, VOLUME, SPEAKER, FREQ])
    assert got[GAIN].value == pytest.approx(0.4084238708, rel=1e-6) and got[GAIN].display == "-0.22"
    assert got[VOLUME].value == pytest.approx(0.5, rel=0.012) and got[VOLUME].display == "-6.0 dB"
    assert got[SPEAKER].value is False and not got[SPEAKER].automated
    assert got[FREQ].value == pytest.approx(5000.0, rel=1e-6)


def test_apply_reads_back_in_a_second_call_and_checks():
    s = song()
    live = LocalLom(s)
    got = knobs.apply(live, {DRIVE: 0.6, SPEAKER: False})
    assert len(live.calls) == 2 and "p.value = s[\"value\"]" in live.calls[0] and "p.value =" not in live.calls[1]
    assert got[DRIVE].value == 0.6
    s.tracks[0].devices[1].parameters[1].sticky = True   # Live keeps its old value
    with pytest.raises(KnobError, match="read back differs"):
        knobs.apply(LocalLom(s), {DRIVE: 0.7})


def test_type_and_size_limits_hold_before_any_call():
    live = LocalLom(song())
    with pytest.raises(TypeError):
        knobs.set_many(live, {EQ_ON: 1})
    many = {Knob("rumble", ("plugin", "Decapitator"), f"P{i}"): 0.5 for i in range(21)}
    with pytest.raises(ValueError, match="more than 20 parameters"):
        knobs.set_many(live, many)
    assert live.calls == []
