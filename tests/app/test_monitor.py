"""zpkt.app.monitor on FakeLive: Now, the Pin, the Reference, the level match and the transport."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from tests.app.conftest import wait_for
from tests.app.test_web import first_control
from zpkt.app.bus import Command
from zpkt.live import state as S


def live_value(rig, key):
    return S.flatten(S.take(rig.conn))[key]


def move(rig, key, n, who="you"):
    reply = rig.desk.bus.submit(Command("mix.set", who, {"norms": [[key, n]]}, approval="user"))
    assert reply[0] == 200, reply
    return reply


def test_changed_counts_from_where_the_desk_first_saw_the_mix_until_a_pin_is_set(rig):
    _, key, _ = first_control(rig, "f")
    assert rig.desk.monitor.changed() == []
    move(rig, key, 0.2)
    assert rig.desk.monitor.changed() == [key]
    assert rig.command("monitor.pin")[0] == 200
    assert rig.desk.monitor.changed() == []
    assert (rig.tmp / "state" / "pin.json").exists()  # the pin is a checkpoint, so `hands live state` can read it
    assert rig.get("/api/hear")[1]["pin"] == "pin"


def test_hearing_the_pin_puts_its_values_in_live_and_now_puts_them_back(rig):
    _, key, _ = first_control(rig, "f")
    start = live_value(rig, key)
    move(rig, key, 0.2)
    moved = live_value(rig, key)
    assert moved.raw != start.raw
    assert rig.command("monitor.hear", {"hearing": "pin"})[0] == 200
    assert live_value(rig, key).raw == start.raw  # Live plays the pinned version
    hear = rig.get("/api/hear")[1]
    assert hear["hearing"] == "pin" and hear["changed"] == 1
    assert rig.command("monitor.hear", {"hearing": "now"})[0] == 200
    assert live_value(rig, key).raw == moved.raw
    assert rig.get("/api/hear")[1]["hearing"] == "now"


def test_hearing_the_pin_makes_no_history_entries(rig):
    _, key, _ = first_control(rig, "f")
    move(rig, key, 0.2)
    before = len(rig.desk.history.entries)
    rig.command("monitor.hear", {"hearing": "pin"})
    rig.command("monitor.hear", {"hearing": "now"})
    import time

    time.sleep(0.3)  # the echoes of the writes come back from the pager
    assert len(rig.desk.history.entries) == before


def test_touching_a_control_while_the_pin_is_heard_goes_back_to_now_and_counts_from_there(rig):
    _, key, _ = first_control(rig, "f")
    other = next(
        v["key"] for k, v in rig.state()["values"].items() if v.get("key") and v["key"] != key and k.endswith("k1")
    )
    start = live_value(rig, key)
    move(rig, key, 0.2)
    moved = live_value(rig, key)
    rig.command("monitor.hear", {"hearing": "pin"})
    now_other = live_value(rig, other)
    # the MiniLab turns another knob: the pager says so
    rig.send(
        {
            "t": "v",
            "page": 0,
            "slot": "k1",
            "n": 0.9,
            "s": "x",
            "r": now_other.raw + 0.01,
            "key": other,
            "who": "minilab",
        }
    )
    assert wait_for(lambda: rig.get("/api/hear")[1]["hearing"] == "now")
    assert wait_for(lambda: live_value(rig, key).raw == moved.raw)  # Now is back in Live
    assert start.raw != moved.raw
    entry = rig.desk.history.entries[-1]
    assert entry["who"] == "minilab" and entry["moves"][0]["key"] == other
    assert entry["moves"][0]["from"][1] == now_other.raw  # counted from Now, not from the pin


def test_the_minilab_can_compare_with_the_pin_and_let_go(rig):
    _, key, _ = first_control(rig, "f")
    move(rig, key, 0.2)
    assert rig.desk.bus.submit(Command("monitor.hear", "minilab", {"hearing": "pin"}))[0] == 200
    assert rig.get("/api/hear")[1]["hearing"] == "pin"
    assert rig.desk.bus.submit(Command("monitor.hear", "minilab", {"hearing": "now"}))[0] == 200
    assert rig.get("/api/hear")[1]["hearing"] == "now"
    assert [e["who"] for e in rig.desk.bus.log if e["kind"] == "monitor.hear"] == ["minilab", "minilab"]


def test_hear_must_name_now_pin_or_ref(rig):
    assert rig.command("monitor.hear", {"hearing": "loud"}) == (400, {"error": "hearing is one of now, pin, ref"})


def test_the_reference_is_a_monitor_track_soloed_at_the_matched_level(rig):
    assert rig.command("monitor.hear", {"hearing": "ref"})[0] == 200
    assert rig.state()["monitor"] == {"slot": "C", "ref": "C1"}
    mon = rig.track("mon C1")
    assert mon.solo and not mon.mute
    assert rig.get("/api/hear")[1]["hearing"] == "ref"
    assert rig.live.song.current_song_time >= rig.desk.settings.align_beat  # the reference only exists from the drop
    rig.command("monitor.hear", {"hearing": "now"})
    assert rig.state()["monitor"]["slot"] == "W" and rig.track("mon C1").mute


def test_the_reference_loops_over_its_own_clip_and_the_songs_loop_comes_back(rig):
    """The reference went silent where its file ended while the song's loop ran on (Anthony, 26 November 2026). While
    it is heard, Live loops from the drop for as long as the reference's file lasts."""
    song, a = rig.live.song, rig.desk.settings.align_beat
    wav = rig.desk.settings.viz_dir / "C1.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav), np.zeros(44100 * 9), 44100)  # nine seconds of reference
    rig.command("transport", {"action": "loop", "loop": "whole"})
    whole = (song.loop_start, song.loop_length)
    assert rig.command("monitor.hear", {"hearing": "ref"})[0] == 200
    beats = 9.0 * song.tempo / 60.0
    assert song.loop and song.loop_start == a and song.loop_length == pytest.approx(beats, abs=0.01)
    assert a <= song.current_song_time < a + beats
    rig.command("monitor.hear", {"hearing": "now"})
    assert (song.loop_start, song.loop_length) == whole and rig.state()["loop"] == "whole"


def test_the_old_monitor_route_still_switches_and_main_is_bypassed_then_restored(rig):
    main = {d.name: d.parameters[0].value for d in rig.live.song.master_track.devices if d.name.startswith("desk")}
    assert rig.post("/api/monitor", {"slot": "A", "ref": "C1"}) == (200, {"ok": True})
    assert rig.track("mon A").solo
    assert all(d.parameters[0].value == 0.0 for d in rig.live.song.master_track.devices if d.name in main)
    assert rig.desk.monitor.main_saved == main
    rig.post("/api/monitor", {"slot": "W", "ref": "C1"})
    assert {d.name: d.parameters[0].value for d in rig.live.song.master_track.devices if d.name in main} == main
    assert rig.desk.monitor.main_saved is None


def test_the_pager_is_told_what_the_monitor_did_so_a_reload_carries_it_on(rig):
    rig.post("/api/monitor", {"slot": "B", "ref": "C2"})
    assert rig.live.run(
        "import sys\nm = sys.modules['zpkt_mixdesk_pager']\nresult = [m.DESK.monitor_slot, m.DESK.monitor_ref]"
    ) == [
        "B",
        "C2",
    ]
    rig.desk.restart_pager()  # the reload carries the monitor over
    assert rig.state()["monitor"] == {"slot": "B", "ref": "C2"}


def test_a_monitor_track_that_is_missing_leaves_the_choice_as_it_was(rig):
    rig.live.run("song.delete_track([t.name for t in song.tracks].index('mon B'))\nresult = 1")
    code, _ = rig.post("/api/monitor", {"slot": "B", "ref": "C1"})
    assert code == 200
    assert rig.state()["monitor"]["slot"] == "W"


def _reference_file(rig, ref, seconds):
    wav = rig.desk.settings.viz_dir / f"{ref}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(wav), np.zeros(int(44100 * seconds)), 44100)


def test_the_reference_is_switched_to_and_from_on_the_beat_at_its_own_tempo(rig):
    """Anthony, 26 November 2026: "switch on the beat to C (allowing for mismatched tempos)". C1 is at 155 BPM in a
    160 BPM set and its cut holds 19 of its own bars (sources.json). Choosing it puts the playhead at the same bar
    after the drop and the same place in the bar, counted in the reference's bars, and loops those 19 bars; leaving
    it finds the same bar and place in the mix again and brings the mix's loop back. One call to Live each way."""
    song, a = rig.live.song, rig.desk.settings.align_beat
    assert rig.desk.settings.reference_grids["C1"] == (155.0, 19.0)
    ref_bar = 4.0 * song.tempo / 155.0  # one bar of the reference, in the set's beats
    _reference_file(rig, "C1", 19 * 4 * 60 / 155.0 + 0.002)
    rig.command("transport", {"action": "loop", "loop": "drop"})
    drop = (song.loop_start, song.loop_length)
    song.current_song_time = a + 3 * 4.0 + 1.5  # the mix: bar 4 of the drop, a beat and a half in
    assert rig.command("monitor.hear", {"hearing": "ref"})[0] == 200
    assert song.current_song_time == pytest.approx(a + (3 + 1.5 / 4.0) * ref_bar, abs=1e-6)
    assert song.loop and song.loop_start == a and song.loop_length == pytest.approx(19 * ref_bar, abs=1e-6)
    song.current_song_time = a + (7 + 0.25) * ref_bar  # the reference played on: its bar 8, a quarter in
    assert rig.command("monitor.hear", {"hearing": "now"})[0] == 200
    assert song.current_song_time == pytest.approx(a + (7 + 0.25) * 4.0, abs=1e-6)
    assert (song.loop_start, song.loop_length) == drop and rig.state()["loop"] == "drop"


def test_a_switch_from_the_build_lands_inside_the_reference(rig):
    """The reference has no build: a place before the drop is found among its own bars, the place in the bar kept."""
    song, a = rig.live.song, rig.desk.settings.align_beat
    ref_bar = 4.0 * song.tempo / 155.0
    _reference_file(rig, "C1", 19 * 4 * 60 / 155.0 + 0.002)
    song.current_song_time = 4.0 * 2 + 3.0  # bar 3 of the build, three beats in
    rig.command("monitor.hear", {"hearing": "ref"})
    bars = (song.current_song_time - a) / ref_bar
    assert 0 <= bars < 19 and bars % 1 == pytest.approx(0.75, abs=1e-6)


def test_a_reference_at_the_sets_tempo_keeps_its_place(rig):
    """C2 is at the set's own 160 BPM: on the drop its bars are the mix's, so the playhead does not move."""
    song, a = rig.live.song, rig.desk.settings.align_beat
    _reference_file(rig, "C2", 20 * 1.5 + 0.01)
    rig.command("monitor.choose", {"slot": "W", "ref": "C2"})
    song.current_song_time = a + 9.25
    rig.command("monitor.hear", {"hearing": "ref"})
    assert song.current_song_time == pytest.approx(a + 9.25, abs=1e-6) and song.loop_length == pytest.approx(80.0)


def test_play_and_loop_go_through_the_pager(rig):
    assert rig.command("transport", {"action": "play"})[0] == 200 and rig.live.song.is_playing
    assert rig.command("transport", {"action": "loop", "loop": "drop"})[0] == 200 and rig.live.song.loop
    assert rig.command("transport", {"action": "loop", "loop": "sideways"})[0] == 400


def test_the_hearing_says_what_is_heard_for_every_slot():
    from zpkt.app.monitor import hearing_of

    assert hearing_of("W", False) == "now"
    assert hearing_of("C", False) == "ref"
    assert hearing_of("A", False) == "original"  # a legacy render is not Now
    assert hearing_of("B", False) == "recipe"
    assert [hearing_of(s, True) for s in "ABWC"] == ["pin"] * 4  # the Pin comes first
