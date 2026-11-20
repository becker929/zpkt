"""Put Live and macOS audio back into a working state, with nobody at the Mac.

`check` looks at every part of the rig that can go wrong between renders, and `reset` repairs what
it finds, mildest step first:

- **soft**: answer Live's dialogs, choose an audio output device if Live has none (in its Settings
  window, which Live 12 exposes to Accessibility), stop the transport, turn recording off, delete
  leftover "Render" tracks (the temporary Resampling tracks a render adds and removes; a crash leaves them).
- **restart**: quit Live (saving the set first), restart macOS audio if it is stuck, open the set
  again, answer the start-up messages, then do the soft step.

What the reset learned the hard way (2026-11-20):
- After macOS audio restarts under a running Live, Live switches its output to "No Device" and keeps
  that in Preferences.cfg (written only when Live quits, so a copy of it taken while Live runs is
  stale). So Live is quit *before* audio restarts, and when Live has no device the soft step
  chooses one in Settings (the last that worked, else the Mac's speakers).
- Live draws its own dialogs, so they cannot be read or pressed through Accessibility. Its log names
  the message boxes it shows; Return answers an informational one ("Audio is disabled...") and
  recovers unsaved work at "Would you like to recover your work?", Escape cancels a question, and
  Command-D is "Don't Save" in the quit prompt. A Live waiting at
  "Audio is disabled" does not load the set (the LOM stays silent) until it is answered.
- A mix panel changes Live without saving the set, so unsaved changes can be the user's mix. A
  restart therefore saves the set first (after copying the file to `set-backups/`), unless asked
  to discard. Live deletes CrashDetection.cfg on a clean exit; a set that cannot be saved or quit
  cleanly is killed, and the reset accepts Live's offer to recover it on the next start.
- The Settings window is a window like the set's, so the set's name is read from the windows list,
  not from the front window.
- Restarting macOS audio needs root. It runs as `sudo -n`, so it works only once the user has
  allowed that one command without a password (SUDOERS_HINT); otherwise the reset says so.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import wave
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from hands import config
from hands.live import ui
from hands.live.transport import LiveError, LiveClient, McpTransport

AUDIO_RESTART = ["sudo", "-n", "/usr/bin/killall", "coreaudiod"]
SUDOERS_HINT = ("restarting macOS audio needs your password once: run `sudo visudo -f /etc/sudoers.d/zpkt-audio` "
                f"and add the line `{os.environ.get('USER', 'you')} ALL=(root) NOPASSWD: /usr/bin/killall coreaudiod`, "
                "or run `sudo killall coreaudiod` yourself")
NO_DEVICE = "No Device"
LAUNCH_MARK = "Live App: Begin Init"
_BOX = re.compile(r"Message Box: (.*)")
_DEVICE = re.compile(r"Audio In Out: Output Device: (.*?)(?: \(\d+ In, \d+ Out\))?$")
BACKUPS_KEPT = 10


# ---------------------------------------------------------------- what Live's log says


def _log() -> Path | None:
    return config.rig().live_log


def log_size() -> int:
    log = _log()
    try:
        return log.stat().st_size if log else 0
    except FileNotFoundError:
        return 0


def log_since(offset: int | None = None) -> list[str]:
    """Log lines after `offset` (bytes), or since Live's latest launch when None."""
    log = _log()
    if not log or not log.exists():
        return []
    with log.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        start = offset if offset is not None else max(0, size - (4 << 20))
        f.seek(min(start, size))
        lines = f.read().decode("utf-8", "replace").splitlines()
    if offset is None:
        marks = [i for i, line in enumerate(lines) if LAUNCH_MARK in line]
        lines = lines[marks[-1]:] if marks else lines
    return lines


def message_boxes(lines: list[str]) -> list[str]:
    return [m.group(1).strip() for line in lines if (m := _BOX.search(line))]


def output_device(lines: list[str]) -> str | None:
    """The output device Live last opened in these lines; NO_DEVICE when it has none."""
    device = None
    for line in lines:
        if (m := _DEVICE.search(line)):
            device = m.group(1).strip()
        elif "Message Box: Audio is disabled" in line:
            device = NO_DEVICE
    return device


def answer_for(box: str) -> str:
    """The key that answers a message box Live drew: 'return' for information, 'escape' for a question
    (cancel or no), 'recover' for Live's offer to recover unsaved work."""
    if "recover your work" in box:
        return "recover"
    return "escape" if box.rstrip().endswith("?") else "return"


# ---------------------------------------------------------------- the pieces of the rig


def live_running() -> bool:
    return subprocess.run(["pgrep", "-x", "Live"], capture_output=True).returncode == 0


def system_audio_ok(timeout: float = 5.0) -> bool:
    """Can macOS play a sound through its default output? Plays a fifth of a second of silence. A stuck
    coreaudiod makes afplay fail (AudioQueueStart 'what') or hang; so does a default output that is a TV
    switched off, which is why this alone never calls for a restart."""
    path = Path(tempfile.gettempdir()) / "zpkt-silence.wav"
    if not path.exists():
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            w.writeframes(b"\0\0" * 8820)
    try:
        return subprocess.run(["afplay", str(path)], capture_output=True, timeout=timeout).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def lom_ok(client: McpTransport) -> bool:
    try:
        return client.run("result = 1") == 1
    except (LiveError, OSError):
        return False


def playhead_moves(client: McpTransport, wait_s: float = 1.0) -> bool | None:
    """Play for a moment from where the playhead is, and put it back. None if Live is already playing
    (then it was not this check's to stop) or does not answer."""
    try:
        state = client.run("result = [song.is_playing, song.current_song_time]")
        if state[0]:
            return None
        client.run("song.start_playing()")  # from the start marker, not from the playhead
        time.sleep(0.3)
        first = client.run("result = song.current_song_time")
        time.sleep(wait_s)
        after = client.run("result = song.current_song_time\nsong.stop_playing()")
        client.run(f"song.current_song_time = {float(state[1])!r}")
        return after > first
    except (LiveError, OSError, TypeError, IndexError):
        return None


def press(key: str) -> None:
    """Bring Live to the front and press a key: 'return', 'escape' or 'dont-save' (Command-D)."""
    stroke = {"return": "key code 36", "escape": "key code 53",
              "dont-save": 'keystroke "d" using command down'}[key]
    ui.osa(f'tell application "{config.rig().live_app}" to activate\ndelay 0.4\n'
           f'tell application "System Events" to {stroke}', timeout=15)
    time.sleep(0.8)


NOT_SETS = {"", "Settings"}


def set_window() -> str | None:
    """The open set's name: the title of Live's main window, whichever window is in front."""
    try:
        names = [n for n, role in ui.windows() if role == "AXStandardWindow" and n not in NOT_SETS]
    except ui.UiError:
        return None
    return names[0] if names else None


def open_dialogs() -> int:
    try:
        return ui.dialogs()
    except ui.UiError:
        return 0


DEVICE_SCRIPT = Path(__file__).with_name("audio_device.applescript")
FALLBACK_DEVICES = ("Mac mini Speakers", "MacBook", "Built-in", "Use System Device")


def last_good_device() -> str | None:
    """The last output device Live opened that was a real one, from the end of its log."""
    good = None
    for line in log_since(max(0, log_size() - (4 << 20))):
        if (m := _DEVICE.search(line)) and m.group(1).strip() != NO_DEVICE:
            good = m.group(1).strip()
    return good


def choose_device(report: Report) -> bool:
    """Pick Live's audio output device in its Settings window: the last one that worked, else the Mac's own
    speakers, else whatever macOS uses."""
    names = [n for n in dict.fromkeys([last_good_device(), *FALLBACK_DEVICES]) if n]
    since = log_size()
    try:
        chosen = ui.osa_file(DEVICE_SCRIPT, "set", *names, timeout=40)
    except ui.UiError as exc:
        report.step(f"could not open Live's audio settings ({exc})")
        return False
    if chosen in ("NONE", "NO_LIVE", "NO_SETTINGS", "NO_POPUP"):
        report.step(f"could not choose an audio device in Live's settings ({chosen})")
        return False
    for _ in range(20):
        device = output_device(log_since(since))
        if device and device != NO_DEVICE:
            report.step(f"set Live's audio output to {device}")
            return True
        time.sleep(0.5)
    report.step(f"chose {chosen} in Live's settings, but Live did not open it")
    return False


# ---------------------------------------------------------------- check


@dataclass
class Health:
    live_running: bool = False
    lom: bool = False
    front: str | None = None
    dialogs: int = 0
    last_message: str | None = None
    device: str | None = None
    system_audio: bool = True
    playhead: bool | None = None
    playing: bool | None = None
    recording: bool | None = None
    render_tracks: int = 0
    problems: list[str] = field(default_factory=list)
    needs: str = "nothing"  # nothing | soft | restart

    def as_dict(self) -> dict:
        return asdict(self)


_STATE = """result = {
  "playing": song.is_playing,
  "recording": bool(song.record_mode or song.session_record or song.arrangement_overdub),
  "render_tracks": sum(1 for t in song.tracks if t.name == "Render" and not t.has_midi_input),
}"""


def check(client: McpTransport | None = None, *, play: bool = True) -> Health:
    """Look at every part of the rig, without changing anything (except a second of playback)."""
    client = client or LiveClient(retries=0, timeout=4)
    h = Health(system_audio=system_audio_ok(), live_running=live_running())
    if not h.live_running:
        if not h.system_audio:
            h.problems.append("macOS cannot play a sound")
        h.problems.append("Live is not running")
        h.needs = "restart"
        return h
    lines = log_since()
    boxes = message_boxes(lines)
    h.last_message = boxes[-1] if boxes else None
    h.device = output_device(lines)
    h.dialogs = open_dialogs()
    h.front = set_window()
    h.lom = lom_ok(client)
    if h.device == NO_DEVICE:
        h.problems.append("Live has no audio output device")
    if h.dialogs:
        h.problems.append(f"Live shows {h.dialogs} dialog(s)" + (f" (latest message: {h.last_message})" if h.last_message else ""))
    if not h.lom:
        h.problems.append("Live does not answer hands (its Remote Script is silent)")
    if h.lom:
        try:
            state = client.run(_STATE)
            h.playing, h.recording, h.render_tracks = state["playing"], state["recording"], state["render_tracks"]
        except (LiveError, OSError, KeyError, TypeError):
            pass
        if h.recording:
            h.problems.append("Live is recording")
        if h.render_tracks:
            h.problems.append(f"{h.render_tracks} leftover Render track(s) from an interrupted render")
        if play and h.device != NO_DEVICE and not h.dialogs:
            h.playhead = playhead_moves(client)
            if h.playhead is False:
                h.problems.append("Live's playhead does not move: its audio engine is not running")
    # macOS failing to play through its default output only matters when Live is not heard playing either:
    # the default may be a TV that is off, while Live plays through the Mac's speakers.
    if not h.system_audio and h.playhead is not True:
        h.problems.append("macOS cannot play a sound either (its audio may be stuck)")
    hard = h.playhead is False or (not h.lom and not h.dialogs) or (not h.system_audio and h.playhead is not True and not h.dialogs)
    h.needs = "restart" if hard else ("soft" if h.problems else "nothing")
    return h


# ---------------------------------------------------------------- the steps of a reset


@dataclass
class Report:
    ok: bool = False
    set: str | None = None
    steps: list[str] = field(default_factory=list)
    needs_you: list[str] = field(default_factory=list)
    backup: str | None = None
    health: dict | None = None

    def step(self, text: str) -> None:
        self.steps.append(text)
        print(f"· {text}", flush=True)


def answer_dialogs(report: Report, since: int | None = None, rounds: int = 4) -> None:
    """Press the safe answer on every dialog: Accessibility for the ones macOS draws, a key for Live's own."""
    for _ in range(rounds):
        if not open_dialogs():
            return
        try:
            out = ui.reap_modals(reap=True)
            if not out.startswith("OPEN"):
                report.step(f"closed a dialog ({out.splitlines()[0][:80]})")
                continue
        except ui.UiError:
            pass
        boxes = message_boxes(log_since(since))
        box = boxes[-1] if boxes else ""
        key = answer_for(box) if box else "escape"
        press("return" if key == "recover" else key)
        report.step(f"answered Live's message with {key}" + (f": {box[:90]}" if box else ""))
    if open_dialogs():
        report.needs_you.append("a dialog in Live would not close; answer it in Live")


def soft_reset(client: McpTransport, report: Report) -> None:
    answer_dialogs(report)
    if live_running() and output_device(log_since()) == NO_DEVICE:
        choose_device(report)
    if not lom_ok(client):
        return
    gone = client.run("""song.stop_playing()
song.record_mode = False
song.session_record = False
song.arrangement_overdub = False
_gone = 0
for _i in reversed(range(len(song.tracks))):
    _t = song.tracks[_i]
    if _t.name == "Render" and not _t.has_midi_input:
        song.delete_track(_i)
        _gone += 1
result = _gone""")
    report.step("stopped the transport and turned recording off")
    if gone:
        report.step(f"deleted {gone} leftover Render track(s)")


def _set_path(name: str | None, path: str | None) -> Path | None:
    if path:
        return Path(path).expanduser()
    if name:
        p = config.rig().set_path(name)
        return p if p.exists() else None
    return None


def _last_set_file() -> Path:
    return config.rig().data_dir / "rig_last_set.json"


def remember_set(path: Path) -> None:
    f = _last_set_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"set": str(path)}))


def last_set() -> Path | None:
    try:
        p = Path(json.loads(_last_set_file().read_text())["set"])
        return p if p.exists() else None
    except (FileNotFoundError, ValueError, KeyError):
        return None


def backup_set(path: Path) -> Path:
    """Copy a set file to <data_dir>/set-backups/ before a reset saves over it; keep the newest few."""
    folder = config.rig().data_dir / "set-backups"
    folder.mkdir(parents=True, exist_ok=True)
    dst = folder / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}.als"
    shutil.copy2(path, dst)
    for old in sorted(folder.glob(f"{path.stem}-*.als"))[:-BACKUPS_KEPT]:
        old.unlink()
    return dst


def _unsaved() -> bool:
    try:
        return ui.menu_enabled("File", "Save Live Set")
    except ui.UiError:
        return False


def quit_live(report: Report, keep: bool, timeout_s: float = 45) -> None:
    """Quit Live. With keep, unsaved changes are saved first (the file is copied to set-backups/ before),
    or, for a set hands cannot back up, left to Live's own recovery by stopping Live instead of quitting.
    The quit prompt is answered with Don't Save; a Live that will not go is stopped."""
    if not live_running():
        return
    answer_dialogs(report)
    front = set_window()
    unsaved = keep and not open_dialogs() and _unsaved()
    path = config.rig().set_path(front) if front else None
    force = False
    if unsaved and path and path.exists():
        report.backup = str(backup_set(path))
        before = path.stat().st_mtime_ns
        try:
            if ui.menu("File", "Save Live Set"):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline and path.stat().st_mtime_ns == before:
                    time.sleep(0.3)
                report.step(f"saved {front} (the version before is in {report.backup})")
        except (ui.UiError, OSError) as exc:
            report.step(f"could not save {front} ({exc}); Live will offer to recover it")
            force = True
    elif unsaved:
        report.step(f"{front or 'the open set'} has unsaved changes hands cannot back up; Live will offer to recover them")
        force = True
    if not force:
        try:
            subprocess.Popen(["osascript", "-e", f'tell application "{config.rig().live_app}" to quit'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
        deadline = time.monotonic() + timeout_s
        pressed = False
        while live_running() and time.monotonic() < deadline:
            time.sleep(1)
            if not pressed and open_dialogs():
                press("dont-save")  # saved by now, or the caller asked to discard
                pressed = True
                report.step("answered Live's save prompt with Don't Save")
    if live_running():
        for pid in subprocess.run(["pgrep", "-x", "Live"], capture_output=True, text=True).stdout.split():
            os.kill(int(pid), signal.SIGKILL)
        time.sleep(2)
        prefs = config.rig().live_prefs_dir
        if not keep and prefs and (prefs / "CrashDetection.cfg").exists():
            (prefs / "CrashDetection.cfg").unlink()  # no recovery offer for work the caller chose to discard
        report.step("stopped Live" + ("" if force else " (it would not quit)"))
    else:
        report.step("quit Live")


def restart_audio(report: Report) -> bool:
    run = subprocess.run(AUDIO_RESTART, capture_output=True, text=True)
    if run.returncode:
        report.needs_you.append(SUDOERS_HINT)
        report.step("could not restart macOS audio without a password")
        return False
    for _ in range(20):
        time.sleep(0.5)
        if system_audio_ok():
            report.step("restarted macOS audio")
            return True
    report.needs_you.append("macOS audio still does not play after a restart; restart the Mac")
    return False


def launch(report: Report, set_path: Path | None, client: McpTransport, timeout_s: float = 180) -> bool:
    """Open Live (with the set), answer its start-up messages, and wait until hands can drive it."""
    since = log_size()
    argv = ["open", "-a", config.rig().live_app] + ([str(set_path)] if set_path else [])
    for k in range(5):
        if subprocess.run(argv, capture_output=True).returncode == 0:
            break
        time.sleep(3 + 2 * k)  # LaunchServices lags a quit
    report.step(f"opened Live{f' with {set_path.stem}' if set_path else ''}")
    answered = 0
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        time.sleep(2)
        boxes = message_boxes(log_since(since))
        if len(boxes) > answered and open_dialogs():
            key = answer_for(boxes[answered])
            press("return" if key == "recover" else key)
            report.step(f"answered Live's message with {key}: {boxes[answered][:90]}")
            answered += 1
            continue
        if lom_ok(client) and (not set_path or set_window() == set_path.stem):
            if open_dialogs():
                answer_dialogs(report, since)
            return True
    report.needs_you.append(f"Live did not come back in {timeout_s:g} s; look at Live")
    return False


def reset(*, set_path: Path | None = None, level: str = "auto", keep: bool = True,
          client: McpTransport | None = None) -> Report:
    """Bring the rig back. level: auto (the mildest step that fixes what check finds), soft or restart."""
    client = client or LiveClient(retries=0, timeout=5)
    report = Report()
    before = check(client, play=False) if level == "auto" else None
    front = before.front if before else set_window()
    asked = set_path
    set_path = set_path or _set_path(front, None) or last_set()
    report.set = set_path.stem if set_path else None
    need = level if level != "auto" else before.needs
    if asked and front != asked.stem and need != "restart":
        report.step(f"{front or 'no set'} is open, not {asked.stem}: Live restarts with it")
        need = "restart"
    if need == "soft":
        soft_reset(client, report)
        after = check(client)
        if after.needs == "restart":
            need = "restart"  # the playhead check found what the quick look could not
        report.health = after.as_dict()
    if need == "restart":
        quit_live(report, keep)
        if not system_audio_ok():
            restart_audio(report)
        if launch(report, set_path, client):
            soft_reset(client, report)
        report.health = check(client).as_dict()
        if report.health["device"] == NO_DEVICE:
            report.needs_you.append("Live has no audio output device: choose one in Live > Settings > Audio "
                                    "(Audio Output Device)")
    elif need == "nothing":
        report.step("nothing to fix")
        report.health = check(client).as_dict()
    report.ok = bool(report.health) and report.health["needs"] == "nothing"
    if report.ok and set_path:
        remember_set(set_path)
    return report
