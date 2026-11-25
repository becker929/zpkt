"""What Live shows for a parameter's value: the text laws behind the fake LOM's `str(parameter)` and `str_for_value`.

Formats follow a dump of a real set made over the LOM (the industrial short's set-v8.json, now in zpkt-archive): three significant
digits ("0.00 dB", "-14.8 dB", "121 ms", "1.14 kHz", even Live's own "100.0 Hz"), mixer volume with one decimal and
"-inf dB" at the bottom, pan as "C", "25L", "50R". Live does not publish its fader law or every unit; those spots say
GUESS, and stay monotonic and consistent so that zpkt's bisections over the text find what they look for.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

Show = Callable[[float], str]

MINUS_INF = "-inf dB"
FLOOR_DB = -70.0  # Live shows anything quieter as -inf (zpkt.live.als.SILENT is the same floor in linear gain)


def _no_minus_zero(text: str) -> str:
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def three_digits(x: float) -> str:
    """Live's usual precision. Rounding can show a fourth digit, as Live does ("100.0" for 99.97)."""
    a = abs(x)
    text = f"{x:.2f}" if a < 10 else f"{x:.1f}" if a < 100 else f"{x:.0f}"
    return _no_minus_zero(text)


def decibels(db: float) -> str:
    """A device's gain: "0.00 dB", "-14.8 dB"; -inf below the floor."""
    return MINUS_INF if db < FLOOR_DB else f"{three_digits(db)} dB"


def hertz(f: float) -> str:
    """A frequency: "22.0 Hz", "120 Hz", "1.14 kHz", "10.0 kHz"."""
    return f"{three_digits(f)} Hz" if f < 1000 else f"{three_digits(f / 1000)} kHz"


def milliseconds(ms: float) -> str:
    """A time: "0.01 ms", "121 ms"; a second or more as "4.00 s"."""
    return f"{three_digits(ms)} ms" if ms < 1000 else f"{three_digits(ms / 1000)} s"


def percent(p: float) -> str:
    """A percentage: "100 %", "56 %", "0.0 %". GUESS: below 10 % Live shows one decimal for most parameters."""
    return _no_minus_zero(f"{p:.1f}") + " %" if abs(p) < 10 else _no_minus_zero(f"{p:.0f}") + " %"


def plain(x: float) -> str:
    """A number without a unit ("0.71"), as EQ Eight's Q shows."""
    return three_digits(x)


def pan(v: float) -> str:
    """Mixer pan, -1..1: "C", "25L", "50R"."""
    n = round(abs(v) * 50)
    return "C" if n == 0 else f"{n}{'L' if v < 0 else 'R'}"


def fader_db(v: float) -> float:
    """Mixer volume (0..1) in dB. GUESS: Live does not publish its fader law. This one keeps what zpkt relies on:
    0.85 is 0 dB, 1.0 is +6 dB and 0 is silence; 40 dB per unit above 0.4, a log tail below it."""
    if v <= 0:
        return -math.inf
    if v >= 0.4:
        return 40.0 * (v - 0.85)
    return -18.0 + 35.0 * math.log10(v / 0.4)


def volume(v: float) -> str:
    """Track volume as Live's mixer shows it: one decimal ("0.0 dB", "-2.5 dB", "6.0 dB"), else "-inf dB"."""
    db = fader_db(v)
    return MINUS_INF if db < FLOOR_DB else _no_minus_zero(f"{db:.1f}") + " dB"


def send(v: float) -> str:
    """A send (0..1): like volume, but its top is 0 dB. GUESS: the volume law 6 dB down."""
    db = fader_db(v) - 6.0
    return MINUS_INF if db < FLOOR_DB else _no_minus_zero(f"{db:.1f}") + " dB"


def choice(items: Sequence[str]) -> Show:
    """A quantized parameter shows the name of its step."""

    def show(v: float) -> str:
        return items[max(0, min(len(items) - 1, round(v)))]

    return show


def log_scale(lo: float, hi: float, unit: Show) -> Show:
    """A 0..1 raw value on a log scale from lo to hi (EQ Eight's frequency is 10 Hz-22 kHz this way)."""
    return lambda u: unit(lo * (hi / lo) ** u)


def linear(lo: float, hi: float, unit: Show) -> Show:
    """A 0..1 raw value mapped straight onto lo..hi."""
    return lambda u: unit(lo + (hi - lo) * u)
