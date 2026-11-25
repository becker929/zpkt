"""Characterization of the `hands` commands that talk to Live and had no test of their own: what each prints, its
exit code and what it leaves in the set. Live is FakeLive, served on a free port; the GUI (window titles, dialogs,
osascript) is stubbed. These pin today's behaviour so the refactors after them can show they change nothing.
"""

from __future__ import annotations

import json
import re
import socket

import pytest
from typer.testing import CliRunner

from zpkt.live import session, ui
from zpkt.live.cli import app
from zpkt.live.testing import FakeLive, fake_set

LIVE_PORT = 16619


@pytest.fixture(autouse=True)
def never_the_real_live(monkeypatch):
    real = socket.create_connection

    def guarded(address, *args, **kwargs):
        if address[1] == LIVE_PORT:
            raise AssertionError("a test tried to reach the real Live on 16619")
        return real(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", guarded)


SET = {
    "tempo": 128.0,
    "tracks": [
        {"name": "kick", "type": "midi", "devices": ["Operator"]},
        {"name": "REF Roses", "mute": True},
        {"name": "REF Hedon", "mute": True},
    ],
    "returns": [{"name": "Space", "devices": ["Reverb"]}],
}


@pytest.fixture
def live():
    with FakeLive(fake_set(SET)) as fake:
        yield fake


@pytest.fixture
def port(live):
    return ["--port", str(live.serve())]


@pytest.fixture
def front(monkeypatch):
    """Live's window, without Live: the set in front and the dialogs open."""
    seen = {"title": "test_set", "dialogs": 0}
    monkeypatch.setattr(ui, "front_title", lambda: seen["title"])
    monkeypatch.setattr(ui, "dialogs", lambda: seen["dialogs"])
    return seen


def invoke(*argv: str, **kwargs):
    return CliRunner().invoke(app, list(argv), **kwargs)


# --------------------------------------------------------------------------- hands live check, modals


def test_live_check_prints_the_front_set_or_the_guard(live, port, front):
    ok = invoke("live", "check", *port)
    assert ok.exit_code == 0 and ok.stdout.strip() == "test_set"
    front["dialogs"] = 1
    stopped = invoke("live", "check", *port)
    assert stopped.exit_code == 1
    assert "GUARD: hands live check: 1 dialog(s) open in Live" in stopped.stderr
    front.update(dialogs=0, title="Anthony's set")
    assert invoke("live", "check", *port).exit_code == 1
    assert invoke("live", "check", "--any-set", *port).exit_code == 0
    assert invoke("live", "check", "--expect", "test_other", *port).exit_code == 1


def test_live_modals_reports_clean_open_and_what_the_script_says(monkeypatch):
    monkeypatch.setattr(ui, "reap_modals", lambda reap: "CLEAN\n")
    monkeypatch.setattr(ui, "dialogs", lambda: 0)
    assert invoke("live", "modals").stdout.strip() == "CLEAN"
    monkeypatch.setattr(ui, "dialogs", lambda: 2)
    out = invoke("live", "modals").stdout
    assert out.startswith("OPEN | 2 dialog(s) Live draws itself")
    asked = []
    monkeypatch.setattr(ui, "reap_modals", lambda reap: asked.append(reap) or "REAPED | Cancel")
    assert invoke("live", "modals", "--reap").stdout.strip() == "REAPED | Cancel" and asked == [True]

    def broken(reap):
        raise ui.UiError("no accessibility")

    monkeypatch.setattr(ui, "reap_modals", broken)
    res = invoke("live", "modals")
    assert res.exit_code == 1 and "no accessibility" in res.stderr


# --------------------------------------------------------------------------- hands live save, state ls/diff


def test_live_save_keeps_a_copy_and_the_state(live, port, front, rig, monkeypatch):
    (rig.sets_dir / "test_set.als").write_bytes(b"als")
    saved = []
    monkeypatch.setattr(session, "save", lambda name: saved.append(name) or True)
    res = invoke("live", "save", "--as", "test_copy", "--state", "kept", *port)
    assert res.exit_code == 0, res.output
    assert saved == ["test_set"]
    assert f"saved {rig.sets_dir / 'test_set.als'}" in res.stdout
    assert (rig.sets_dir / "test_copy.als").read_bytes() == b"als"
    state = json.loads((rig.sets_dir / "state" / "test_set" / "kept.json").read_text())
    assert state["set"] == "test_set" and set(state["tracks"]) == {"kick", "REF Roses", "REF Hedon", "A-Space", "Main"}
    again = invoke("live", "save", "--as", "test_copy", *port)
    assert again.exit_code == 1 and "exists; pick another name" in again.stderr


def test_live_save_says_when_there_was_nothing_to_save(front, rig, monkeypatch):
    monkeypatch.setattr(session, "save", lambda name: False)
    res = invoke("live", "save")
    assert res.exit_code == 0 and res.stdout.strip() == f"nothing to save in {rig.sets_dir / 'test_set.als'}"


def test_live_save_falls_back_to_the_set_hands_last_saw(rig, monkeypatch):
    def unreadable():
        raise ui.UiError("window on another Space")

    monkeypatch.setattr(ui, "front_title", unreadable)
    monkeypatch.setattr(session, "save", lambda name: True)
    (rig.data_dir / "live_loaded.json").write_text(json.dumps({"test_old": 1, "test_new": 2}))
    res = invoke("live", "save")
    assert res.exit_code == 0 and "test_new.als" in res.stdout
    assert "using test_new, the set hands last saw open" in res.stderr
    (rig.data_dir / "live_loaded.json").unlink()
    res = invoke("live", "save")
    assert res.exit_code == 1 and "Live shows no set" in res.stderr


def test_live_state_ls_lists_newest_first(front, rig):
    res = invoke("live", "state", "ls")
    assert res.stdout.strip() == f"none in {rig.sets_dir / 'state' / 'test_set'}"
    folder = rig.sets_dir / "state" / "test_set"
    folder.mkdir(parents=True)
    import os

    for k, name in enumerate(("old", "new")):
        (folder / f"{name}.json").write_text("{}")
        os.utime(folder / f"{name}.json", (1_700_000_000 + k * 60, 1_700_000_000 + k * 60))
    lines = invoke("live", "state", "ls").stdout.splitlines()
    assert [line.split()[0] for line in lines] == ["new", "old"]
    assert re.fullmatch(r"new\s+\d{4}-\d\d-\d\d \d\d:\d\d", lines[0])


def test_live_state_diff_of_two_files_needs_no_live(tmp_path):
    def state(volume: list) -> dict:
        return {
            "returns": ["A-Space"],
            "tracks": {"kick": {"mixer": {"volume": volume, "sends": {"A-Space": ["-inf dB", 0.0]}}, "devices": []}},
        }

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(state(["0.0 dB", 0.85])))
    b.write_text(json.dumps(state(["-6.0 dB", 0.7])))
    res = invoke("live", "state", "diff", str(a), str(b))
    assert res.exit_code == 1
    assert res.stdout == "2 values in A, 1 differ\nkick/volume: 0.0 dB -> -6.0 dB\n"
    assert invoke("live", "state", "diff", str(a), str(a)).stdout == "2 values in A, 0 differ\nsame\n"


# --------------------------------------------------------------------------- hands live audition


def test_live_audition_plays_a_chord_and_leaves_the_set_as_it_was(live, port):
    res = invoke("live", "audition", "kick", "--notes", "60,64", "--listen", "0.3", *port)
    assert res.exit_code == 0, res.output
    got = json.loads(res.stdout)
    assert set(got) == {"peak", "series", "sound"} and got["sound"] is False
    kick = live.song.tracks[0]
    assert kick.arrangement_clips == () and not live.song.is_playing and live.song.start_time == 0.0
    live.song.start_playing()
    busy = invoke("live", "audition", "kick", "--listen", "0.1", *port)
    assert busy.exit_code == 1 and "Live is playing" in busy.stderr


# --------------------------------------------------------------------------- hands ab, spectrum


def test_ab_toggles_steps_and_reports(live, port):
    status = invoke("ab", "status", *port)
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout) == {"mode": "mix", "ref": "REF Roses", "refs": ["REF Roses", "REF Hedon"]}
    toggled = json.loads(invoke("ab", "toggle", *port).stdout)
    assert toggled == {"mode": "ref", "ref": "REF Roses", "spectrum": None}
    roses = live.song.tracks[1]
    assert roses.solo and not roses.mute
    assert json.loads(invoke("ab", "next", *port).stdout) == {"mode": "ref", "ref": "REF Hedon", "spectrum": None}
    assert json.loads(invoke("ab", "toggle", *port).stdout)["mode"] == "mix"
    assert all(t.mute and not t.solo for t in live.song.tracks[1:])
    bad = invoke("ab", "sideways", *port)
    assert bad.exit_code == 2 and "use toggle, next or status" in bad.stdout


def test_ab_without_references_fails_with_the_naming_rule(port, live):
    with live.main_thread():
        for t in live.song.tracks[1:]:
            t.name = t.name.replace("REF ", "ref ")
    res = invoke("ab", "status", *port)
    assert res.exit_code == 1 and "no reference tracks: name them REF <name>" in res.stdout  # rich prints to stdout


def test_spectrum_adds_and_shows_the_master_spectrum(live, port):
    res = invoke("spectrum", "--show", *port)
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout) == {"spectrum": True}
    assert [d.class_name for d in live.song.master_track.devices] == ["SpectrumAnalyzer"]


# --------------------------------------------------------------------------- hands record, kit


def test_record_passes_its_options_to_the_recorder(monkeypatch, tmp_path):
    from zpkt.live import record

    calls = []

    def recorder(kind):
        def run(**kw):
            calls.append((kind, kw))
            return str(tmp_path / kw["filename"])

        return run

    monkeypatch.setattr(record, "record_arrangement", recorder("arrangement"))
    monkeypatch.setattr(record, "record_via_resampling", recorder("resampling"))
    out = tmp_path / "take.wav"
    res = invoke("record", "--beats", "16", "--output", str(out), "--arrangement", "--tail", "2")
    assert res.exit_code == 0 and f"Exported: {out}" in res.stdout.replace("\n", "")  # rich wraps long lines
    kind, kw = calls[-1]
    assert kind == "arrangement" and kw["filename"] == "take.wav" and kw["duration_beats"] == 16.0
    assert kw["output_dir"] == str(tmp_path) and kw["tail_beats"] == 2.0
    assert invoke("record", "--output", str(out)).exit_code == 0 and calls[-1][0] == "resampling"
    monkeypatch.setattr(record, "record_via_resampling", lambda **kw: None)
    failed = invoke("record", "--output", str(out))
    assert failed.exit_code == 1 and "Recording failed" in failed.stdout

    def refuses(**kw):
        raise RuntimeError("the arrangement is not empty")

    monkeypatch.setattr(record, "record_via_resampling", refuses)
    refused = invoke("record", "--output", str(out))
    assert refused.exit_code == 1 and "the arrangement is not empty" in refused.stdout


def test_kit_commands_print_json_and_stop_on_a_guard(monkeypatch, tmp_path, rig):
    from zpkt.live import probe_kit

    made = probe_kit.Kit(
        kit="c8x4", set="test_c8x4", src="test_src", keep=(8.0, 40.0), lead=8.0, pattern_beats=32.0, P=4
    )
    monkeypatch.setattr(probe_kit, "template", lambda client, *a: made)
    res = invoke("kit", "template", "c8x4", "test_src", "8", "40", "4")
    assert res.exit_code == 0 and json.loads(res.stdout)["set"] == "test_c8x4"
    seen = []
    monkeypatch.setattr(probe_kit, "render", lambda client, b, k, out: seen.append(out) or {"files": 4})
    assert json.loads(invoke("kit", "render", "test_b", "c8x4").stdout) == {"files": 4}
    assert seen == [rig.data_dir / "kit_out" / "test_b"]

    def guarded(*a):
        session.stop("kit: 1 dialog(s) open in Live")

    monkeypatch.setattr(probe_kit, "render", guarded)
    stopped = invoke("kit", "render", "test_b", "c8x4")
    assert stopped.exit_code == 1 and "1 dialog(s) open" in stopped.stdout


# --------------------------------------------------------------------------- hands rig


def test_rig_check_and_reset_report_and_exit_by_readiness(monkeypatch):
    from zpkt.live import rig

    health = rig.Health(live_running=True, lom=True, device="Yeti", playhead=True)
    monkeypatch.setattr(rig, "check", lambda play=True: health)
    ok = invoke("rig", "check")
    assert ok.exit_code == 0 and ok.stdout.strip() == "ready: Live answers, plays and has an audio device"
    assert json.loads(invoke("rig", "check", "--json").stdout)["needs"] == "nothing"
    sick = rig.Health(live_running=True, device="Yeti", problems=["no LOM"], needs="soft")
    monkeypatch.setattr(rig, "check", lambda play=True: sick)
    res = invoke("rig", "check")
    assert res.exit_code == 1 and res.stdout == "- no LOM\n`hands rig reset` would do a soft reset.\n"
    bad = invoke("rig", "reset", "--level", "hard")
    assert bad.exit_code == 2 and "--level is auto, soft or restart" in bad.stderr


def test_rig_output_reads_and_chooses_the_device(monkeypatch):
    from zpkt.live import rig

    asked = []
    monkeypatch.setattr(ui, "osa_file", lambda path, *args, timeout: asked.append(args) or "Yeti Stereo")
    assert invoke("rig", "output").stdout.strip() == "Yeti Stereo" and asked == [("read",)]
    monkeypatch.setattr(ui, "osa_file", lambda path, *args, timeout: "NO_LIVE")
    res = invoke("rig", "output", "Yeti")
    assert res.exit_code == 1 and "could not choose 'Yeti' (NO_LIVE)" in res.stderr
    monkeypatch.setattr(ui, "osa_file", lambda path, *args, timeout: "Yeti Stereo")
    monkeypatch.setattr(rig, "log_size", lambda: 0)
    monkeypatch.setattr(rig, "log_since", lambda since: "")
    monkeypatch.setattr(rig, "output_device", lambda log: "Yeti Stereo")
    assert invoke("rig", "output", "Yeti").stdout.strip() == "Live's output: Yeti Stereo"


# --------------------------------------------------------------------------- hands live reload


def test_live_reload_counts_down_opens_and_waits_for_the_set(monkeypatch, tmp_path, live, rig):
    import subprocess

    from zpkt.live import transport

    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: ran.append(argv) or subprocess.CompletedProcess(argv, 0))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(ui, "dialogs", lambda: 0)
    monkeypatch.setattr(ui, "front_title", lambda: "test_set")
    monkeypatch.setenv("ZPKT_LIVE_PORT", str(live.serve()))
    rig_cache = transport.config.rig
    rig_cache.cache_clear()
    res = invoke("live", "reload", str(tmp_path / "test_set.als"), "--seconds", "3")
    assert res.exit_code == 0, res.output
    assert res.stdout.strip() == "reloaded: test_set"
    assert ran[0][0] == "bash" and ran[0][1].endswith("macros/hammerspoon/scripts/rig-confirm.sh")
    assert ran[0][2:] == ["Reloading the Live set test_set", "3"]
    assert ran[1] == ["open", "-a", rig.live_app, str(tmp_path / "test_set.als")]
    monkeypatch.setattr(
        subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1 if argv[0] == "bash" else 0)
    )
    cancelled = invoke("live", "reload", str(tmp_path / "test_set.als"))
    assert cancelled.exit_code == 1 and "cancelled" in cancelled.stderr


# --------------------------------------------------------------------------- hands build, execute (the first design)


def test_build_prints_the_steps_and_runs_them_dry(tmp_path):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"name": "char", "bpm": 132}))
    res = invoke("build", "--config", str(path))
    assert res.exit_code == 0, res.output
    assert "Build: char" in res.stdout and "Dry run" in res.stdout
    missing = invoke("build", "--config", str(tmp_path / "none.json"))
    assert missing.exit_code == 1 and "Config file not found" in missing.stdout
    path.write_text("{")
    assert "Invalid config" in invoke("build", "--config", str(path)).stdout


def test_execute_runs_the_steps_against_live(tmp_path, live, port):
    path = tmp_path / "project.json"
    path.write_text(json.dumps({"name": "char", "bpm": 132}))
    res = invoke("execute", "--config", str(path), *port)
    assert res.exit_code == 0, res.output
    # the config's "bpm" is not a ProjectConfig field: the defaults run (140 BPM, one reference kick track)
    assert "[ 0/2] Set tempo to 140.0 BPM" in res.stdout and "Done — 3 steps completed." in res.stdout
    assert live.song.tempo == 140.0 and [t.name for t in live.song.tracks][-1] == "1-ref_kick"
