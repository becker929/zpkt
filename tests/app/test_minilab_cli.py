"""`zpkt app midi ...`: profile, learn and latency, run on fakes (never on a MiniLab or the real Live), and the way
`zpkt app` starts the adapter."""

from __future__ import annotations

import json
import sys
import threading
import time

import pytest

import zpkt.app as app
from tests.app.test_midi_adapter import KNOB_CC, key_of
from zpkt.app.adapters import AdapterError, AppContext
from zpkt.app.minilab import cli, latency
from zpkt.app.minilab.latency import LatencyProbe, Sample
from zpkt.app.minilab.ports import FakePort, PortUnavailable
from zpkt.app.minilab.profile import Event


def test_the_profile_command_lists_every_control_and_says_nothing_is_verified(capsys):
    assert cli.main(["profile"]) == 0
    out = capsys.readouterr().out
    assert "none verified at the hardware" in out and "k1" in out and "live-script" in out
    assert "not known yet (ignored until learned): octave_down, octave_up" in out
    assert "pitchbend ch 1" in out and "note ch 1 48-72" in out


def test_learn_waits_for_one_message_and_gives_up_when_none_comes():
    port = FakePort()
    threading.Timer(0.05, lambda: port.receive("cc", 99, 127)).start()
    assert cli.learn_message(port, 2.0) == Event("cc", 1, 99, 127) and port.closed
    quiet = FakePort()
    assert cli.learn_message(quiet, 0.05) is None and quiet.closed


def test_a_learned_message_is_a_profile_entry_and_a_pitch_bend_has_no_number():
    assert cli.message_of(Event("cc", 2, 7, 1)).number == 7
    assert cli.message_of(Event("pitchbend", 1, 0, 9000)).number is None


def test_the_learn_command_prints_the_entry_to_paste_and_says_when_nothing_came(monkeypatch, capsys):
    port = FakePort()
    monkeypatch.setattr(cli, "open_port", lambda profile, name=None: port)
    threading.Timer(0.05, lambda: port.receive("cc", 99, 127, channel=3)).start()
    assert cli.main(["learn", "octave_up", "--seconds", "2"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out.strip().splitlines()[-1]) == {"type": "cc", "channel": 3, "number": 99}
    monkeypatch.setattr(cli, "open_port", lambda profile, name=None: FakePort())
    assert cli.main(["learn", "octave_up", "--seconds", "0.05"]) == 1
    assert "Nothing came in" in capsys.readouterr().out
    assert cli.main(["learn", "nonesuch"]) == 2 and "no control 'nonesuch'" in capsys.readouterr().out


def test_without_the_extra_the_tools_say_what_to_install_and_exit_2(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mido", None)
    assert cli.main(["learn", "k1"]) == 2
    assert "uv sync --extra midi" in capsys.readouterr().out


def test_run_latency_returns_the_timings_of_the_knobs_turned_while_it_runs(rig):
    port = FakePort()
    context = AppContext(rig.desk.bus, rig.desk, rig.desk.settings)
    key_of(rig, "k3")

    def turn_knobs(seconds):  # what the person does during the run
        for v in (20, 60, 100, 30):
            port.receive("cc", KNOB_CC["k3"], v)
            time.sleep(0.15)

    result = cli.run_latency(context, port, 1.0, sleep=turn_knobs)
    assert result["queue"]["count"] >= 2 and result["bus"]["median_ms"] > 0
    assert result["echo"].get("count", 0) >= 1
    assert port.closed


def test_the_probe_counts_a_batch_nobody_echoed_and_the_summary_reads_in_milliseconds():
    probe = LatencyProbe()
    probe.batch(["k1"], 1.0, 1.01, 1.05, 200)
    probe.echo("k1", 1.09)
    probe.batch(["k2"], 2.0, 2.02, 2.10, 200)  # Live never reports it back (the value it already had)
    probe.close()
    result = probe.report()
    assert result["queue"]["count"] == 2 and result["echo"]["count"] == 1
    assert result["bus"]["max_ms"] == pytest.approx(80, abs=0.5) and result["echo"]["median_ms"] == pytest.approx(
        40, abs=0.5
    )
    assert result["total"]["median_ms"] == pytest.approx(90, abs=0.5)
    text = latency.format_summary(result)
    assert "queue: 2 samples" in text and "total: 1 samples" in text
    assert "no samples" in latency.format_summary({"queue": {}, "bus": {}, "echo": {}, "total": {}})


def test_a_newer_batch_for_a_control_closes_the_older_one_unechoed():
    probe = LatencyProbe()
    probe.batch(["k1"], 0.0, 0.1, 0.2, 200)
    probe.batch(["k1"], 1.0, 1.1, 1.2, 200)
    probe.echo("k1", 1.5)
    probe.echo("k1", 1.6)  # nothing waits any more: ignored
    assert [(s.slot, s.echo_s is None) for s in probe.samples] == [("k1", True), ("k1", False)]


def test_percentiles_are_by_nearest_rank_and_an_empty_list_is_an_error():
    values = [float(i) for i in range(1, 101)]
    assert latency.percentile(values, 50) == 50 and latency.percentile(values, 95) == 95
    assert latency.percentile([7.0], 99) == 7.0
    with pytest.raises(ValueError, match="no samples"):
        latency.percentile([], 50)
    assert latency.summary([Sample("k1", 0.001, 0.002, None, 200)])["echo"] == {}


def test_zpkt_app_midi_hands_over_to_the_tools(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(list(argv)) or 0)
    with pytest.raises(SystemExit) as stop:
        app.main(["midi", "profile"])
    assert stop.value.code == 0 and seen == [["profile"]]


def test_the_app_stops_with_a_sentence_when_the_midi_adapter_cannot_open_its_port(monkeypatch, rig):
    from zpkt.app.adapters import midi as midi_adapter
    from zpkt.app.desk import Settings

    def no_port(profile, name=None):
        raise PortUnavailable("no MIDI port matches MiniLab3. Is it plugged in?")

    monkeypatch.setattr(midi_adapter, "open_port", no_port)
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: rig.desk.settings))
    monkeypatch.setattr("zpkt.app.desk.Desk", lambda settings: rig.desk)
    with pytest.raises(SystemExit) as stop:
        app.main(["--adapters", "midi", "--port", "0"])
    assert "zpkt app: midi: no MIDI port matches MiniLab3" in str(stop.value)


def test_a_bad_profile_stops_the_app_with_the_files_sentence(monkeypatch, rig, tmp_path):
    from zpkt.app.desk import Settings

    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    monkeypatch.setenv("ZPKT_MINILAB_PROFILE", str(bad))
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: rig.desk.settings))
    monkeypatch.setattr("zpkt.app.desk.Desk", lambda settings: rig.desk)
    with pytest.raises(SystemExit) as stop:
        app.main(["--adapters", "midi", "--port", "0"])
    assert "zpkt app:" in str(stop.value) and "needs 'sysex'" in str(stop.value)


def test_both_kinds_of_failure_are_adapter_errors():
    assert issubclass(PortUnavailable, AdapterError)
    from zpkt.app.minilab.profile import ProfileError

    assert issubclass(ProfileError, AdapterError) and issubclass(ProfileError, ValueError)
