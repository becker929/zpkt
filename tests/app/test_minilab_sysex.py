"""The MiniLab's SysEx out: display, LED and knob ring, as bytes. Unverified at the hardware; these pin the layout."""

from __future__ import annotations

import pytest

from zpkt.app.minilab import sysex
from zpkt.app.minilab.profile import load_profile

HEADER = [0xF0, 0x00, 0x20, 0x6B, 0x7F, 0x42]


@pytest.fixture(scope="module")
def profile():
    return load_profile()


def test_the_display_message_has_the_layout_of_lives_full_screen_message(profile):
    msg = sysex.display(profile, "Buses", "page 1 of 12")
    assert msg[:6] == HEADER and msg[6:9] == [4, 2, 96]
    assert msg[9:16] == [31, 7, 1, 0, 0, 0, 0]  # options: full screen, not transient, no pictograms
    assert msg[16] == 1 and bytes(msg[17:22]) == b"Buses" and msg[22:24] == [0, 2]
    assert bytes(msg[24:36]) == b"page 1 of 12" and msg[36:] == [0, 0xF7]


def test_the_lines_are_cut_to_the_width_and_kept_to_7_bit_ascii(profile):
    msg = sysex.display(profile, "A very long page name", "naïve → text " * 3)
    line_1 = bytes(msg[msg.index(1, 16) + 1 : msg.index(0, 17)])
    assert line_1 == b"A very lon"
    assert all(b < 128 for b in msg[1:-1])
    assert sysex.ascii_line("naïve", 18) == list(b"na?ve")
    assert sysex.ascii_line("  hi  ", 18) == list(b"hi")


def test_a_pad_led_is_its_id_and_a_seven_bit_colour(profile):
    msg = sysex.led(profile, profile.by_name("a1"), (127, 0, 40))
    assert msg == [*HEADER, 2, 2, 22, 52, 127, 0, 40, 0xF7]
    clipped = sysex.led(profile, profile.by_name("b8"), (200, -5, 3))
    assert clipped == [*HEADER, 2, 2, 22, 75, 127, 0, 3, 0xF7]


def test_a_knob_ring_is_the_header_the_knobs_id_and_the_value(profile):
    assert sysex.realign(profile, profile.by_name("k1"), 64) == [*HEADER, 33, 16, 0, 7, 64, 0xF7]
    assert sysex.realign(profile, profile.by_name("k8"), 300)[-2] == 127


def test_a_control_with_no_led_or_ring_is_an_error_that_says_so(profile):
    with pytest.raises(ValueError, match="no LED"):
        sysex.led(profile, profile.by_name("k1"), (1, 1, 1))
    with pytest.raises(ValueError, match="no ring"):
        sysex.realign(profile, profile.by_name("a1"), 1)
