"""zpkt.live.testing.FakeLive itself: it answers as the Remote Script does, over its own fake set, in process and on TCP."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
import types

import pytest

from zpkt.live.testing import FakeLive, fake_set, hw002_like
from zpkt.live.testing.fakelive import REMOTE_SCRIPT
from zpkt.live.testing.lom import NOTIFICATION_REFUSED, MidiNoteSpecification
from zpkt.live.transport import LOST, LiveClient, LiveError

LIVE_PORT = 16619


@pytest.fixture(autouse=True)
def never_the_real_live(monkeypatch):
    """Whatever a test gets wrong, nothing here may reach the real Live's port."""
    real = socket.create_connection

    def guarded(address, *args, **kwargs):
        if address[1] == LIVE_PORT:
            raise AssertionError("a test tried to reach the real Live on 16619")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)


@pytest.fixture
def live():
    with FakeLive(
        fake_set(
            {
                "tempo": 128.0,
                "returns": [{"name": "Space", "devices": ["Reverb"]}],
                "tracks": [
                    {"name": "kick", "volume": 0.6, "sends": [0.25], "devices": [{"device": "EQ Eight", "name": "EQ"}]},
                    {
                        "name": "keys",
                        "type": "midi",
                        "devices": ["Operator"],
                        "clips": [{"start": 4.0, "length": 8.0, "notes": [[60, 0.0, 1.0, 100]]}],
                    },
                ],
            }
        )
    ) as fake:
        yield fake


def script_serialize():
    """The Remote Script's own serialize, loaded by path (its _Framework import stubbed for the load)."""
    stub = types.ModuleType("_Framework.ControlSurface")
    stub.ControlSurface = object
    spec = importlib.util.spec_from_file_location("test_remote_script_copy", REMOTE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.update({"_Framework": types.ModuleType("_Framework"), "_Framework.ControlSurface": stub})
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("_Framework", None)
        sys.modules.pop("_Framework.ControlSurface", None)
    return module.serialize


# --------------------------------------------------------------------------- eval, exec, results


def test_an_expression_is_evaluated_and_statements_set_result(live):
    assert live.run("song.tempo") == 128.0
    assert live.run("x = 2\nresult = x * 3") == 6
    assert live.run("x = 2") is None
    assert live.run("result = [t.name for t in tracks] + [r.name for r in returns] + [master.name]") == [
        "kick",
        "keys",
        "A-Space",
        "Main",
    ]


def test_the_scope_is_the_scripts_and_is_new_each_call(live):
    names = live.run("result = sorted(k for k in globals() if not k.startswith('__'))")
    assert names == sorted(
        [
            "song",
            "app",
            "tracks",
            "returns",
            "master",
            "browser",
            "Live",
            "MidiNoteSpecification",
            "find_item",
            "find_items",
            "find_track",
            "load_to",
            "log",
            "json",
            "time",
        ]
    )
    live.run("leftover = 1")
    with pytest.raises(LiveError, match="name 'leftover' is not defined"):
        live.run("leftover")
    assert live.run("find_track('KICK').name") == "kick"


def test_results_are_serialized_by_the_scripts_own_rules(live):
    serialize = script_serialize()
    song = live.song
    kick = song.tracks[0]
    samples = {
        "song.tracks[0]": kick,
        "song.tracks[0].devices[0]": kick.devices[0],
        "song.tracks[0].mixer_device.volume": kick.mixer_device.volume,
        "list(song.tracks[0].devices[0].parameters)[:3]": list(kick.devices[0].parameters)[:3],
        "song.tracks[1].arrangement_clips[0].get_notes_extended(0, 128, 0.0, 8.0)": song.tracks[1]
        .arrangement_clips[0]
        .get_notes_extended(0, 128, 0.0, 8.0),
        "{'a': {'b': {'c': {'d': {'e': [1.5, True]}}}}}": {"a": {"b": {"c": {"d": {"e": [1.5, True]}}}}},
        "(1, {2, 3}, b'x', None)": (1, {2, 3}, b"x", None),
        "song.tracks[0].output_routing_type": kick.output_routing_type,
        "{t.name: [str(t.mixer_device.volume), t.mixer_device.volume.value] for t in song.tracks}": {
            t.name: [str(t.mixer_device.volume), t.mixer_device.volume.value] for t in song.tracks
        },
    }
    for code, value in samples.items():
        assert live.run(code) == json.loads(json.dumps(serialize(value), default=str)), code


def test_errors_carry_the_traceback_and_a_warning_for_several_lines(live):
    one = live.execute("1 / 0")
    assert (one.status, one.error, one.warning) == ("error", "division by zero", None)
    assert one.traceback.startswith("Traceback") and 'File "<string>", line 1' in one.traceback
    many = live.execute("song.tempo = 100\nraise ValueError('half done')")
    assert many.error == "half done" and many.warning.startswith("Multi-line code may have partially executed")
    assert live.song.tempo == 100.0
    empty = live.execute("   ")
    assert (empty.status, empty.error) == ("error", "No code provided")
    assert len(live.calls) == 2  # a call with no code never reached Live's main thread


def test_every_call_is_kept(live):
    live.run("song.tempo")
    live.run("song.tempo = 140")
    assert live.codes == ["song.tempo", "song.tempo = 140"]
    assert [c.number for c in live.calls] == [1, 2] and all(c.seconds >= 0 for c in live.calls)
    assert all(c.status == "ok" and c.readbacks == [] for c in live.calls)
    assert any("exec: song.tempo = 140" in line for line in live.log)


def test_a_value_read_back_in_the_call_that_wrote_it_is_noted(live):
    live.run("p = song.tracks[0].mixer_device.volume\np.value = 0.5\nresult = p.value")
    live.run("song.tracks[0].mixer_device.volume.value")
    assert live.calls[0].readbacks == ["Track 'kick'/Track Volume.value"]
    assert live.calls[1].readbacks == []


# --------------------------------------------------------------------------- calls that go wrong


def test_a_call_told_to_fail_raises_before_its_code_runs(live):
    live.fail_on(1, "Invalid value")
    res = live.execute("song.tempo = 90")
    assert (res.status, res.error) == ("error", "Invalid value") and "RuntimeError" in res.traceback
    assert live.song.tempo == 128.0 and live.calls[0].fault == "fail"
    live.fail_on(2, KeyError("gone"))
    assert live.execute("song.tempo").error == "'gone'"
    assert live.run("song.tempo") == 128.0


@pytest.mark.parametrize("runs", [True, False])
def test_a_call_that_times_out_answers_as_the_script_does(live, runs):
    live.time_out_on(1, runs=runs)
    res = live.execute("song.tempo = 90")
    assert (res.status, res.error, res.warning) == (
        "error",
        "Timed out after 12s",
        "Code may still be running on the main thread.",
    )
    assert live.song.tempo == (90.0 if runs else 128.0)


def test_a_lost_reply_is_what_liveclient_reports(live):
    live.lose_reply_on(1)
    res = live.execute("song.tempo = 90")
    assert res.status == "error" and res.error.startswith(LOST) and live.song.tempo == 90.0
    port = live.serve()
    client = LiveClient(port=port, timeout=2.0, retries=0)
    live.lose_reply_on(2, runs=False)
    with pytest.raises(LiveError, match="Lost the reply from Ableton"):
        client.run("song.tempo = 100")
    assert live.song.tempo == 90.0
    assert client.run("song.tempo") == 90.0


# --------------------------------------------------------------------------- over TCP


def test_served_it_speaks_the_scripts_protocol(live):
    port = live.serve()
    assert port != LIVE_PORT and live.port == port
    client = LiveClient(port=port, timeout=2.0, retries=0)
    assert client.ping() >= 0
    assert client.run("result = [t.name for t in song.tracks]") == ["kick", "keys"]
    direct, wire = live.execute("song.tracks[0].mixer_device"), client.execute("song.tracks[0].mixer_device")
    assert (direct.status, direct.result, direct.error) == (wire.status, wire.result, wire.error)
    bad_direct, bad_wire = live.execute("nope"), client.execute("nope")
    assert (bad_direct.error, bad_direct.warning) == (bad_wire.error, bad_wire.warning)
    kept = LiveClient(port=port, timeout=2.0, retries=0, keep=True)
    assert [kept.run("1 + 1"), kept.run("2 + 2")] == [2, 4]
    kept.close()
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as raw:
        raw.sendall(b"not json\n")
        assert json.loads(raw.makefile().readline()) == {"status": "error", "error": "Malformed JSON"}


def test_serving_refuses_lives_own_port_and_close_drops_a_kept_client(live):
    with pytest.raises(ValueError, match="real Live's port"):
        live.serve(LIVE_PORT)
    port = live.serve()
    kept = LiveClient(port=port, timeout=2.0, retries=0, keep=True)
    kept.run("1")
    live.close()  # must not wait for the kept connection
    with pytest.raises(LiveError, match="Cannot reach Ableton"):
        LiveClient(port=port, timeout=1.0, retries=0).run("1")


def test_modules_the_code_registers_by_hand_go_at_close():
    with FakeLive() as live:
        live.run("import sys, types\nsys.modules['zz_fakelive_probe'] = types.ModuleType('zz_fakelive_probe')")
        assert "zz_fakelive_probe" in sys.modules
        assert live.run("import sys\nresult = 'zz_fakelive_probe' in sys.modules")
    assert "zz_fakelive_probe" not in sys.modules
    assert "json" in sys.modules and "Live" not in sys.modules


# --------------------------------------------------------------------------- the set's behaviour


def test_listeners_fire_on_change_and_writes_inside_them_are_refused(live):
    heard = []
    kick = live.song.tracks[0]
    kick.add_mute_listener(lambda: heard.append(("mute", kick.mute)))
    kick.mixer_device.volume.add_value_listener(lambda: heard.append(("volume", kick.mixer_device.volume.value)))
    live.song.add_tempo_listener(lambda: setattr(live.song, "loop", True))
    live.run("song.tracks[0].mute = True")
    live.run("song.tracks[0].mute = True")  # no change, no notification
    live.run("song.tracks[0].mixer_device.volume.value = 0.5\nsong.tempo = 99")
    assert heard == [("mute", True), ("volume", 0.5)]
    assert kick.mixer_device.track_activator.value == 0.0
    assert not live.song.loop and NOTIFICATION_REFUSED in live.listener_errors[0]
    fn = heard.append
    kick.add_solo_listener(fn)
    assert kick.solo_has_listener(fn)
    kick.remove_solo_listener(fn)
    assert not kick.solo_has_listener(fn)
    with pytest.raises(AttributeError, match="'Track' object has no attribute 'add_bogus_listener'"):
        kick.add_bogus_listener(fn)


def test_what_parameters_show(live):
    eq = live.song.tracks[0].devices[0]
    p = {x.name: x for x in eq.parameters}
    assert [p["Device On"].str_for_value(v) for v in (0, 1)] == ["Off", "On"]
    assert [p["1 Filter Type A"].str_for_value(v) for v in (0, 3, 7)] == ["High Pass 48dB", "Bell", "Low Pass 48dB"]
    assert p["1 Filter Type A"].value_items[3] == "Bell" and p["1 Filter Type A"].is_quantized
    # measured pairs from zpkt.live.knobs: raw LOM value -> what a dump of the real Live showed
    assert p["1 Frequency A"].str_for_value(0.8074892) == "5.00 kHz"
    assert p["1 Gain A"].str_for_value(-14.8) == "-14.8 dB" and p["1 Gain A"].str_for_value(0) == "0.00 dB"
    assert p["1 Q A"].str_for_value(0.37803) == "0.71"
    mixer = live.song.tracks[0].mixer_device
    assert [mixer.volume.str_for_value(v) for v in (0.0, 0.85, 1.0)] == ["-inf dB", "0.0 dB", "6.0 dB"]
    assert [mixer.panning.str_for_value(v) for v in (-1.0, -0.5, 0.0, 0.5)] == ["50L", "25L", "C", "25R"]
    assert [mixer.sends[0].str_for_value(v) for v in (0.0, 1.0)] == ["-inf dB", "0.0 dB"]
    assert str(mixer.volume) == mixer.volume.str_for_value(0.6)


def test_utility_and_compressor_show_what_the_measured_values_did():
    utility = {
        p.name: p
        for p in fake_set({"tracks": [{"name": "t", "devices": ["Utility", "Compressor"]}]})
        .tracks[0]
        .devices[0]
        .parameters
    }
    assert utility["Output"].str_for_value(-0.2222222) == "-7.78 dB"
    assert utility["Bass Freq"].str_for_value(0.3802112) == "120 Hz"
    assert utility["Stereo Width"].str_for_value(0.9365079) == "88 %"
    comp = {
        p.name: p
        for p in fake_set({"tracks": [{"name": "t", "devices": ["Compressor"]}]}).tracks[0].devices[0].parameters
    }
    assert comp["Ratio"].str_for_value(0.6666667) == "3.00 : 1"
    assert comp["Attack"].str_for_value(0.1796875) == "0.08 ms"


def test_values_outside_the_range_are_refused(live):
    with pytest.raises(LiveError, match="Invalid value"):
        live.run("song.tracks[0].mixer_device.volume.value = 1.5")
    with pytest.raises(LiveError, match="has no mute"):
        live.run("song.master_track.mute = True")
    with pytest.raises(LiveError, match="has no arm"):
        live.run("song.return_tracks[0].arm = True")


def test_tracks_returns_and_the_stale_alias(live):
    assert live.run("song.create_audio_track(-1)\nresult = (len(tracks), len(song.tracks))") == [2, 3]
    live.run("song.create_return_track()\nsong.return_tracks[-1].name = 'Echo'")
    assert live.run("[r.name for r in song.return_tracks]") == ["A-Space", "B-Echo"]
    assert live.run("[len(t.mixer_device.sends) for t in list(song.tracks) + list(song.return_tracks)]") == [2] * 5
    live.run("song.delete_return_track(0)")
    assert live.run("[r.name for r in song.return_tracks]") == ["A-Echo"]
    assert live.run("song.tracks[0].mixer_device.sends[0].value") == 0.0  # Space's send went with it


def test_undo_takes_back_the_last_call(live):
    live.run("song.tempo = 90\nsong.tracks[0].name = 'renamed'")
    live.run("song.create_midi_track(-1)")
    live.run("song.undo()")
    assert len(live.song.tracks) == 2
    live.run("song.undo()")
    assert (live.song.tempo, live.song.tracks[0].name) == (128.0, "kick")


def test_the_browser_finds_and_loads_onto_the_selected_track(live):
    assert live.run("find_item(browser.audio_effects, 'eq eight').name") == "EQ Eight"
    assert live.run("[i.name for i in find_items(browser.audio_effects, 'comp')]") == [
        "Compressor",
        "Glue Compressor",
    ]  # starts-with before contains
    live.run("load_to(song.tracks[0], browser.audio_effects, 'Saturator')")
    assert [d.name for d in live.song.tracks[0].devices] == ["EQ", "Saturator"]
    assert live.song.view.selected_track is live.song.tracks[0]
    with pytest.raises(LiveError, match="No loadable item matching 'Nope'"):
        live.run("load_to(song.tracks[0], browser.audio_effects, 'Nope')")


def test_selecting_a_midi_track_arms_it(live):
    live.run("song.view.selected_track = song.tracks[1]")
    assert live.song.tracks[1].arm
    live.run("song.view.selected_track = song.tracks[0]")
    assert not live.song.tracks[1].arm


def test_clips_notes_and_the_transport(live):
    assert live.run("[(c.start_time, c.end_time, c.is_midi_clip) for c in song.tracks[1].arrangement_clips]") == [
        [4.0, 12.0, True]
    ]
    live.run(
        "c = song.tracks[1].create_midi_clip(16.0, 4.0)\n"
        "c.add_new_notes((MidiNoteSpecification(pitch=64, start_time=0.5, duration=0.25, velocity=90),))"
    )
    assert live.run("[n.pitch for n in song.tracks[1].arrangement_clips[1].get_notes_extended(0, 128, 0, 4)]") == [64]
    assert live.song.last_event_time == 20.0
    live.run(
        "song.start_time = 8.0\nsong.loop = True\nsong.loop_start = 8.0\nsong.loop_length = 4.0\nsong.start_playing()"
    )
    assert live.song.is_playing and live.song.current_song_time == 8.0
    live.play_for(5.0)
    assert live.song.current_song_time == 9.0  # wrapped by the loop
    live.run("song.stop_playing()")
    assert not live.song.is_playing
    assert isinstance(MidiNoteSpecification(60, 0, 1), MidiNoteSpecification)


def test_hw002_like_has_the_mix_desks_shape():
    with FakeLive(hw002_like()) as live:
        names = live.run("result = [t.name for t in song.tracks]")
        assert {"Kick bus", "Hats bus", "Break bus", "Chord and splash bus", "Perc bus", "Transitions bus"} <= set(
            names
        )
        assert names[-6:] == ["mon A", "mon B", "mon C1", "mon C2", "mon C3", "mon C4"]
        assert live.run("[r.name for r in song.return_tracks]") == ["A-Space", "B-Echo"]
        assert live.run("[d.name for d in song.master_track.devices]") == ["desk Glue", "desk Utility", "desk headroom"]
        assert live.run("[d.name for d in find_track('Kick bus').devices]") == ["desk EQ", "desk Sat", "desk Glue"]
        assert live.run("str(song.master_track.devices[2].parameters[9])") == "-6.00 dB"
        assert live.run("str(find_track('kick').output_routing_type.display_name)") == "Kick bus"
        assert live.run("all(t.mute for t in song.tracks if t.name.startswith('mon '))")


def test_fake_set_refuses_what_it_does_not_know():
    with pytest.raises(ValueError, match="unknown keys \\['volum'\\]"):
        fake_set({"tracks": [{"name": "a", "volum": 0.5}]})
    with pytest.raises(ValueError, match="has no parameter 'Gian'"):
        fake_set({"tracks": [{"name": "a", "devices": [{"device": "EQ Eight", "params": {"Gian": 1}}]}]})
    with pytest.raises(KeyError, match="no built-in device 'Phaser'"):
        fake_set({"tracks": [{"name": "a", "devices": ["Phaser"]}]})
    plugin = fake_set(
        {
            "tracks": [
                {
                    "name": "a",
                    "devices": [
                        {
                            "name": "Decapitator",
                            "class_name": "PluginDevice",
                            "params": [{"name": "Drive", "value": 0.3}],
                        }
                    ],
                }
            ]
        }
    )
    assert [(p.name, p.value) for p in plugin.tracks[0].devices[0].parameters] == [("Device On", 1.0), ("Drive", 0.3)]
