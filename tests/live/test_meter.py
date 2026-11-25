"""zpkt.live.meter: the OSC the Max for Live meter sends, parsed, and read from a handed-in socket."""

from __future__ import annotations

import struct

from zpkt.audio.levels import SILENCE_DB, rms_to_db
from zpkt.live import meter


def osc(levels: list[float], tag: str = "f") -> bytes:
    tags = ("," + tag * len(levels)).encode() + b"\x00"
    tags += b"\x00" * (-len(tags) % 4)
    fmt = ">f" if tag == "f" else ">i"
    return b"/spec\x00\x00\x00" + tags + b"".join(struct.pack(fmt, v) for v in levels)


def test_a_spec_message_is_its_floats():
    got = meter.parse(osc([0.5, 0.25, 0.0]))
    assert got == [0.5, 0.25, 0.0]
    assert len(meter.parse(osc([0.1] * 31)) or []) == meter.BANDS


def test_integers_are_read_as_floats():
    assert meter.parse(osc([3, 4], "i")) == [3.0, 4.0]


def test_anything_else_is_none_never_an_exception():
    for bad in (
        b"",
        b"/other\x00\x00,f\x00\x00",
        b"/spec\x00",
        b"/spec\x00\x00\x00,ff\x00" + b"\x00" * 3,
        b"/spec\x00\x00\x00,s\x00\x00ab\x00\x00",
    ):
        assert meter.parse(bad) is None


def test_the_band_centres_run_from_20_hz_to_20_khz():
    hz = meter.centers()
    assert len(hz) == 31 and hz[0] == 20.0 and round(hz[-1]) == 20480


def test_read_levels_takes_a_socket_and_opens_nothing():
    class Sock:
        def recvfrom(self, size, /):
            return osc([0.5]), ("127.0.0.1", 1)

    assert meter.read_levels(Sock()) == [0.5]


def test_levels_become_db_with_a_floor():
    assert rms_to_db([1.0, 0.1, 0.5]) == [0.0, -20.0, -6.02]
    assert rms_to_db([0.0, 1e-8, 1e-7]) == [SILENCE_DB] * 3
