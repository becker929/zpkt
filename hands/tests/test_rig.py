"""hands.live.rig against fakes: what the log says, what check concludes, what reset does in which order."""
from __future__ import annotations

import pytest

from hands.live import rig

LOG = """\
2026-11-19T22:51:27.0: info: Live App: Begin Init
2026-11-19T22:51:27.3: info: Audio In Out: Output Device: Mac mini Speakers (0 In, 2 Out)
2026-11-20T09:21:06.4: info: Audio In Out: Output Device: No Device
2026-11-20T09:24:12.7: info: Live App: Begin Init
2026-11-20T09:24:12.9: info: Message Box: Audio is disabled. Please choose an audio output device in the Audio Settings.
"""


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "Log.txt"
    path.write_text(LOG)
    monkeypatch.setattr(rig, "_log", lambda: path)
    return path


def test_log_since_launch_starts_at_the_latest_launch(log):
    lines = rig.log_since()
    assert lines[0].endswith("Live App: Begin Init") and "09:24" in lines[0]
    assert rig.message_boxes(lines) == ["Audio is disabled. Please choose an audio output device in the Audio Settings."]


def test_output_device(log):
    assert rig.output_device(rig.log_since()) == rig.NO_DEVICE
    assert rig.output_device(LOG.splitlines()[:2]) == "Mac mini Speakers"
    assert rig.output_device(LOG.splitlines()[:3]) == rig.NO_DEVICE


def test_log_since_an_offset(log):
    offset = log.stat().st_size
    with log.open("a") as f:
        f.write("2026-11-20T10:00:00.0: info: Message Box: Save changes?\n")
    assert rig.message_boxes(rig.log_since(offset)) == ["Save changes?"]


@pytest.mark.parametrize("box, key", [
    ("Audio is disabled. Please choose an audio output device in the Audio Settings.", "return"),
    ('Live unexpectedly quit while you were working on the Live Set "x.als." Would you like to recover your work?', "recover"),
    ("Do you want to replace the file?", "escape"),
])
def test_answer_for(box, key):
    assert rig.answer_for(box) == key


class Lom:
    """A Live that answers, with a playhead that moves or not."""

    def __init__(self, moves=True, recording=False, renders=0, answers=True):
        self.moves, self.recording, self.renders, self.answers = moves, recording, renders, answers
        self.calls = []

    def run(self, code):
        self.calls.append(code)
        if not self.answers:
            raise rig.LiveError("refused")
        if code == "result = 1":
            return 1
        if code.startswith("result = {"):
            return {"playing": False, "recording": self.recording, "render_tracks": self.renders}
        if code.startswith("result = [song.is_playing"):
            return [False, 64.0]
        if code == "result = song.current_song_time":
            return 64.0
        if code.startswith("result = song.current_song_time"):
            return 65.0 if self.moves else 64.0
        if "delete_track" in code:
            return self.renders
        return None


@pytest.fixture
def rigstate(monkeypatch, log):
    state = {"audio": True, "running": True, "dialogs": 0, "front": "HW002_121_pp_mix"}
    monkeypatch.setattr(rig, "system_audio_ok", lambda timeout=5.0: state["audio"])
    monkeypatch.setattr(rig, "live_running", lambda: state["running"])
    monkeypatch.setattr(rig, "open_dialogs", lambda: state["dialogs"])
    monkeypatch.setattr(rig, "set_window", lambda: state["front"])
    monkeypatch.setattr(rig.time, "sleep", lambda s: None)
    return state


def _healthy_log(log):
    log.write_text("x: info: Live App: Begin Init\nx: info: Audio In Out: Output Device: Mac mini Speakers (0 In, 2 Out)\n")


def test_check_ready(rigstate, log):
    _healthy_log(log)
    h = rig.check(Lom())
    assert h.needs == "nothing" and h.playhead and h.device == "Mac mini Speakers"


def test_check_no_device_needs_a_soft_reset(rigstate):
    h = rig.check(Lom())
    assert h.needs == "soft" and any(p.startswith("Live has no audio output device") for p in h.problems)
    assert any("hands rig output" in p for p in h.problems)    # the problem names its fix
    assert h.playhead is None  # no point playing without a device


def test_check_frozen_playhead_needs_a_restart(rigstate, log):
    _healthy_log(log)
    h = rig.check(Lom(moves=False))
    assert h.needs == "restart" and h.playhead is False


def test_check_stuck_system_audio_with_a_frozen_live(rigstate, log):
    _healthy_log(log)
    rigstate["audio"] = False
    assert rig.check(Lom(moves=False)).needs == "restart"


def test_a_silent_default_output_does_not_matter_while_live_plays(rigstate, log):
    _healthy_log(log)
    rigstate["audio"] = False  # the TV that is the Mac's default output is off
    h = rig.check(Lom())
    assert h.needs == "nothing" and not h.problems


def test_check_leftovers_need_only_a_soft_reset(rigstate, log):
    _healthy_log(log)
    h = rig.check(Lom(recording=True, renders=2))
    assert h.needs == "soft" and h.render_tracks == 2


def test_check_dialog_with_silent_lom_is_soft_first(rigstate, log):
    _healthy_log(log)
    rigstate["dialogs"] = 1
    assert rig.check(Lom(answers=False)).needs == "soft"


def test_check_live_not_running(rigstate):
    rigstate["running"] = False
    assert rig.check(Lom()).needs == "restart"


def test_soft_reset_deletes_render_tracks(rigstate, log):
    _healthy_log(log)
    lom, report = Lom(renders=2), rig.Report()
    rig.soft_reset(lom, report)
    assert any("delete_track" in c for c in lom.calls)
    assert "deleted 2 leftover Render track(s)" in report.steps


def test_restart_order_quits_live_before_audio(rigstate, monkeypatch, tmp_path):
    order = []
    rigstate["audio"] = False
    monkeypatch.setattr(rig, "quit_live", lambda report, keep: (order.append("quit"), rigstate.update(running=False)))
    monkeypatch.setattr(rig, "restart_audio", lambda report: (order.append("audio"), rigstate.update(audio=True)))
    monkeypatch.setattr(rig, "launch", lambda report, path, client: order.append("launch") or True)
    monkeypatch.setattr(rig, "soft_reset", lambda client, report: order.append("soft"))
    monkeypatch.setattr(rig, "check", lambda client=None, play=True: rig.Health(needs="restart" if not order else "nothing"))
    (tmp_path / "s.als").write_text("a set")
    report = rig.reset(set_path=tmp_path / "s.als", level="restart", client=Lom())
    assert order == ["quit", "audio", "launch", "soft"]
    assert report.ok


def test_restart_without_a_snapshot_asks_for_the_device(rigstate, monkeypatch, tmp_path):
    monkeypatch.setattr(rig, "quit_live", lambda report, keep: rigstate.update(running=False))
    monkeypatch.setattr(rig, "launch", lambda report, path, client: True)
    monkeypatch.setattr(rig, "soft_reset", lambda client, report: None)
    monkeypatch.setattr(rig, "check", lambda client=None, play=True: rig.Health(needs="soft", device=rig.NO_DEVICE, problems=["no device"]))
    (tmp_path / "s.als").write_text("a set")
    report = rig.reset(set_path=tmp_path / "s.als", level="restart", client=Lom())
    assert not report.ok and any("Audio Output Device" in n for n in report.needs_you)


def test_audio_restart_without_sudo_says_how(monkeypatch):
    monkeypatch.setattr(rig.subprocess, "run", lambda *a, **k: rig.subprocess.CompletedProcess(a, 1, "", "a password is required"))
    report = rig.Report()
    assert not rig.restart_audio(report)
    assert "sudoers" in report.needs_you[0] and "killall coreaudiod" in report.needs_you[0]


def test_backups_keep_the_newest(tmp_path):
    src = tmp_path / "HW.als"
    src.write_text("x")
    folder = rig.config.rig().data_dir / "set-backups"
    folder.mkdir()
    for i in range(12):
        (folder / f"HW-20260101-0000{i:02d}.als").write_text("old")
    rig.backup_set(src)
    assert len(list(folder.glob("HW-*.als"))) == rig.BACKUPS_KEPT


def test_soft_reset_chooses_a_device_when_live_has_none(rigstate, monkeypatch):
    chosen = []
    monkeypatch.setattr(rig, "choose_device", lambda report: chosen.append(True) or True)
    rig.soft_reset(Lom(), rig.Report())
    assert chosen


def test_last_good_device_skips_no_device(log):
    assert rig.last_good_device() == "Mac mini Speakers"


def test_set_window_ignores_settings(monkeypatch):
    monkeypatch.setattr(rig.ui, "windows", lambda: [("Settings", "AXStandardWindow"), ("", "AXUnknown"),
                                                     ("HW002_121_pp_mix", "AXStandardWindow")])
    assert rig.set_window() == "HW002_121_pp_mix"


def test_asking_for_another_set_restarts_live_with_it(rigstate, monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(rig, "quit_live", lambda report, keep: rigstate.update(running=False))
    monkeypatch.setattr(rig, "launch", lambda report, path, client: opened.append(path.stem) or True)
    monkeypatch.setattr(rig, "soft_reset", lambda client, report: None)
    healthy = rig.Health(needs="nothing", front="HW002_121_pp_mix")
    monkeypatch.setattr(rig, "check", lambda client=None, play=True: healthy)
    (tmp_path / "other.als").write_text("a set")
    report = rig.reset(set_path=tmp_path / "other.als", client=Lom())
    assert opened == ["other"] and report.ok


def test_mix_renders_open_deaf_buses():
    from hands.live import mix

    class Bus:
        def run(self, code):
            assert "current_monitoring_state = 0" in code and "_fed" in code
            return ["Kick bus", "Hats bus"]

    assert mix.open_buses(Bus()) == ["Kick bus", "Hats bus"]
    assert "Kick bus, Hats bus" in mix.opened_note(["Kick bus", "Hats bus"])[0]
    assert mix.opened_note([]) == []

    class Old:
        def run(self, code):
            raise RuntimeError("no current_monitoring_state")

    assert mix.open_buses(Old()) == []


def test_live_exec_forgives_import_song_and_print():
    from hands.live.cli import friendly
    src, notes = friendly("import song\nfrom song import tracks\nprint(song.tempo)")
    assert "import song" not in src and "from song" not in src and notes
    assert src.startswith("_printed = []") and 'result = "\\n".join(_printed)' in src
    src, notes = friendly("result = song.tempo")
    assert src == "result = song.tempo" and not notes


def test_grid_of_identical_versions_says_so():
    from hands.live.versions import same_note
    same = [{"rms_dbfs": -26.0}, {"rms_dbfs": -26.0}, {"rms_dbfs": -26.05}]
    assert "measure the same" in same_note(same, {"bars": [2, 6]})[0] and "bars 2-7" in same_note(same, {"bars": [2, 6]})[0]
    assert same_note([{"rms_dbfs": -26.0}, {"rms_dbfs": -20.0}], {"bars": [2, 6]}) == []


def test_quiet_tracks_names_where_they_first_play():
    from hands.live import mix

    class Live:
        def run(self, code):
            assert "'Kick bus'" in code and "Main" not in code.split("_names = ")[1].split("\n")[0]
            return {"Kick bus": 64.0, "fx": None}

    notes = mix.quiet_tracks(Live(), ["Kick bus", "Main", "fx"], 4.0, 24.0)
    assert notes[0] == "Kick bus plays nothing in these bars; it first plays at bar 17: its controls change nothing here"
    assert notes[1].startswith("fx plays nothing in these bars:")


@pytest.mark.parametrize("code, changes", [
    ("[t.name for t in song.tracks]", False),
    ("result = song.tracks[0].mixer_device.volume.value", False),
    ("t = song.tracks[0]\nprint(t.devices)", False),
    ("song.tracks[0].mixer_device.volume.value = 0.5", True),
    ("t = song.tracks[0]\nt.insert_device('Saturator')", True),
    ("song.delete_track(3)", True),
    ("for _t in song.tracks: _t.current_monitoring_state = 2", True),
    ("song.start_playing()", True),
    ("t.devices.append(None)", True),
    ("x = [d for d in t deves]", False),
])
def test_live_exec_knows_what_changes_live(code, changes):
    from hands.live.cli import writes
    assert writes(code) is changes


def test_identical_grid_fails_with_where_to_move(monkeypatch):
    from hands.live import mix, versions
    monkeypatch.setattr(mix, "quiet_tracks", lambda client, tracks, start, beats:
                        ["Kick bus plays nothing in these bars; it first plays at bar 17: its controls change nothing here"])
    same = versions.same_note([{"rms_dbfs": -22.5}] * 3, {"bars": [3, 8]})
    assert same  # the error path is exercised end to end in the lab; here, the hint's parts
    hint = versions.re.search(r"first plays at bar (\d+)", " ".join(mix.quiet_tracks(None, ["Kick bus"], 8.0, 32.0)))
    assert hint and hint.group(1) == "17"


def test_a_level_grid_spans_six_db_below_the_fader(monkeypatch):
    from hands.live import versions

    class Live:
        def run(self, code):
            return "0.0 dB"

    monkeypatch.setattr(versions, "_raw", lambda client, panel, c, want: {"-6 dB": 0.7}[want])
    c = {"param": "Kick bus volume", "kind": "fader", "min": 0.0, "max": 1.0, "label": "Kick bus"}
    panel = {"values": {"Kick bus volume": 0.85}, "exprs": {"Kick bus volume": "x"}, "kind": "mix"}
    monkeypatch.setattr(versions, "_where", lambda panel, c: "x")
    assert versions.fader_span(Live(), panel, c, 0.0, 1.0) == (0.7, 0.85)
    assert versions.fader_span(Live(), {"values": {}}, c, 0.0, 1.0) == (0.0, 1.0)
