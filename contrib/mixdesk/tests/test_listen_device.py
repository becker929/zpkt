"""The generated "zpkt listen" device, read as a patch: the objects it must hold and how they are wired. No Live."""

from __future__ import annotations

import json
import struct

import pytest

import listen
import meter
from zpkt.live.listen import CONTROL_PORT, INTERVAL_MS, LISTEN_PORT, WATCHDOG_MS

pytestmark = pytest.mark.skipif(not meter.TEMPLATE.exists(), reason="Live's Max Audio Effect template is not here")


def graph(patch: dict) -> tuple[dict[str, str], set[tuple[str, int, str, int]]]:
    """The patch as {object text: id} and its wires as (from text, outlet, to text, inlet)."""
    boxes = {b["box"]["id"]: b["box"].get("text", "") for b in patch["patcher"]["boxes"]}
    wires = {
        (
            boxes[w["patchline"]["source"][0]],
            w["patchline"]["source"][1],
            boxes[w["patchline"]["destination"][0]],
            w["patchline"]["destination"][1],
        )
        for w in patch["patcher"]["lines"]
    }
    return {text: oid for oid, text in boxes.items()}, wires


CATCH = "jit.catch~ 2 @mode 0"
SEND = f"jit.net.send @ip 127.0.0.1 @port {LISTEN_PORT}"
CLOCK = f"qmetro {INTERVAL_MS}"


def test_the_patch_holds_the_expected_objects():
    texts, _ = graph(listen.build())
    for text in (
        "plugin~",
        "plugout~",
        CATCH,
        SEND,
        CLOCK,
        f"udpreceive {CONTROL_PORT}",
        "route /listen",
        f"delay {WATCHDOG_MS}",
        "dspstate~",
        "prepend sr",
    ):
        assert text in texts, text
    assert not [t for t in texts if t.startswith(("udpsend", "click~", "metro"))]  # the debug taps are not in it


def test_the_audio_goes_through_untouched_and_out_to_the_sender():
    _, wires = graph(listen.build())
    assert {("plugin~", 0, "plugout~", 0), ("plugin~", 1, "plugout~", 1)} <= wires
    assert [w for w in wires if w[2] == "plugout~"] and all(w[0] == "plugin~" for w in wires if w[2] == "plugout~")
    assert {("plugin~", 0, CATCH, 0), ("plugin~", 1, CATCH, 1), (CATCH, 0, SEND, 0)} <= wires
    assert all(w[2] in ("plugout~", CATCH) for w in wires if w[0] == "plugin~")  # nothing else hears the signal


def test_the_switch_the_watchdog_and_the_rate_are_wired():
    _, wires = graph(listen.build())
    path = [
        (f"udpreceive {CONTROL_PORT}", 0, "route /listen", 0),
        ("route /listen", 0, "sel 1 0", 0),
        ("sel 1 0", 0, "t b b b 1", 0),  # "/listen 1"
        ("sel 1 0", 1, "t 0 stop", 0),  # "/listen 0"
        ("t b b b 1", 3, "change", 0),  # on
        ("t b b b 1", 2, f"delay {WATCHDOG_MS}", 0),  # re-arm the watchdog
        ("t 0 stop", 1, f"delay {WATCHDOG_MS}", 0),  # off cancels it
        (f"delay {WATCHDOG_MS}", 0, "t 0 stop", 0),  # nothing heard: off
        ("t 0 stop", 0, "change", 0),
        ("change", 0, CLOCK, 0),
        (CLOCK, 0, CATCH, 0),  # only the clock empties jit.catch~: no clock, nothing sent
        ("t b b b 1", 1, "t getconnected", 0),
        ("t getconnected", 0, SEND, 0),
        (SEND, 0, "route connected", 0),
        ("route connected", 0, "sel 0", 0),
        ("sel 0", 0, f"t {LISTEN_PORT}", 0),
        (f"t {LISTEN_PORT}", 0, "prepend port", 0),
        ("prepend port", 0, SEND, 0),  # not connected: told its port again, which makes it connect
        ("t b b b 1", 0, "dspstate~", 0),
        ("dspstate~", 1, "prepend sr", 0),
        ("prepend sr", 0, SEND, 1),
    ]
    for wire in path:
        assert wire in wires, wire
    assert [w[0] for w in wires if w[2] == CLOCK] == ["change"]  # the clock has one master, and it starts stopped


def test_every_wire_joins_two_boxes_on_inlets_and_outlets_they_have():
    patch = listen.build(debug=True, port=9001, control=9002)
    boxes = {b["box"]["id"]: b["box"] for b in patch["patcher"]["boxes"]}
    assert len(boxes) == len(patch["patcher"]["boxes"])  # ids are unique
    for w in patch["patcher"]["lines"]:
        (a, out), (b, inlet) = w["patchline"]["source"], w["patchline"]["destination"]
        assert out < boxes[a]["numoutlets"] and inlet < boxes[b]["numinlets"], (boxes[a]["text"], boxes[b]["text"])
    texts, wires = graph(patch)
    assert "jit.net.send @ip 127.0.0.1 @port 9001" in texts and "udpreceive 9002" in texts and "click~" in texts
    assert not [w for w in wires if w[2] == "plugout~" and w[0] != "plugin~"]  # the test click never reaches Live


def test_make_writes_an_amxd_live_can_read(tmp_path, monkeypatch):
    monkeypatch.setattr(listen, "USER_LIB", tmp_path)
    monkeypatch.setattr(listen.sys, "argv", ["listen.py", "make"])
    out = listen.make()
    data = out.read_bytes()
    assert out.name == "zpkt listen.amxd" and data[:4] == b"ampf" and data[8:12] == b"aaaa"  # an audio effect
    at = data.index(b"ptch")
    size = struct.unpack("<I", data[at + 4 : at + 8])[0]
    body = data[at + 8 : at + 8 + size]
    assert len(body) == size and json.loads(body.rstrip(b"\x00")) == listen.build()
