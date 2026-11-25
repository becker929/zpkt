"""Live's built-in devices as the fake LOM makes them: parameter names, ranges, choices and what each one shows.

Names and order follow a dump of a real set (the industrial short's set-v8.json, now in zpkt-archive) for EQ Eight, Utility, Glue
Compressor, Compressor, Reverb and Limiter; raw ranges follow zpkt.live.knobs' measured conversions (EQ Eight's
frequency 0-1 on a log scale from 10 Hz to 22 kHz, Utility's gain dB/35, its width the square root of the fraction).
Saturator, Echo, Spectrum, Operator, Simpler and the racks are smaller: the parameters zpkt names, with GUESS ranges.
`browser_roots()` lays the same devices out as Live's browser does, so find_item and load_item work.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from zpkt.live.testing import display
from zpkt.live.testing.lom import BrowserItem, Device, DeviceParameter, DeviceType, RackDevice, SimplerDevice


@dataclass(frozen=True)
class Param:
    """One parameter: raw range, default, and what it shows. A parameter with `items` is quantized: 0..len-1."""

    name: str
    min: float = 0.0
    max: float = 1.0
    default: float = 0.0
    show: display.Show | None = None
    items: tuple[str, ...] = ()

    def make(self) -> DeviceParameter:
        return DeviceParameter(
            self.name, min=self.min, max=self.max, default=self.default, show=self.show, items=self.items
        )


@dataclass(frozen=True)
class Spec:
    """A built-in device: its browser name, class, kind and parameters after "Device On"."""

    name: str
    class_name: str
    kind: int
    params: tuple[Param, ...]
    rack: bool = False
    factory: Callable[..., Device] = field(default=Device)


OFF_ON = ("Off", "On")


def switch(name: str, on: bool = False) -> Param:
    return Param(name, default=1.0 if on else 0.0, items=OFF_ON)


def choice(name: str, items: Sequence[str], default: int = 0) -> Param:
    return Param(name, default=float(default), items=tuple(items))


def gain(name: str, lo: float, hi: float, default: float = 0.0) -> Param:
    """A gain in dB, raw value = dB."""
    return Param(name, lo, hi, default, display.decibels)


def freq(name: str, lo_hz: float, hi_hz: float, default_hz: float) -> Param:
    """A frequency, raw 0..1 on a log scale from lo_hz to hi_hz."""
    import math

    return Param(
        name,
        0.0,
        1.0,
        math.log(default_hz / lo_hz) / math.log(hi_hz / lo_hz),
        display.log_scale(lo_hz, hi_hz, display.hertz),
    )


def mix(name: str, default: float = 1.0) -> Param:
    """A 0..1 amount shown in percent (Dry/Wet)."""
    return Param(name, 0.0, 1.0, default, lambda v: display.percent(100 * v))


def time_log(name: str, lo_ms: float, hi_ms: float, default_ms: float) -> Param:
    import math

    return Param(
        name,
        0.0,
        1.0,
        math.log(default_ms / lo_ms) / math.log(hi_ms / lo_ms),
        display.log_scale(lo_ms, hi_ms, display.milliseconds),
    )


def number(name: str, lo: float, hi: float, default: float, suffix: str = "") -> Param:
    return Param(name, lo, hi, default, lambda v: display.three_digits(v) + suffix)


def _eq_band(n: int, side: str) -> tuple[Param, ...]:
    # GUESS: Live's defaults; here every A band is on, a bell at 0 dB, so a new EQ Eight changes nothing
    return (
        switch(f"{n} Filter On {side}", side == "A"),
        choice(f"{n} Filter Type {side}", EQ8_TYPES, 3),
        freq(f"{n} Frequency {side}", 10.0, 22000.0, EQ8_FREQS[n - 1]),
        gain(f"{n} Gain {side}", -15.0, 15.0),
        Param(f"{n} Q {side}", 0.0, 1.0, 0.3780, display.log_scale(0.1, 18.0, display.plain)),
    )


# GUESS for "Notch": the other names are in the dump; the order is the .als's Mode 0-7
EQ8_TYPES = (
    "High Pass 48dB",
    "High Pass 12dB",
    "Low Shelf",
    "Bell",
    "Notch",
    "High Shelf",
    "Low Pass 12dB",
    "Low Pass 48dB",
)
EQ8_FREQS = (30.0, 100.0, 250.0, 500.0, 1000.0, 2500.0, 5000.0, 18000.0)

EQ_EIGHT = Spec(
    "EQ Eight",
    "Eq8",
    DeviceType.audio_effect,
    (
        gain("Output", -12.0, 12.0),
        Param("Scale", -2.0, 2.0, 1.0, lambda v: display.percent(100 * v)),  # GUESS: the raw range
        switch("Adaptive Q", True),
        *(p for n in range(1, 9) for side in "AB" for p in _eq_band(n, side)),
    ),
)

UTILITY = Spec(
    "Utility",
    "StereoGain",
    DeviceType.audio_effect,
    (
        switch("Left Inv"),
        switch("Right Inv"),
        choice("Channel Mode", ("Left", "Stereo", "Right", "Swap"), 1),  # GUESS: the order
        Param("Stereo Width", 0.0, 2.0, 1.0, lambda v: display.percent(100 * v * v)),
        switch("Mono"),
        switch("Bass Mono"),
        freq("Bass Freq", 50.0, 500.0, 120.0),
        Param("Balance", -1.0, 1.0, 0.0, display.pan),
        Param("Output", -1.0, 1.0, 0.0, lambda v: display.MINUS_INF if v <= -1.0 else display.decibels(35.0 * v)),
        switch("Mute"),
        switch("DC Filter"),
    ),
)

GLUE = Spec(
    "Glue Compressor",
    "GlueCompressor",
    DeviceType.audio_effect,
    (
        gain("Threshold", -40.0, 0.0),
        gain("Range", 0.0, 70.0, 70.0),
        gain("Output", -20.0, 20.0),  # GUESS: the range
        choice("Attack", (".01", ".1", ".3", "1", "3", "10", "30"), 5),
        choice("Ratio", ("2", "4", "10")),
        choice("Release", (".1", ".2", ".4", ".6", ".8", "1.2", "Auto"), 3),  # GUESS: ".8" and "Auto"
        mix("Dry/Wet"),
        switch("Peak Clip In"),
        switch("S/C On"),
        gain("S/C Gain", -24.0, 24.0),
        mix("S/C Mix"),
        choice("S/C EQ Type", ("Low pass", "Band pass", "High pass", "Notch"), 2),
        switch("S/C EQ On"),
        freq("S/C EQ Freq", 30.0, 15000.0, 200.0),
        gain("S/C EQ Gain", -15.0, 15.0),
        number("S/C EQ Q", 0.1, 12.0, 0.71),
    ),
)

COMPRESSOR = Spec(
    "Compressor",
    "Compressor2",
    DeviceType.audio_effect,
    (
        gain("Threshold", -70.0, 6.0),
        Param("Ratio", 0.0, 1.0, 0.75, lambda u: "inf : 1" if u >= 1.0 else f"{1 / (1 - u):.2f} : 1"),
        Param("Expansion Ratio", 0.0, 1.0, 0.0, lambda u: f"1 : {1 + u:.2f}"),
        time_log("Attack", 0.01, 1000.0, 1.0),
        time_log("Release", 1.0, 3000.0, 30.0),
        switch("Auto Release On/Off"),
        gain("Output", -36.0, 36.0),
        switch("Makeup"),
        mix("Dry/Wet"),
        choice("Model", ("Peak", "RMS", "Expand")),
        choice("Env Mode", ("Lin", "Log"), 1),
        gain("Knee", 0.0, 18.0, 6.0),
        choice("LookAhead", ("0 ms", "1 ms", "10 ms")),
        switch("S/C Listen"),
        switch("S/C EQ On"),
        choice("S/C EQ Type", ("Low pass", "Band pass", "High pass", "Notch"), 2),
        freq("S/C EQ Freq", 30.0, 15000.0, 80.0),
        number("S/C EQ Q", 0.1, 12.0, 0.71),
        gain("S/C EQ Gain", -15.0, 15.0),
        switch("S/C On"),
        gain("S/C Gain", -24.0, 24.0),
        mix("S/C Mix"),
    ),
)

SATURATOR = Spec(
    "Saturator",
    "Saturator",
    DeviceType.audio_effect,
    (  # GUESS: ranges and choices
        gain("Drive", -36.0, 36.0),
        choice(
            "Type",
            (
                "Analog Clip",
                "Soft Sine",
                "Medium Curve",
                "Hard Curve",
                "Sinoid Fold",
                "Digital Clip",
                "Waveshaper",
                "Bit Crush",
            ),
        ),
        switch("Color"),
        gain("Base", -36.0, 36.0),
        freq("Freq", 30.0, 18500.0, 1000.0),
        mix("Width", 0.0),
        gain("Depth", -36.0, 36.0),
        gain("Output", -36.0, 36.0),
        mix("Dry/Wet"),
        choice("Post Clip Mode", ("Off", "Soft", "Hard")),
    ),
)

REVERB = Spec(
    "Reverb",
    "Reverb",
    DeviceType.audio_effect,
    (  # names from the dump; GUESS ranges
        time_log("Predelay", 0.5, 250.0, 2.5),
        switch("In Lo Cut On"),
        switch("In Hi Cut On", True),
        freq("Input Freq", 50.0, 18000.0, 830.0),
        number("Input Width", 0.5, 9.0, 5.85, " "),
        switch("ER Spin On", True),
        Param("ER Spin Rate", 0.0, 1.0, 0.3, display.log_scale(0.07, 1.3, display.hertz)),
        number("ER Spin Amount", 0.0, 55.0, 17.5, " "),
        number("ER Shape", 0.0, 1.0, 0.5, " "),
        switch("Diff. Hi On", True),
        choice("Diff. Hi Type", ("Shelf", "Cut")),
        freq("Diff. Hi Freq", 20.0, 16000.0, 4500.0),
        number("HiShelf Gain", 0.2, 1.0, 0.7, " "),
        switch("Diff. Lo On"),
        freq("Diff. Lo Freq", 20.0, 15000.0, 90.0),
        number("LowShelf Gain", 0.2, 1.0, 0.75, " "),
        switch("Chorus On", True),
        Param("Chorus Rate", 0.0, 1.0, 0.02, display.log_scale(0.01, 8.0, display.hertz)),
        number("Chorus Amount", 0.01, 4.0, 0.02, " "),
        time_log("Decay Time", 200.0, 60000.0, 2000.0),
        mix("Diffusion", 0.6),
        mix("Scale", 0.4),
        switch("Freeze On"),
        switch("Flat On", True),
        switch("Cut On", True),
        number("Room Size", 0.22, 500.0, 50.0, " "),
        choice("Size Smoothing", ("None", "Slow", "Fast"), 2),
        number("Stereo Image", 0.0, 120.0, 100.0, " "),
        choice("Density", ("Sparse", "Low", "Mid", "High"), 1),
        gain("Reflect Level", -30.0, 6.0),
        gain("Diffuse Level", -30.0, 6.0),
        mix("Dry/Wet"),
    ),
)

ECHO = Spec(
    "Echo",
    "Echo",
    DeviceType.audio_effect,
    (  # GUESS: names, ranges and choices
        choice("Channel Mode", ("Stereo", "Ping Pong", "Mid/Side")),
        switch("L Sync", True),
        choice("L 16th", tuple(str(n) for n in range(1, 17)), 2),
        time_log("L Time", 1.0, 5000.0, 250.0),
        switch("R Sync", True),
        choice("R 16th", tuple(str(n) for n in range(1, 17)), 2),
        switch("Link", True),
        mix("Feedback", 0.5),
        switch("Filter On", True),
        freq("HP Freq", 20.0, 20000.0, 100.0),
        freq("LP Freq", 20.0, 20000.0, 8000.0),
        gain("Input Gain", -36.0, 36.0),
        gain("Output Gain", -36.0, 36.0),
        mix("Stereo Width", 1.0),
        mix("Dry/Wet", 0.5),
    ),
)

LIMITER = Spec(
    "Limiter",
    "Limiter",
    DeviceType.audio_effect,
    (
        gain("Input Gain", -24.0, 24.0),
        gain("Ceiling", -24.0, 0.0, -0.3),
        time_log("Release", 1.0, 3000.0, 100.0),
        switch("Auto", True),
        mix("Link"),
        mix("M/S Link", 0.0),
        choice("Lookahead", ("1.5 ms", "3 ms", "6 ms"), 1),
        choice("Routing", ("L/R", "M/S")),
        choice("Mode", ("Standard", "Soft Clip", "True Peak")),
        switch("Maximize On"),
        gain("Threshold", -24.0, 0.0, -0.3),
        gain("Output", -24.0, 0.0),
    ),
)

SPECTRUM = Spec(
    "Spectrum",
    "SpectrumAnalyzer",
    DeviceType.audio_effect,
    (  # GUESS
        choice("Block", ("1024", "2048", "4096", "8192", "16384"), 2),
        choice("Channel", ("L+R", "L", "R")),
        number("Refresh", 10.0, 1000.0, 60.0, " ms"),
        number("Avg", 1.0, 100.0, 1.0),
    ),
)

OPERATOR = Spec(
    "Operator",
    "Operator",
    DeviceType.instrument,
    (  # GUESS: a few of its parameters
        choice(
            "Osc-A Wave",
            (
                "Sin",
                "Sin 4 Bit",
                "Sin 8 Bit",
                "Saw 3",
                "Saw 4",
                "Saw 6",
                "Saw 8",
                "Saw 16",
                "Saw 32",
                "Saw 64",
                "Saw D",
                "Squ 3",
                "Squ 4",
                "Squ 6",
                "Squ 8",
                "Squ 16",
                "Squ 32",
                "Squ 64",
                "Squ D",
                "Tri",
                "Noise Looped",
                "Noise White",
            ),
        ),
        switch("Filter On", True),
        freq("Filter Freq", 30.0, 18500.0, 18500.0),
        mix("Filter Res", 0.2),
        time_log("Ae Attack", 0.01, 20000.0, 0.01),
        time_log("Ae Decay", 1.0, 20000.0, 600.0),
        gain("Ae Sustain", -70.0, 0.0),
        time_log("Ae Release", 1.0, 20000.0, 50.0),
        gain("Volume", -70.0, 6.0, -12.0),
    ),
)

SIMPLER = Spec(
    "Simpler",
    "OriginalSimpler",
    DeviceType.instrument,
    (  # GUESS: a few of its parameters
        gain("Volume", -70.0, 6.0, -12.0),
        Param("Pan", -1.0, 1.0, 0.0, display.pan),
        number("Transpose", -48.0, 48.0, 0.0, " st"),
        freq("Filter Freq", 30.0, 22000.0, 22000.0),
        mix("Filter Res", 0.0),
        time_log("Ve Attack", 0.1, 20000.0, 0.1),
        time_log("Ve Release", 1.0, 60000.0, 50.0),
    ),
    factory=SimplerDevice,
)

MACROS = tuple(Param(f"Macro {n}", 0.0, 127.0, 0.0, lambda v: f"{v:.0f}") for n in range(1, 17))
AUDIO_RACK = Spec(
    "Audio Effect Rack",
    "AudioEffectGroupDevice",
    DeviceType.audio_effect,
    (Param("Chain Selector", 0.0, 127.0, 0.0, lambda v: f"{v:.0f}"), *MACROS),
    rack=True,
)
INSTRUMENT_RACK = Spec(
    "Instrument Rack",
    "InstrumentGroupDevice",
    DeviceType.instrument,
    (Param("Chain Selector", 0.0, 127.0, 0.0, lambda v: f"{v:.0f}"), *MACROS),
    rack=True,
)
DRUM_RACK = Spec("Drum Rack", "DrumGroupDevice", DeviceType.instrument, MACROS, rack=True)

STOCK: dict[str, Spec] = {
    s.name: s
    for s in (
        EQ_EIGHT,
        UTILITY,
        GLUE,
        COMPRESSOR,
        SATURATOR,
        REVERB,
        ECHO,
        LIMITER,
        SPECTRUM,
        OPERATOR,
        SIMPLER,
        AUDIO_RACK,
        INSTRUMENT_RACK,
        DRUM_RACK,
    )
}


def make(device: str, *, name: str | None = None, on: bool = True) -> Device:
    """A new built-in device by its browser name ("EQ Eight"), at its defaults; `name` renames it ("desk EQ")."""
    spec = STOCK.get(device)
    if spec is None:
        raise KeyError(f"the fake has no built-in device {device!r}; it has: {', '.join(STOCK)}")
    params = [switch("Device On", on).make(), *(p.make() for p in spec.params)]
    label = name or spec.name
    if spec.rack:
        return RackDevice(label, spec.class_name, params, class_display_name=spec.name, kind=spec.kind)
    return spec.factory(label, spec.class_name, params, class_display_name=spec.name, kind=spec.kind)


def _param_from_fields(p: Mapping[str, object]) -> Param:
    """Param from a dict of its fields (a JSON set description, so no `show`); "value" is not one of them."""
    unknown = set(p) - {"name", "min", "max", "default", "items", "value"}
    if unknown:
        raise TypeError(f"Param got unexpected fields {sorted(unknown)}")
    items = p.get("items", ())
    if not isinstance(items, Iterable) or isinstance(items, str):
        raise TypeError(f"Param items must be a list of names, not {items!r}")
    return Param(
        name=str(p["name"]),
        min=_number(p.get("min", 0.0)),
        max=_number(p.get("max", 1.0)),
        default=_number(p.get("default", 0.0)),
        items=tuple(str(i) for i in items),
    )


def _number(v: object) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise TypeError(f"expected a number, got {v!r}")
    return float(v)


def custom(
    name: str, class_name: str, params: Sequence[Mapping[str, object]], *, kind: int = DeviceType.audio_effect
) -> Device:
    """A device the catalog lacks (a plug-in): each param a dict of Param's fields, "value" for where it starts."""
    made = [switch("Device On", True).make()]
    for p in params:
        param = _param_from_fields(p).make()
        if "value" in p:
            param._values["value"] = param._check(p["value"])
        made.append(param)
    return Device(name, class_name, made, kind=kind)


def browser_roots() -> dict[str, BrowserItem]:
    """The browser's categories with the catalog's devices in them (each a loadable item, as in Live 12)."""

    def items(kind: int, *, drums: bool = False) -> list[BrowserItem]:
        return [
            BrowserItem(s.name, loadable=True, device=s.name, folder=True)
            for s in STOCK.values()
            if s.kind == kind and (s.class_name == "DrumGroupDevice") == drums
        ]

    return {
        "instruments": BrowserItem("Instruments", items(DeviceType.instrument), folder=True),
        "audio_effects": BrowserItem("Audio Effects", items(DeviceType.audio_effect), folder=True),
        "drums": BrowserItem("Drums", items(DeviceType.instrument, drums=True), folder=True),
        "midi_effects": BrowserItem("MIDI Effects", folder=True),
        "plugins": BrowserItem("Plug-Ins", [BrowserItem("VST3", folder=True), BrowserItem("AUv2", folder=True)]),
    }
