"""The whole pager loaded into FakeLive by the server (server.pager_start_code), played on the fake MiniLab, with
what it reports arriving in the server's state (conftest.py's rig)."""

from __future__ import annotations

import pytest
from conftest import wait_for


def test_a_fader_picks_up_only_once_it_passes_the_value(rig):
    kick = rig.track("Kick bus").mixer_device.volume  # page 0, f1, at 0.85
    fader = rig.minilab.elements.volume_fader
    fader.receive(20)  # far below: no pickup
    assert kick.value == pytest.approx(0.85)
    assert wait_for(lambda: rig.state()["picked"].get("f1") is False)
    fader.receive(127)  # passed the value: picked up, and it moves
    assert kick.value == pytest.approx(1.0)
    assert wait_for(lambda: (st := rig.state())["picked"].get("f1") is True and st["values"]["0:f1"]["r"] == 1.0)


def test_pad_a2_arms_its_page_then_its_layer(rig):
    desk = rig.get("/api/desk")[1]
    on_a2 = [i for i, p in enumerate(desk["pages"]) if p.get("pad") == 2 or ("pad" not in p and i == 1)]
    pad = rig.minilab.elements.pad_bank_a_raw[1]
    pad.receive(127)
    assert wait_for(lambda: rig.state()["page"] == on_a2[0])
    if len(on_a2) > 1:
        pad.receive(127)
        assert wait_for(lambda: rig.state()["page"] == on_a2[1])


def test_a_macro_on_a_saved_surface_moves_its_parameters_between_their_ends(rig):
    surface = {"name": "Macro test", "what": "x", "controls": {"k1": {"label": "Dark", "macro": [
        {"track": "Hats bus", "device": "desk EQ", "param": "7 Gain A", "from": "0 dB", "to": "-9 dB"}]}}}
    code, out = rig.post("/api/surface/save", {"surface": surface})
    assert code == 200, out
    rig.minilab.elements.encoders_raw[0].receive(127)
    gain = next(p for p in rig.track("Hats bus").devices[0].parameters if p.name == "7 Gain A")
    assert str(gain).startswith("-9.0")
    rig.minilab.elements.encoders_raw[0].receive(0)
    assert str(gain).startswith("0.0")
    key = "Hats bus/desk EQ/7 Gain A"
    assert wait_for(lambda: any(v.get("key") == key for v in rig.state()["values"].values()))
