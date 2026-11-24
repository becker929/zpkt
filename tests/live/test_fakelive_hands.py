"""hands' own LOM code run against FakeLive: the mix state, knobs, the mix panel's reads, and the CLI in a subprocess.

These run the code strings hands sends to Live, unchanged, so they pin what reaches Live: the calls, their sizes,
and that no call reads back what it wrote (ableton-guide rule 1).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

from hands.live import knobs, mix
from hands.live import panel as P
from hands.live import state as S
from hands.testing import FakeLive, fake_set, hw002_like

LIVE_PORT = 16619
GUARD = """import socket
_real = socket.create_connection
def _guarded(address, *args, **kwargs):
    if address[1] == 16619:
        raise OSError("test guard: the real Live's port 16619 is off limits")
    return _real(address, *args, **kwargs)
socket.create_connection = _guarded
"""


@pytest.fixture(autouse=True)
def never_the_real_live(monkeypatch):
    real = socket.create_connection

    def guarded(address, *args, **kwargs):
        if address[1] == LIVE_PORT:
            raise AssertionError("a test tried to reach the real Live on 16619")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)


@pytest.fixture
def live():
    with FakeLive(hw002_like()) as fake:
        yield fake


def param(live: FakeLive, track: str, device: str, name: str):
    t = next(x for x in [*live.song.tracks, *live.song.return_tracks, live.song.master_track] if x.name == track)
    return next(p for p in next(d for d in t.devices if d.name == device).parameters if p.name == name)


def no_readbacks(live: FakeLive) -> None:
    assert [(c.number, c.readbacks) for c in live.calls if c.readbacks] == []


# --------------------------------------------------------------------------- hands.live.state


def test_state_take_reads_every_track_in_chunks_of_eight(live):
    st = S.take(live)
    names = [t.name for t in live.song.tracks] + [r.name for r in live.song.return_tracks] + ["Main"]
    assert list(st["tracks"]) == names and st["returns"] == ["A-Space", "B-Echo"]
    assert len(live.calls) == 2 + -(-len(names) // S.READ_CHUNK)
    kick_bus = st["tracks"]["Kick bus"]
    assert kick_bus["mixer"]["volume"] == ["0.0 dB", 0.85]
    assert kick_bus["mixer"]["sends"] == {"A-Space": ["-inf dB", 0.0], "B-Echo": ["-inf dB", 0.0]}
    assert [d["name"] for d in kick_bus["devices"]] == ["desk EQ", "desk Sat", "desk Glue"]
    assert kick_bus["devices"][1]["params"]["Dry/Wet"] == ["0.0 %", 0.0]
    assert st["tracks"]["Main"]["devices"][2]["params"]["Output"] == ["-6.00 dB", pytest.approx(-6 / 35)]
    assert "mute" not in st["tracks"]["Main"]["mixer"]
    no_readbacks(live)


def test_state_put_restores_a_state_and_diff_sees_the_change(live):
    before = S.take(live)
    live.run(
        "t = find_track('Kick bus')\nt.mixer_device.volume.value = 0.5\nt.mute = True\n"
        "next(p for p in t.devices[0].parameters if p.name == '1 Gain A').value = -4.5\n"
        "song.return_tracks[0].mixer_device.volume.value = 0.7"
    )
    now = S.take(live)
    rows = S.diff(before, now)
    assert ("Kick bus/volume", "0.0 dB", "-14.0 dB") in rows and ("Kick bus/mute", "False", "True") in rows
    assert ("Kick bus/desk EQ/1 Gain A", "0.00 dB", "-4.50 dB") in rows and (
        "Space/volume",
        "0.0 dB",
        "-6.0 dB",
    ) in rows
    assert len(rows) == 4
    live.calls.clear()
    assert S.put(live, before) == []
    assert S.diff(before, S.take(live)) == []
    writes = [c.code for c in live.calls if c.code.startswith(("d = ", "t = "))]
    assert len(writes) == 3  # one device call (desk EQ) and two mixer calls (Kick bus, A-Space)
    no_readbacks(live)


def test_state_put_reports_what_the_set_lacks_and_takes_a_desk_recipe(live):
    state = S.from_desk(
        {
            "mixer": {"Kick bus": {"volume": ["-6.0 dB", 0.7], "pan": ["C", 0.0]}},
            "chains": {"Gone bus": [{"name": "desk EQ", "values": {"1 Gain A": ["1.00 dB", 1.0]}}]},
            "returns": [{"name": "Space", "devices": [{"name": "Reverb", "values": {"Decay Time": ["4.00 s", 0.5]}}]}],
        }
    )
    rows = S.put(live, state)
    assert ("Gone bus/*", "track", None) in rows and len(rows) == 1
    assert live.run("find_track('Kick bus').mixer_device.volume.value") == 0.7
    assert param(live, "A-Space", "Reverb", "Decay Time").value == 0.5


# --------------------------------------------------------------------------- hands.live.knobs


def test_knobs_set_many_writes_in_one_call_and_apply_reads_back_in_another(live):
    gain = knobs.Knob("Kick bus", ("Eq8", 0), "Bands.1/ParameterA/Gain")
    fader = knobs.Knob("kick", "Mixer", "Volume")
    speaker = knobs.Knob("kick", "Mixer", "Speaker")
    width = knobs.Knob("Main", ("StereoGain", 0), "StereoWidth")
    readings = knobs.apply(live, {gain: -3.0, fader: 0.5, speaker: False, width: 0.81})
    assert len(live.calls) == 2 and "SPEC = " in live.calls[0].code and "SPEC = " in live.calls[1].code
    assert readings[gain].display == "-3.00 dB" and readings[gain].lom == -3.0
    assert readings[fader].display == "-6.0 dB" and readings[fader].value == pytest.approx(0.5, rel=0.01)
    assert readings[speaker].lom is False and live.run("find_track('kick').mute")
    assert readings[width].display == "81 %"
    no_readbacks(live)


def test_knobs_refuse_an_automated_parameter_and_write_nothing(live):
    automated, other = param(live, "Kick bus", "desk EQ", "2 Gain A"), param(live, "Kick bus", "desk EQ", "1 Gain A")
    automated._values["automation_state"] = 1  # it plays its arrangement automation
    gain = knobs.Knob("Kick bus", ("Eq8", 0), "Bands.1/ParameterA/Gain")
    first = knobs.Knob("Kick bus", ("Eq8", 0), "Bands.0/ParameterA/Gain")
    with pytest.raises(knobs.KnobError, match="automated"):
        knobs.set_many(live, {first: 2.0, gain: -3.0})
    assert automated.value == 0.0 and other.value == 0.0
    with pytest.raises(knobs.KnobError, match="no Eq8 #3"):
        knobs.set_many(live, {knobs.Knob("Kick bus", ("Eq8", 3), "Bands.1/ParameterA/Gain"): 1.0})


# --------------------------------------------------------------------------- the mix panel's reads


def test_read_params_gives_range_value_and_what_live_shows(live):
    sat = mix._dev("Kick bus", "desk Sat")
    rows = mix.read_params(
        live, [mix._par(sat, "Drive"), mix._par(sat, "Type"), f"{mix.tr('kick')}.mixer_device.volume"]
    )
    drive, kind, volume = rows
    assert (drive["min"], drive["max"], drive["quantized"]) == (-36.0, 36.0, False)
    assert drive["table"][0] == "-36.0 dB" and drive["table"][16] == "0.00 dB" and len(drive["table"]) == P.SAMPLES
    assert kind["quantized"] and kind["items"][:2] == ["Analog Clip", "Soft Sine"]
    assert volume["table"][0] == "-inf dB" and volume["table"][-1] == "6.0 dB" and volume["value"] == 0.85
    assert len(live.calls) == 1


def test_panel_reads_the_state_a_catalog_and_resolves_shown_values(live):
    state = P._state(live)
    assert state["names"][0] == "kick" and state["tempo"] == 160.0 and not state["playing"] and state["end"] == 160.0
    where = P.Loc(mix._dev("Kick bus", "desk EQ"))
    catalog = P.read_catalog(live, where)
    assert len(catalog) == 84 and len(live.calls) == 1 + 1 + 3  # the count, then 40 parameters a call
    by = {p["name"]: p for p in catalog}
    assert by["1 Filter Type A"]["items"][3] == "Bell" and by["1 Frequency A"]["shown"] == "30.0 Hz"
    values, warnings = P.resolve(
        live,
        where,
        catalog,
        {"1 Frequency A": "200 Hz", "1 Gain A": "-3 dB", "1 Filter Type A": "Low Shelf", "Device On": True},
    )
    shown = {n: param(live, "Kick bus", "desk EQ", n).str_for_value(v) for n, v in values.items()}
    assert shown == {
        "Device On": "On",
        "1 Filter Type A": "Low Shelf",
        "1 Frequency A": "200 Hz",
        "1 Gain A": "-3.00 dB",
    }
    assert warnings == []
    no_readbacks(live)


def test_panel_params_loads_a_device_on_a_temporary_track_and_takes_it_away(live):
    tracks = [t.name for t in live.song.tracks]
    text = P.params(live, "Glue Compressor", grep="Ratio|Release")
    assert text.splitlines()[0].startswith("Glue Compressor: 2 of 17 parameters")
    assert "Ratio | 0..2 | 0 = 2 | 2, 4, 10" in text
    assert [t.name for t in live.song.tracks] == tracks
    assert live.browser.loaded == [("Glue Compressor", "panel params (temporary)")]


def test_open_buses_and_quiet_tracks():
    song = fake_set(
        {
            "tracks": [
                {"name": "a", "output": "bus", "clips": [{"start": 64.0, "length": 16.0}]},
                {"name": "bus", "monitoring": 2},
                {"name": "b"},
            ]
        }
    )
    with FakeLive(song) as live:
        assert mix.open_buses(live) == ["bus"] and live.song.tracks[1].current_monitoring_state == 0
        assert mix.open_buses(live) == []
        notes = mix.quiet_tracks(live, ["bus", "b", "Main"], 0.0, 32.0)
        assert notes == [
            "bus plays nothing in these bars; it first plays at bar 17: its controls change nothing here",
            "b plays nothing in these bars: its controls change nothing here",
        ]


# --------------------------------------------------------------------------- the CLI, in another process


def _hands(args, env, cwd):
    return subprocess.run(
        [sys.executable, "-c", "from hands.cli import main; main()", *args],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_hands_live_state_in_a_subprocess_against_the_served_fake(live, tmp_path, rig):
    bin_dir, guard = tmp_path / "bin", tmp_path / "guard"
    bin_dir.mkdir()
    guard.mkdir()
    (bin_dir / "osascript").write_text("#!/bin/sh\necho test_fake_set\n")  # Live's window title, without Live
    (bin_dir / "osascript").chmod(0o755)
    (guard / "sitecustomize.py").write_text(GUARD)
    port = live.serve()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": str(guard),
        "ZPKT_LIVE_PORT": str(port),
    }

    took = _hands(["live", "state", "take", "before"], env, tmp_path)
    assert took.returncode == 0, took.stderr
    saved = rig.sets_dir / "state" / "test_fake_set" / "before.json"
    assert saved.exists() and f"{len(live.song.tracks) + 3} tracks" in took.stdout

    with live.main_thread():
        next(t for t in live.song.tracks if t.name == "Hats bus").mixer_device.volume.value = 0.5
    differ = _hands(["live", "state", "diff", "before"], env, tmp_path)
    assert differ.returncode == 1 and "Hats bus/volume: 0.0 dB -> -14.0 dB" in differ.stdout

    env["ZPKT_LIVE_PORT"] = "9"  # --port still wins over the rig's setting
    put = _hands(["live", "state", "put", "before", "--port", str(port)], env, tmp_path)
    assert put.returncode == 0 and "put, Live matches" in put.stdout, put.stderr
    same = _hands(["live", "state", "diff", "before", "--port", str(port)], env, tmp_path)
    assert same.returncode == 0 and "0 differ" in same.stdout
    unreachable = _hands(["live", "state", "diff", "before"], env, tmp_path)
    assert unreachable.returncode == 1 and "Cannot reach Ableton" in unreachable.stderr
