"""How a parameter's value in the .als maps onto its value in the LOM, per device and parameter.

The LOM shows a parameter under another name and often in other units than the .als: EQ Eight's frequency is 0-1 on
a log scale, Utility's gain is dB/35, its width the square root of the .als fraction. Each Unit converts one way and
back; UNITS, EQ8_BAND and MIXER say which unit and LOM name a parameter has. They were measured on HW002 (the
evidence pairs are by UNITS). zpkt.live.knobs uses them to write knobs given in .als units.
"""

from __future__ import annotations

import math
import re
from typing import Any


class Unit:
    """How a parameter's .als value maps onto its LOM value."""

    def to_lom(self, v: Any) -> Any:
        return float(v)

    def from_lom(self, u: Any) -> Any:
        return float(u)


class Lin(Unit):
    def __init__(self, lo: float, hi: float) -> None:
        self.lo, self.hi = lo, hi

    def to_lom(self, v: Any) -> Any:
        return (float(v) - self.lo) / (self.hi - self.lo)

    def from_lom(self, u: Any) -> Any:
        return self.lo + float(u) * (self.hi - self.lo)


class Log(Lin):
    def to_lom(self, v: Any) -> Any:
        return math.log(float(v) / self.lo) / math.log(self.hi / self.lo)

    def from_lom(self, u: Any) -> Any:
        return self.lo * (self.hi / self.lo) ** float(u)


class Bool(Unit):
    def to_lom(self, v: Any) -> Any:
        if not isinstance(v, bool):
            raise TypeError(f"a switch takes True/False, not {v!r}")
        return 1.0 if v else 0.0

    def from_lom(self, u: Any) -> Any:
        return float(u) >= 0.5


class Db35(Unit):
    """Utility's gain: linear amplitude in the .als, dB/35 (-1..1) in the LOM."""

    def to_lom(self, v: Any) -> Any:
        return -1.0 if v <= 0 else max(-1.0, min(1.0, 20 * math.log10(v) / 35))

    def from_lom(self, u: Any) -> Any:
        return 10 ** (float(u) * 35 / 20)


class Sqrt(Unit):
    """Utility's width: a fraction 0-4 in the .als, its square root 0-2 in the LOM."""

    def to_lom(self, v: Any) -> Any:
        return math.sqrt(float(v))

    def from_lom(self, u: Any) -> Any:
        return float(u) ** 2


class Ratio(Unit):
    """Compressor ratio: r in the .als, 1 - 1/r in the LOM."""

    def to_lom(self, v: Any) -> Any:
        return 1 - 1 / float(v)

    def from_lom(self, u: Any) -> Any:
        return math.inf if float(u) >= 1 else 1 / (1 - float(u))


class Fader(Unit):
    """Mixer volume: linear gain in the .als; in the LOM a fader position whose dB only Live
    knows (str_for_value), so Live finds the position by bisection on the display."""

    def to_lom(self, v: Any) -> Any:
        """The target in dB; None for silence (0 or less), which is the bottom of the fader, -inf."""
        return 20 * math.log10(v) if v > 0 else None

    def from_lom(self, display: Any) -> Any:
        text = display.replace(" dB", "")
        return 0.0 if "inf" in text else 10 ** (float(text) / 20)


class Mute(Unit):
    """The track's activator (Mixer Speaker): True is on. The LOM sets track.mute to the opposite."""

    def to_lom(self, v: Any) -> Any:
        if not isinstance(v, bool):
            raise TypeError(f"a track's activator takes True/False, not {v!r}")
        return v

    def from_lom(self, u: Any) -> Any:
        return bool(u)


SAME, BOOL, MUTE, FADER = Unit(), Bool(), Mute(), Fader()

# (device tag, .als param) -> (LOM parameter name, unit). Evidence pairs, .als -> LOM:
#   Utility Gain 0.4084238708 -> -0.2222222 (-7.78 dB / 35); StereoWidth 0.8770471 -> 0.9365079;
#   BassMonoFrequency 120 -> 0.3802112 (log 50-500); EQ Eight Freq 30.95 Hz -> 0.1468144 and
#   5000 Hz -> 0.8074892 (log 10-22000), Q 2.2926 -> 0.6031746 (log 0.1-18), Gain -14.256 ->
#   -14.256; Compressor Ratio 3 -> 0.6666667, Attack 0.0791 ms -> 0.1796875 (log 0.01-1000);
#   Reverb MixDirect -> Dry/Wet as is (probe-pack bench, 6 Oct); plugin parameters 0-1 as is.
UNITS: dict[tuple[str, str], tuple[str, Unit]] = {
    ("StereoGain", "Gain"): ("Output", Db35()),
    ("StereoGain", "StereoWidth"): ("Stereo Width", Sqrt()),
    ("StereoGain", "BassMono"): ("Bass Mono", BOOL),
    ("StereoGain", "BassMonoFrequency"): ("Bass Freq", Log(50.0, 500.0)),
    ("StereoGain", "Balance"): ("Balance", SAME),
    ("StereoGain", "ChannelMode"): ("Channel Mode", SAME),
    ("StereoGain", "Mono"): ("Mono", BOOL),
    ("Eq8", "GlobalGain"): ("Output", SAME),
    ("Eq8", "Scale"): ("Scale", SAME),
    ("Compressor2", "Ratio"): ("Ratio", Ratio()),
    ("Compressor2", "Attack"): ("Attack", Log(0.01, 1000.0)),
    ("Compressor2", "Knee"): ("Knee", SAME),
    ("Reverb", "MixDirect"): ("Dry/Wet", SAME),
}
EQ8_FREQ = Log(10.0, 22000.0)
EQ8_BAND: dict[str, tuple[str, Unit]] = {
    "Freq": ("Frequency", EQ8_FREQ),
    "Gain": ("Gain", SAME),
    "Q": ("Q", Log(0.1, 18.0)),
    "IsOn": ("Filter On", BOOL),
    "Mode": ("Filter Type", SAME),
}
_BAND_PATH = re.compile(r"Bands\.(\d)/Parameter([AB])/(\w+)")
MIXER: dict[str, tuple[str, Unit]] = {"Volume": ("volume", FADER), "Pan": ("pan", SAME), "Speaker": ("mute", MUTE)}
