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
