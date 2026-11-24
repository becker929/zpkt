"""meter.py's OSC parse and the page's meter message, and monitor.py's tracks, offline."""

from __future__ import annotations

import struct

import meter
import monitor
import pytest
import server


def osc(address: bytes, values: list[float], tag: str = "f") -> bytes:
    def pad(b: bytes) -> bytes:
        return b + b"\x00" * (4 - len(b) % 4)

    body = b"".join(struct.pack(">f" if tag == "f" else ">i", v) for v in values)
    return pad(address) + pad(b"," + tag.encode() * len(values)) + body


def test_the_meter_sends_31_bands_and_the_page_gets_them_in_db():
    data = osc(b"/spec", [0.5] * meter.BANDS)
    levels = meter.parse(data)
    assert levels == pytest.approx([0.5] * 31)
    hz = [round(f, 2) for f in meter.centers()]
    assert hz[0] == 20.0 and len(hz) == 31
    msg = server.meter_message([*levels], hz)
    assert msg["t"] == "meter" and msg["db"][0] == pytest.approx(-6.02, abs=0.01)
    assert server.meter_message([0.0] * 31, hz)["db"][0] == -140.0
    assert server.meter_message([0.5] * 30, hz) is None


def test_the_meter_ignores_anything_but_spec():
    assert meter.parse(osc(b"/other", [1.0])) is None
    assert meter.parse(osc(b"/spec", [1, 2], tag="i")) == [1.0, 2.0]


def test_monitor_tracks_are_the_two_renders_at_the_top_and_the_references_at_the_drop():
    want = monitor.wanted()
    assert list(want)[:2] == ["mon A", "mon B"] and want["mon A"][1] == 0.0
    assert {n for n in want if n.startswith("mon C")} == {"mon C1", "mon C2", "mon C3", "mon C4"}
    assert want["mon C1"][1] == monitor.ALIGN_BEAT == 64.0
