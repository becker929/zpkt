"""contrib/mixdesk/pager.py loaded into FakeLive the way contrib/mixdesk/server.py's start_pager loads it into Live.

The pager runs inside Live: listeners on the set, a MiniLab it grabs, UDP datagrams to the desk's server. Here the
datagrams go to a socket the test owns (never the running desk's 8986), and the MiniLab is zpkt.live.testing's fake.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

import pytest

from zpkt.live.testing import FakeLive, MiniLab_3, hw002_like
from zpkt.live.testing.display import fader_db

MIXDESK = Path(__file__).resolve().parents[2] / "contrib" / "mixdesk"
MOD = "zpkt_mixdesk_pager"
pytestmark = pytest.mark.skipif(not (MIXDESK / "pager.py").exists(), reason="contrib/mixdesk is not in this checkout")


def start_code(cfg: dict, udp_port: int) -> str:
    """The code server.start_pager sends (contrib/mixdesk/server.py), with the test's config and UDP port."""
    return (
        "import importlib.util, sys, json\n"
        f"spec = importlib.util.spec_from_file_location({MOD!r}, {str(MIXDESK / 'pager.py')!r})\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        f"old = sys.modules.get({MOD!r})\n"
        "if old is not None and getattr(old, 'DESK', None) is not None:\n"
        "    d = old.DESK\n"
        "    m.CARRY = {'main_saved': getattr(d, 'main_saved', None), 'slot': getattr(d, 'monitor_slot', 'W'), "
        "'ref': getattr(d, 'monitor_ref', 'C1'), 'page': d.page, 'v': getattr(old, 'SLOTS_V', 1)}\n"
        "    d.stop()\n"
        f"sys.modules[{MOD!r}] = m\n"
        f"result = m.start(song, json.loads({json.dumps(cfg)!r}), {udp_port})\n"
    )


def call(live: FakeLive, expr: str):
    """What server.call sends: an expression on the running desk."""
    return live.run(
        f"import sys\nm = sys.modules.get({MOD!r})\nresult = {expr} if m is not None and m.DESK is not None else None"
    )


class Desk:
    """A started pager: the fake Live, its MiniLab, and the datagrams it sent."""

    def __init__(self, live: FakeLive, minilab: MiniLab_3 | None, udp: socket.socket, snapshot: dict) -> None:
        self.live, self.minilab, self.udp, self.snapshot = live, minilab, udp, snapshot

    def sent(self) -> list[dict]:
        out = []
        try:
            while True:
                out.append(json.loads(self.udp.recv(65536)))
        except (TimeoutError, BlockingIOError):
            return out


@pytest.fixture
def cfg() -> dict:
    return json.loads((MIXDESK / "desk.json").read_text())


@pytest.fixture
def desk(request, cfg):
    minilab = MiniLab_3() if getattr(request, "param", True) else None
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("127.0.0.1", 0))
    udp.settimeout(0.2)
    live = FakeLive(hw002_like(), surfaces=[minilab] if minilab else [])
    try:
        yield Desk(live, minilab, udp, live.run(start_code(cfg, udp.getsockname()[1])))
        call(live, "m.DESK.stop()")
    finally:
        live.close()
        udp.close()


def track(live: FakeLive, name: str):
    return next(t for t in [*live.song.tracks, *live.song.return_tracks, live.song.master_track] if t.name == name)


@pytest.mark.parametrize("desk", [False], indirect=True)
def test_without_a_minilab_every_desk_control_still_finds_its_target(desk, cfg):
    snap = desk.snapshot
    assert snap["attached"] is False and snap["page"] == 0 and snap["loop"] == "off" and snap["playing"] is False
    assert {k: v["err"] for k, v in snap["values"].items() if v["err"]} == {}
    controls = sum(len(p["controls"]) for p in cfg["pages"])
    assert len(snap["values"]) >= controls
    assert snap["values"]["0:k8"]["s"] == "-6.00 dB" and snap["values"]["0:k8"]["key"] == "Main/desk headroom/Output"
    assert desk.live.listener_errors == []


def test_inventory_lists_every_control_one_line_each(desk):
    lines = call(desk.live, "m.DESK.inventory()").splitlines()
    rows = [line.split("\t") for line in lines]
    assert all(len(r) == 7 for r in rows)
    assert "\t".join(["Kick bus", "", "volume", "0.0 dB", "-inf dB", "6.0 dB", ""]) in lines
    assert "\t".join(["Kick bus", "", "send:Space", "-inf dB", "-inf dB", "0.0 dB", ""]) in lines
    assert "\t".join(["Kick bus", "", "mute", "off", "off", "on", "Q"]) in lines
    assert "\t".join(["Main", "desk headroom", "Output", "-6.00 dB", "-inf dB", "35.0 dB", ""]) in lines
    assert "\t".join(["Space", "Reverb", "Device On", "On", "Off", "On", "Q"]) in lines
    assert not any(r[0].startswith("mon ") for r in rows)
    assert not any(r[0] == "Main" and r[2] in ("mute", "solo") for r in rows)


def test_the_minilab_drives_the_set_and_every_move_goes_out(desk):
    assert desk.snapshot["attached"] is True and desk.minilab.rebuilds >= 1
    desk.sent()
    desk.minilab.elements.encoders_raw[0].receive(64)  # page 0, k1: Perc bus volume
    assert track(desk.live, "Perc bus").mixer_device.volume.value == pytest.approx(64 / 127)
    sent = desk.sent()
    assert {"t": "hw", "page": 0, "slot": "k1", "hw": pytest.approx(64 / 127), "picked": True} in sent
    moved = [m for m in sent if m["t"] == "v" and m["page"] == 0 and m["slot"] == "k1"]
    assert moved and moved[0]["key"] == "Perc bus/volume" and moved[0]["s"] == "-13.8 dB"
    desk.minilab.elements.pad_bank_a_raw[1].receive(127)  # pad A2 arms its page
    assert call(desk.live, "m.DESK.page") == next(m["page"] for m in desk.sent() if m["t"] == "page")


def test_a_change_from_anywhere_is_sent_and_set_raw_puts_values_back(desk):
    desk.sent()
    desk.live.run("find_track('Hats bus').mixer_device.volume.value = 0.5")
    assert any(m["t"] == "v" and m["key"] == "Hats bus/volume" and m["s"] == "-14.0 dB" for m in desk.sent())
    missing = call(desk.live, "m.DESK.set_raw([['Kick bus/volume', 0.7], ['Kick bus/mute', True], ['Nope/volume', 1]])")
    assert missing == ["Nope/volume"]
    assert track(desk.live, "Kick bus").mixer_device.volume.value == 0.7 and track(desk.live, "Kick bus").mute


def test_monitor_solos_a_monitor_track_and_bypasses_mains_desk_devices(desk):
    call(desk.live, "m.DESK.monitor('A', 'C1', -3.0)")
    mon_a, main = track(desk.live, "mon A"), desk.live.song.master_track
    assert mon_a.solo and not mon_a.mute and fader_db(mon_a.mixer_device.volume.value) == pytest.approx(-3.0, abs=0.06)
    assert all(track(desk.live, n).mute for n in ("mon B", "mon C1"))
    assert [d.parameters[0].value for d in main.devices] == [0.0, 0.0, 0.0]
    call(desk.live, "m.DESK.monitor('W', 'C1', 0.0)")
    assert not mon_a.solo and mon_a.mute and [d.parameters[0].value for d in main.devices] == [1.0, 1.0, 1.0]


def test_playing_past_the_end_stops_on_the_next_tick(desk):
    call(desk.live, "m.DESK.transport('seek', 150.0)")
    call(desk.live, "m.DESK.transport('play')")
    assert desk.live.song.is_playing
    time.sleep(0.08)  # the pager sends the position at most every 70 ms
    desk.live.play_for(12.0)  # the listener's stop_playing is refused inside a notification, as in Live
    assert desk.live.song.is_playing
    desk.live.tick()  # so the pager deferred it to the next tick
    assert not desk.live.song.is_playing
    assert any(m["t"] == "pos" and m["b"] >= 160.0 for m in desk.sent())


def test_a_restart_carries_the_page_and_close_takes_the_module_away(desk, cfg):
    desk.minilab.elements.pad_bank_a_raw[2].receive(127)
    page = call(desk.live, "m.DESK.page")
    again = desk.live.run(start_code(cfg, desk.udp.getsockname()[1]))
    assert again["page"] == page and again["attached"] is True
    assert MOD in sys.modules
    call(desk.live, "m.DESK.stop()")
    desk.live.close()
    assert MOD not in sys.modules
