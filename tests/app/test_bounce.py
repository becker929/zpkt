"""Bounce and measure (zpkt.app.bounce_commands) on FakeLive, with the Export dialog stood in: an agent renders the
mix or a track, reads a few numbers and never the audio, and Live is left as it was."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests.app.test_monitor import live_value, move
from tests.app.test_web import first_control
from zpkt.app import bounce_commands
from zpkt.app.ask import mcp, tools
from zpkt.app.bus import Command
from zpkt.live import render

SR = 44100
BAR_S = 1.5  # a bar of four beats at 160


def ask(rig, kind, args=None, who="agent", **kw):
    return rig.desk.bus.submit(Command(kind, who, args or {}, **kw))


def tone(hz: float, amp: float, seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return amp * np.sin(2 * np.pi * hz * t) * np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)


@pytest.fixture()
def exports(rig, monkeypatch):
    """Live's export, stood in: it makes the range the loop (as the real one does), writes a tone whose pitch says
    what was rendered, under the name Live gives the file, and keeps what it was asked."""
    asked = []
    level = {"Main": (100, 0.5), "Kick bus": (50, 0.25), "A-Space": (4000, 0.1), "kick": (50, 0.0)}

    def export(live, out, start, length, *, mode="Main", bits=32, **kw):
        song = rig.live.song
        asked.append({"out": out, "start": start, "length": length, "mode": mode, "bits": bits, "kw": kw})
        asked[-1]["playing"], asked[-1]["soloed"] = song.is_playing, [t.name for t in song.tracks if t.solo]
        song.loop, song.loop_start, song.loop_length = True, start, length
        hz, amp = level.get(mode, (1000, 0.2))
        out.parent.mkdir(parents=True, exist_ok=True)
        path = out if mode == "Main" else out.with_name(f"{out.stem} {mode}{out.suffix}")
        mono = tone(hz, amp, length * 60 / song.tempo)
        sf.write(str(path), np.column_stack([mono, mono]), SR, subtype="PCM_24")
        return [path]

    monkeypatch.setattr(render, "export", export)
    return asked


def test_a_bounce_of_the_mix_answers_with_the_path_and_a_short_sheet(rig, exports):
    song = rig.live.song
    song.loop, song.loop_start, song.loop_length = True, 64.0, 96.0
    code, got = ask(rig, "render.bounce", {"bars": [17, 20]})
    assert code == 200, got
    assert exports[0]["mode"] == "Main" and (exports[0]["start"], exports[0]["length"]) == (64.0, 16.0)
    assert exports[0]["bits"] == 24
    (one,) = got["files"]
    path = Path(one["file"])
    assert path.is_file() and path.parent == rig.tmp / "renders" / "bounce" and path.suffix == ".wav"
    assert one["what"] == "mix" and one["bars"] == [17, 20] and one["seconds"] == 4 * BAR_S
    assert one["rms_db"] == pytest.approx(-9.0, abs=0.2) and one["bands_db"]["low"] == pytest.approx(-9.0, abs=0.2)
    assert set(one) == {
        "what", "file", "bars", "seconds", "lufs", "true_peak_db", "peak_db", "rms_db", "crest_db", "bands_db",
        "stereo",
    }  # fmt: skip
    assert len(json.dumps(got)) < 700  # a few numbers, never the audio
    assert got["hearing"] == "now" and got["tempo"] == 160 and "stopped_playback" not in got and "soloed" not in got
    # Live is as it was: the loop the export moved is back, no History row, no version, nothing of the mix written
    assert (song.loop, song.loop_start, song.loop_length) == (True, 64.0, 96.0)
    assert rig.desk.history.entries == []
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["bars"] == [17, 20] and meta["tempo"] == 160.0 and meta["set"] == "HW002_121_pp_finish"


def test_with_no_bars_it_is_the_loop_when_on_else_the_song(rig, exports):
    song = rig.live.song
    assert ask(rig, "render.bounce", {"bars": "loop"})[1]["files"][0]["bars"] == [1, 16]  # the brace, on or off
    song.loop, song.loop_start, song.loop_length = True, 32.0, 8.0
    assert ask(rig, "render.bounce")[1]["files"][0]["bars"] == [9, 10]
    song.loop = False
    code, got = ask(rig, "render.bounce")
    assert code == 200 and got["files"][0]["bars"] == [1, 40] and got["files"][0]["seconds"] == 60.0
    assert (exports[-1]["start"], exports[-1]["length"]) == (0.0, 160.0)
    assert (song.loop, song.loop_start, song.loop_length) == (False, 32.0, 8.0)  # an off loop comes back off


def test_tracks_groups_and_returns_are_one_file_each_under_the_name_asked_for(rig, exports):
    code, got = ask(rig, "render.bounce", {"what": ["Kick bus", "a-space", "mix"], "bars": [1, 2], "name": "Before"})
    assert code == 200, got
    assert [e["mode"] for e in exports] == ["Kick bus", "A-Space", "Main"]  # the set's own spelling goes to Live
    assert [f["what"] for f in got["files"]] == ["Kick bus", "A-Space", "mix"]
    names = [Path(f["file"]).name for f in got["files"]]
    assert all(n.endswith("-bars-1-2.wav") for n in names) and "before-kick-bus" in names[0]
    assert sorted(p.name for p in (rig.tmp / "renders" / "bounce").glob("*.wav")) == sorted(names)  # Live's name gone
    assert got["files"][0]["bands_db"]["sub"] == pytest.approx(-15.0, abs=0.3)  # the 50 Hz tone of the Kick bus
    rig.track("kick").mute = True
    quiet = ask(rig, "render.bounce", {"what": "kick", "bars": [1, 1]})[1]["files"][0]
    assert quiet["silent"] is True and quiet["muted"] is True


def test_what_cannot_be_bounced_is_refused_before_live_is_touched(rig, exports, monkeypatch):
    rig.live.song.is_playing = True
    monkeypatch.setattr(bounce_commands, "MAX_AUDIO_S", 200.0)  # the song is 60 s: four files of it are too much
    for args, code, said in (
        ({"what": "mon A"}, 403, "monitor"),
        ({"what": "Kick buss"}, 400, "the set has: kick, Kick bus"),
        ({"what": ["kick", "Kick bus", "p2-oh", "p2-rd1", "crash"]}, 400, "at most 4"),
        ({"what": []}, 400, "'what' is"),
        ({"what": 3}, 400, "'what' is"),
        ({"bars": [0, 4]}, 400, "'bars' is"),
        ({"bars": [5, 4]}, 400, "'bars' is"),
        ({"bars": "verse"}, 400, "'bars' is"),
        ({"bars": [41, 44]}, 400, "ends after bar 40"),
        ({"bars": [1, 40], "what": ["kick", "crash", "Kick bus", "chord"]}, 400, "more than 200 s"),
        ({"name": ""}, 400, "'name' is"),
    ):
        got = ask(rig, "render.bounce", args)
        assert got[0] == code and said in got[1]["error"], (args, got)
    assert "mon A" not in ask(rig, "render.bounce", {"what": "nope"})[1]["error"]  # the rail: never offered
    assert exports == [] and rig.live.song.is_playing  # nothing was exported, and playback went on
    assert not (rig.tmp / "renders" / "bounce").exists() or not list((rig.tmp / "renders" / "bounce").iterdir())


def test_playback_stops_and_solos_are_named(rig, exports):
    rig.live.song.is_playing = True
    rig.track("Kick bus").solo = True
    code, got = ask(rig, "render.bounce", {"bars": [1, 2]})
    assert code == 200 and got["stopped_playback"] is True and got["soloed"] == ["Kick bus"]
    assert exports[0]["playing"] is False and exports[0]["soloed"] == ["Kick bus"]  # stopped first; the solo is left
    assert rig.track("Kick bus").solo is True


def test_a_heard_reference_is_left_and_the_pin_comes_back(rig, exports, monkeypatch):
    assert rig.command("monitor.hear", {"hearing": "ref"})[0] == 200
    assert any(t.solo for t in rig.live.song.tracks if t.name.startswith("mon "))
    code, got = ask(rig, "render.bounce", {"bars": [1, 2]})
    assert code == 200 and got["hearing"] == "now" and got["was_hearing"] == "ref" and "soloed" not in got
    assert exports[0]["soloed"] == []  # Now was heard when the export ran: no monitor track soloed
    assert rig.desk.monitor.message()["hearing"] == "now"
    # the Pin: other values are in the mix while it is heard; the bounce is of Now, and the Pin is heard again after
    _, key, _ = first_control(rig, "f")
    pinned = live_value(rig, key).raw
    move(rig, key, 0.2)
    now = live_value(rig, key).raw
    assert now != pinned and rig.command("monitor.hear", {"hearing": "pin"})[0] == 200
    assert live_value(rig, key).raw == pinned
    seen = []
    real = render.export
    monkeypatch.setattr(render, "export", lambda *a, **k: seen.append(live_value(rig, key).raw) or real(*a, **k))
    code, got = ask(rig, "render.bounce", {"bars": [1, 2]})
    assert code == 200 and got["hearing"] == "pin" and "was_hearing" not in got
    assert seen == [now]  # Now's value was in Live for the export
    assert rig.desk.monitor.message()["hearing"] == "pin" and live_value(rig, key).raw == pinned


def test_an_export_that_fails_says_why_and_the_loop_still_comes_back(rig, exports, monkeypatch):
    song = rig.live.song
    song.loop, song.loop_start, song.loop_length = True, 64.0, 96.0
    real = render.export

    def fails_on_the_second(live, out, start, length, **kw):
        if kw.get("mode") != "Main":
            song.loop_start, song.loop_length = start, length
            raise ValueError("export: nothing written after 2 tries")
        return real(live, out, start, length, **kw)

    monkeypatch.setattr(render, "export", fails_on_the_second)
    code, got = ask(rig, "render.bounce", {"what": ["mix", "Kick bus"], "bars": [1, 2]})
    assert code == 409 and "the bounce of Kick bus failed" in got["error"] and "nothing written" in got["error"]
    assert [f["what"] for f in got["files"]] == ["mix"]  # what was written before is said
    assert (song.loop, song.loop_start, song.loop_length) == (True, 64.0, 96.0)


def test_who_may_bounce_and_the_wrong_set_is_held(rig, exports, monkeypatch):
    spec = rig.desk.bus.table["render.bounce"]
    assert spec.effect == "move" and spec.agent_may and spec.touches_live and spec.guarded
    assert (
        rig.desk.bus.table["render.measure"].effect == "read" and not rig.desk.bus.table["render.measure"].touches_live
    )
    assert ask(rig, "render.bounce", {"bars": [1, 1]}, who="you")[0] == 200
    versions = []
    monkeypatch.setattr(rig.desk.bus, "version_before", versions.append)
    assert ask(rig, "render.bounce", {"bars": [1, 1]}, group="ask-s1")[0] == 200
    assert versions == []  # a bounce changes no value: no automatic version is saved for it
    rig.live.song.file_path = "/Sets/other Project/other.als"
    rig.desk.bus.guard.forget()
    code, got = ask(rig, "render.bounce", {"bars": [1, 1]})
    assert code == 409 and "other" in got["error"] and len(exports) == 2  # the wrong set: nothing is rendered


# ---- measuring -----------------------------------------------------------------------------------------------------


@pytest.fixture()
def bounced(rig, exports):
    """Two bounces of bars 1 to 8: the mix (100 Hz) and the Kick bus (50 Hz, 6 dB under it)."""
    code, got = ask(rig, "render.bounce", {"what": ["mix", "Kick bus"], "bars": [1, 8]})
    assert code == 200, got
    return [f["file"] for f in got["files"]]


def test_measure_with_no_file_lists_the_bounces(rig, bounced):
    code, got = ask(rig, "render.measure")
    assert code == 200 and got["count"] == 2 and got["folder"] == str(rig.tmp / "renders" / "bounce")
    assert {(b["what"], tuple(b["bars"])) for b in got["bounces"]} == {("mix", (1, 8)), ("Kick bus", (1, 8))}
    assert all(set(b) == {"file", "what", "bars", "at"} for b in got["bounces"])
    assert isinstance(got["folder_mb"], int) and isinstance(got["references"], list)


def test_measure_gives_one_view_of_one_window(rig, bounced):
    mix = bounced[0]
    code, got = ask(rig, "render.measure", {"file": Path(mix).name})  # a bounce by its name alone
    assert code == 200 and got["file"] == mix and got["what"] == "mix" and got["summary"]["seconds"] == 8 * BAR_S
    code, got = ask(rig, "render.measure", {"file": mix, "bars": [3, 4]})
    assert code == 200 and got["bars"] == [3, 4] and got["summary"]["seconds"] == 2 * BAR_S
    code, got = ask(rig, "render.measure", {"file": mix, "seconds": [0, 1.5], "detail": "spectrum"})
    assert code == 200 and got["seconds"] == [0, 1.5]
    octaves = got["spectrum"]["third_octaves_db"]
    assert max(octaves, key=lambda k: octaves[k]) == "100" and len(octaves) == 29
    code, got = ask(rig, "render.measure", {"file": mix, "detail": "over_time"})
    assert code == 200 and got["over_time"]["step"] == {"bars": 1} and len(got["over_time"]["rms_db"]) == 8
    assert len(json.dumps(got)) < 500
    plain = rig.tmp / "renders" / "bounce" / "plain.wav"  # a file that says nothing of its bars: steps of seconds
    sf.write(str(plain), tone(100, 0.5, 100.0), SR, subtype="PCM_16")
    code, got = ask(rig, "render.measure", {"file": "plain.wav", "detail": "over_time"})
    assert code == 200 and got["over_time"]["step"] == {"seconds": 2} and len(got["over_time"]["rms_db"]) == 50
    code, got = ask(rig, "render.measure", {"file": "plain.wav", "bars": [1, 2]})
    assert code == 400 and "give the window in 'seconds'" in got["error"]


def test_measure_against_a_second_file_gives_the_difference(rig, bounced):
    mix, kick = bounced
    code, got = ask(rig, "render.measure", {"file": kick, "against": mix, "bars": [1, 4]})
    assert code == 200 and got["against"]["file"] == mix and got["against"]["bars"] == [1, 4]
    diff = got["difference"]
    assert diff["rms_db"] == pytest.approx(-6.0, abs=0.2) and diff["peak_db"] == pytest.approx(-6.0, abs=0.2)
    assert diff["bands_db"]["sub"] > 25 and diff["bands_db"]["low"] < -25  # 50 Hz against 100 Hz
    assert "seconds" not in diff
    plain = rig.tmp / "renders" / "bounce" / "plain.wav"
    sf.write(str(plain), tone(50, 0.25, 3.0), SR, subtype="PCM_16")
    code, got = ask(rig, "render.measure", {"file": kick, "against": "plain.wav", "bars": [1, 2]})
    assert code == 200 and got["against"]["window"] == "whole"  # it says no bars: measured whole
    assert got["difference"]["rms_db"] == pytest.approx(0.0, abs=0.3)


def test_a_reference_is_measured_by_its_id(rig, bounced, monkeypatch, tmp_path):
    ref = tmp_path / "ref.wav"
    sf.write(str(ref), tone(100, 0.5, 6.0), SR, subtype="PCM_16")
    monkeypatch.setattr(
        bounce_commands,
        "references",
        lambda: {"c1": {"file": str(ref), "what": "KSMS (C1)", "tempo": 160.0, "beats_per_bar": 4.0, "bars": [1, 4]}},
    )
    code, got = ask(rig, "render.measure", {"file": "C1", "bars": [2, 3]})
    assert code == 200 and got["what"] == "KSMS (C1)" and got["summary"]["seconds"] == 2 * BAR_S
    code, got = ask(rig, "render.measure", {"file": bounced[0], "against": "c1"})
    assert code == 200 and got["against"]["what"] == "KSMS (C1)" and got["against"]["window"] == "whole"
    assert got["difference"]["rms_db"] == pytest.approx(0.0, abs=0.2)
    ref.unlink()
    code, got = ask(rig, "render.measure", {"file": "C1"})
    assert code == 400 and "KSMS (C1) is not on this Mac" in got["error"]


def test_the_real_sources_name_their_references():
    found = bounce_commands.references()
    assert "c1" in found and found["c1"]["bars"][0] == 1 and found["c1"]["what"].endswith("(C1)")


def test_measure_refuses_what_it_cannot_or_must_not_read(rig, bounced, tmp_path):
    mix = bounced[0]
    (rig.tmp / "renders" / "bounce" / "notes.txt").write_text("x")
    hidden = Path.home() / ".zshrc"
    for args, code, said in (
        ({"file": "ghost.wav"}, 400, "no file 'ghost.wav'"),
        ({"file": "notes.txt"}, 400, "not an audio file"),
        ({"file": "/etc/hosts"}, 403, "inside the home folder"),
        ({"file": mix, "detail": "everything"}, 400, "'detail' is one of"),
        ({"file": mix, "bars": [1, 2], "seconds": [0, 1]}, 400, "not both"),
        ({"file": mix, "bars": [7, 12]}, 400, "holds bars 1 to 8"),
        ({"file": mix, "seconds": [3, 1]}, 400, "'seconds' is"),
        ({"file": mix, "seconds": [100, 101]}, 400, "holds nothing"),
        ({"file": mix, "bars": "all"}, 400, "'bars' is [from, to]"),
        ({"file": 7}, 400, "'file' is"),
        ({"file": mix, "against": "ghost.wav"}, 400, "no file 'ghost.wav'"),
    ):
        got = ask(rig, "render.measure", args)
        assert got[0] == code and said in got[1]["error"], (args, got)
    if hidden.exists():
        assert ask(rig, "render.measure", {"file": str(hidden)})[0] == 403


def test_the_oldest_bounces_go_when_the_folder_is_full(rig, exports, monkeypatch):
    import os

    made = []
    for i in range(3):
        f = ask(rig, "render.bounce", {"bars": [1, 1]})[1]["files"][0]["file"]
        os.utime(f, (1000 + i, 1000 + i))
        made.append(Path(f))
    size = made[0].stat().st_size
    bounce_commands.prune(keep_bytes=2 * size)
    assert [p.exists() for p in made] == [False, True, True]
    assert not made[0].with_suffix(".json").exists() and made[1].with_suffix(".json").exists()
    bounce_commands.prune(keep_bytes=0)
    assert [p.exists() for p in made] == [False, False, True]  # never the newest


# ---- as the agent's tools ------------------------------------------------------------------------------------------


def test_the_agent_bounces_and_measures_through_its_tools(asked, exports):
    gate = asked.ask.gate
    code, got = gate.call("s1", gate.token("s1"), "bounce_audio", {"what": "Kick bus", "bars": [1, 4]})
    assert code == 200 and got["files"][0]["what"] == "Kick bus"
    code, got = gate.call(
        "s1", gate.token("s1"), "measure_audio", {"file": got["files"][0]["file"], "detail": "spectrum"}
    )
    assert code == 200 and max(got["spectrum"]["third_octaves_db"].items(), key=lambda kv: kv[1])[0] == "50"
    assert asked.rig.desk.history.entries == []
    row = next(r for r in asked.rig.desk.bus.log if r["kind"] == "render.bounce")
    assert row["who"] == "agent" and row["status"] == 200
    assert mcp.timeout_for("bounce_audio") > 60 + 4 * 13 + 0.1 * bounce_commands.MAX_AUDIO_S  # longer than the longest
    assert "never open the WAV" in tools.BY_NAME["bounce_audio"].description
