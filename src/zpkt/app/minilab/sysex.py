"""The MiniLab's SysEx messages out: the display, a pad's LED and a knob's ring. Pure: they return the bytes.

The layouts are the ones Live's own MiniLab_3 script sends (zpkt's profile records where each came from). None has
been checked at the hardware: every message here is unverified. A message is a list of bytes from F0 to F7.
"""

from __future__ import annotations

from zpkt.app.minilab.profile import Control, Profile

LINE_1_BYTE, LINE_2_BYTE, END_OF_LINE = 1, 2, 0
Rgb = tuple[int, int, int]


def ascii_line(text: str, width: int) -> list[int]:
    """`text` as the display wants it: 7-bit printable ASCII (anything else becomes ?), cut to `width`, with no
    spaces at the ends."""
    cut = text[:width].strip()
    return [ord(c) if 32 <= ord(c) < 127 else ord("?") for c in cut]


def display(profile: Profile, line_1: str, line_2: str) -> list[int]:
    """The full-screen message: two lines of text (10 and 18 characters)."""
    s, d = profile.sysex, profile.sysex.display
    return [
        *s.header,
        *d.prefix,
        *d.full_screen_options,
        LINE_1_BYTE,
        *ascii_line(line_1, d.line_1_width),
        END_OF_LINE,
        LINE_2_BYTE,
        *ascii_line(line_2, d.line_2_width),
        END_OF_LINE,
        s.end,
    ]


def _seven_bit(value: int) -> int:
    return max(0, min(127, int(value)))


def led(profile: Profile, pad: Control, rgb: Rgb) -> list[int]:
    """A pad's LED colour (each of red, green and blue 0..127)."""
    if pad.led_sysex_id is None:
        raise ValueError(f"the control {pad.name!r} has no LED in the profile")
    s = profile.sysex
    return [*s.header, *s.led_prefix, pad.led_sysex_id, *(_seven_bit(c) for c in rgb), s.end]


def realign(profile: Profile, knob: Control, value: int) -> list[int]:
    """Move a knob's ring to `value` (0..127), so the knob and the parameter agree when a page is armed. Live's
    script sends the knob's id, a zero, then the value (its encoder.py: `_get_sysex_header` ends in the id and 0)."""
    if knob.realign_sysex_id is None:
        raise ValueError(f"the control {knob.name!r} has no ring in the profile")
    s = profile.sysex
    return [*s.header, *s.realign_prefix, knob.realign_sysex_id, 0, _seven_bit(value), s.end]
