"""Live sessions: the guard every step runs, and opening, saving, restarting Live.

Before and after each Live step, `check` makes sure Live is where the step expects it: no dialog
open, one of our sets in front (config.set_prefixes: anything else means someone else is using
Live), the expected set if one is named, and the LOM answering. A Guard means stop: never chain the
next step past a surprise (docs/probe-packing-findings.md, section 7).

Sets live in config.sets_dir and are named without ".als".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

from zpkt.live import config, ui
from zpkt.live.transport import LiveError, McpTransport

_LOG_TAIL_BYTES = 4 << 20  # Log.txt grows by megabytes a day; the last connections are at its end


class Guard(RuntimeError):
    """Live is not in the state a step expects. Stop; do not continue the run."""


def stop(message: str) -> NoReturn:
    """Stop the run: raise Guard with what was found."""
    raise Guard(message)


def _front() -> str | None:
    """The front set's name, or None while Live shows no window (launching, loading)."""
    try:
        return ui.front_title()
    except ui.UiError:
        return None


def _answers(client: McpTransport) -> bool:
    try:
        client.run("result = 1")
        return True
    except LiveError:
        return False


def tell_opened(client: object, name: str) -> None:
    """Tell a transport that keeps track of the open set (the app's, zpkt.live.app_transport) that `name` is open
    now. The app holds calls that name no set to the set it last saw open, so it has to hear of this one. A direct
    connection has nothing to tell."""
    told = getattr(client, "set_opened", None)
    if callable(told):
        told(name)


def _loaded_file() -> Path:
    return config.rig().data_dir / "live_loaded.json"


def _remember(name: str) -> None:
    """Note the set file's mtime as Live now holds it (just opened, or just saved by Live).

    Kept on disk, not in memory: each `hands` command is its own process, and the next one is the
    one that saves over the set.
    """
    record = _loaded_file()
    try:
        seen = json.loads(record.read_text())
    except (FileNotFoundError, ValueError):
        seen = {}
    seen[name] = config.rig().set_path(name).stat().st_mtime_ns
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(seen, indent=1))


def rewritten_on_disk(name: str) -> bool:
    """Has sets_dir/<name>.als changed since Live loaded or saved it? False when unknown (a set
    opened by hand, or before this record existed)."""
    try:
        known = json.loads(_loaded_file().read_text()).get(name)
        return known is not None and config.rig().set_path(name).stat().st_mtime_ns != known
    except (FileNotFoundError, ValueError):
        return False


def _save_front(front: str, where: str) -> None:
    """Save the front set before leaving it, unless its file was rewritten on disk after Live
    loaded it (a batch written offline over it): saving would put Live's stale copy over the new
    file. Then skip the save if Live has nothing unsaved, and stop if it has (one side must lose)."""
    if not rewritten_on_disk(front):
        save(front)
        return
    if ui.menu_enabled("File", "Save Live Set"):
        stop(
            f"{where}: {front}.als changed on disk since Live loaded it and Live has unsaved changes; "
            "saving would overwrite the file, not saving would leave Live's prompt open"
        )


def check(client: McpTransport, where: str, *, expect_front: str | None = None, ours: bool = True) -> str:
    """Pre/post-flight for a Live step; returns the front set's name or raises Guard.

    `where` names the step in the message. With ours=False any set may be in front (a desk
    session); the other checks still apply.
    """
    try:
        n = ui.dialogs()
        front = ui.front_title()
    except ui.UiError as exc:
        stop(f"{where}: cannot read Live's windows ({exc})")
    if n:
        stop(f"{where}: {n} dialog(s) open in Live")
    if expect_front and front != expect_front:
        stop(f"{where}: front set is {front!r}, expected {expect_front!r}")
    if ours and not config.rig().is_ours(front):
        stop(f"{where}: front set {front!r} is not one of ours; someone else may be using Live")
    try:
        client.run("result = 1")
    except LiveError as exc:
        stop(f"{where}: Live does not answer LOM: {exc}")
    return front


def open_set(client: McpTransport, name: str, *, save_current: bool = True, timeout_s: float = 120.0) -> float:
    """Open sets_dir/<name>.als and wait until it is in front and the LOM answers; return seconds.

    The set in front is saved first (if it is one of the files in sets_dir), so Live never asks
    about unsaved changes; not if its file was rewritten on disk after Live loaded it (_save_front). Live does not reload a set that is already open, so asking for the front
    set again would keep its old state (for a batch rewritten offline: render the old batch); that
    is a Guard. Raises Guard if the window or the LOM does not come up in time.
    """
    rig = config.rig()
    path = rig.set_path(name)
    if not path.exists():
        stop(f"open: no set {path}")
    front = _front()
    if front == name:
        tell_opened(client, name)
        stop(f"open: {name} is already open, and Live would not reload it; open another set first")
    if save_current and front and rig.set_path(front).exists():
        _save_front(front, "open")
    t0 = time.monotonic()
    opened = subprocess.run(["open", "-a", rig.live_app, str(path)], capture_output=True, text=True)
    if opened.returncode:
        stop(f"open: `open` failed: {opened.stderr.strip()[-200:]}")
    deadline = t0 + timeout_s
    while _front() != name:
        if time.monotonic() > deadline:
            stop(f"open: Live did not show {name} in {timeout_s:g} s; front window is {_front()!r}")
        if not save_current:
            _discard_prompt()
        time.sleep(0.1)
    while not _answers(client):
        if time.monotonic() > deadline:
            stop(f"open: {name} is in front but the LOM did not answer in {timeout_s:g} s")
        time.sleep(0.1)
    seconds = time.monotonic() - t0
    _remember(name)
    tell_opened(client, name)
    return seconds


def _discard_prompt() -> bool:
    """Answer Live's "save changes?" prompt with Don't Save (Command-D), if one is open. True if it pressed.

    Live draws that prompt itself, so it has no buttons to press through accessibility; Command-D is its Don't Save.
    Only for a caller that asked to discard the set in front."""
    try:
        if not ui.dialogs():
            return False
        ui.osa(
            f'tell application "{config.rig().live_app}" to activate\ndelay 0.4\n'
            'tell application "System Events" to keystroke "d" using command down',
            timeout=15,
        )
    except ui.UiError:
        return False
    time.sleep(0.8)
    return True


def reopen(client: McpTransport, name: str | None = None, *, timeout_s: float = 180.0) -> float:
    """Open sets_dir/<name>.als (default: the set in front) from its file, discarding unsaved changes; return seconds.

    Live will not reload the set it has open, so a set already in front is first swapped for a new empty one
    (File > New Live Set, its prompt answered Don't Save). Another set in front is discarded the same way."""
    front = _front()
    name = (name or front or "").removesuffix(".als")
    if not name:
        stop("reopen: Live shows no set; name one")
    if not config.rig().set_path(name).exists():
        stop(f"reopen: no set {config.rig().set_path(name)}")
    t0 = time.monotonic()
    if front == name:
        if not ui.menu("File", "New Live Set"):
            stop("reopen: File > New Live Set stayed disabled")
        deadline = t0 + 60
        while _front() == name or _discard_prompt():
            if time.monotonic() > deadline:
                stop(f"reopen: Live still shows {name} (or a prompt) after New Live Set")
            time.sleep(0.2)
    open_set(client, name, save_current=False, timeout_s=max(timeout_s - (time.monotonic() - t0), 30.0))
    return time.monotonic() - t0


def save(name: str | None = None, *, timeout_s: float = 30.0) -> bool:
    """File > Save Live Set, then wait until the set's file is rewritten.

    `name` defaults to the front set and must be it; its file in sets_dir is watched. Returns
    False when there was nothing to save (Live greys the item out), True once the file changed;
    raises Guard if it never does.
    """
    front = _front()
    if front is None:
        stop("save: Live shows no set")
    name = name or front
    if name != front:
        stop(f"save: {name!r} is not the front set ({front!r})")
    path = config.rig().set_path(name)
    if not path.exists():
        stop(f"save: {name!r} is not a set in {path.parent}")
    before = path.stat().st_mtime_ns
    if not ui.menu_enabled("File", "Save Live Set"):
        return False
    if not ui.menu("File", "Save Live Set"):
        stop("save: File > Save Live Set stayed disabled")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if path.stat().st_mtime_ns != before:
                _remember(name)
                return True
        except FileNotFoundError:
            pass  # Live replaces the file, so it is missing for a moment
        time.sleep(0.05)
    if not ui.menu_enabled("File", "Save Live Set"):
        return False  # Live had nothing to save; the item greys out a moment after a save, so the click did nothing
    stop(f"save: {path.name} was not rewritten in {timeout_s:g} s")


def front_set() -> tuple[str, bool]:
    """The open set's name, and whether it is a guess: Live's window title, else (the window on another Space, full
    screen) the set hands last saw Live open or save, which each `hands live ...` command keeps on disk. Guard if
    there is neither."""
    try:
        if title := ui.front_title():
            return title, False
    except ui.UiError:
        pass
    try:
        seen = json.loads(_loaded_file().read_text())
    except (FileNotFoundError, ValueError):
        seen = {}
    if not seen:
        stop("Live shows no set, and hands has not seen one opened or saved")
    return max(seen, key=seen.get), True


CONFIRM = Path(__file__).resolve().parents[3] / "hands/macros/hammerspoon/scripts/rig-confirm.sh"  # in the repo


def reload_set(set_path: Path, *, live: McpTransport, save_first: bool = False, seconds: int = 10) -> None:
    """Reopen `set_path` in Live behind a countdown the person at the Mac can cancel (rig-confirm.sh), and wait until
    Live shows it and the LOM answers. For a set edited offline; with save_first, Live saves first (only when the
    file was not edited offline). `live` is the connection the caller hands in: it is asked "1" until Live answers.
    Guard if the countdown is cancelled or Live does not come back with the set."""
    if save_first and not ui.menu("File", "Save Live Set"):
        stop("could not save Live")
    if subprocess.run(["bash", str(CONFIRM), f"Reloading the Live set {set_path.stem}", str(seconds)]).returncode:
        stop("cancelled (or no countdown)")
    subprocess.run(["open", "-a", config.rig().live_app, str(set_path)], check=True)
    time.sleep(3)
    for _ in range(60):
        try:
            if ui.dialogs():
                time.sleep(2)  # the set may still be loading behind a progress window
                continue
            live.run("1")
            if ui.front_title() == set_path.stem:
                return
        except (LiveError, ui.UiError):
            pass
        time.sleep(2)
    if ui.dialogs():
        stop(
            "Live is showing a dialog, most likely about unsaved changes; answer it in Live, "
            "or save first (--save-first) when the file was not edited offline"
        )
    stop("Live did not show the set after the reload")


def copy_set(src: str, dst: str) -> Path:
    """Copy sets_dir/<src>.als to sets_dir/<dst>.als (replacing it) and return the new path."""
    rig = config.rig()
    return Path(shutil.copyfile(rig.set_path(src), rig.set_path(dst)))


def _running() -> bool:
    """Live's process exists, or LaunchServices still thinks so (it lags a quit, and `open`
    then fails with -600)."""
    if subprocess.run(["pgrep", "-x", "Live"], capture_output=True).returncode == 0:
        return True
    return ui.osa(f'application "{config.rig().live_app}" is running') == "true"


def launch(tries: int = 5) -> None:
    """`open -a` Live, retrying while LaunchServices still holds the instance that just quit."""
    for k in range(tries):
        opened = subprocess.run(["open", "-a", config.rig().live_app], capture_output=True, text=True)
        if opened.returncode == 0:
            return
        time.sleep(3 + 2 * k)
    stop(f"launch: open failed {tries} times: {opened.stderr.strip()[-200:]}")


def restart(client: McpTransport, *, timeout_s: float = 240.0) -> float:
    """Save the front set, quit Live, relaunch it and wait for the LOM; return the seconds it took.

    A fresh Live uses less memory: 1.5 GB against 4.5 GB after many loads (FINDINGS).
    """
    front = _front()
    if front and config.rig().set_path(front).exists():
        _save_front(front, "restart")
    if ui.dialogs():
        stop("restart: a dialog is open; quitting would stop at it")
    t0 = time.monotonic()
    ui.osa(f'tell application "{config.rig().live_app}" to quit', timeout=60)
    for _ in range(120):
        if not _running():
            break
        time.sleep(1)
    else:
        stop("restart: Live did not quit (a prompt may be open)")
    launch()
    while time.monotonic() - t0 < timeout_s:
        if _answers(client):
            return time.monotonic() - t0
        time.sleep(2)
    stop(f"restart: Live did not answer LOM {timeout_s:g} s after the relaunch")


def audio_clock_ok(client: McpTransport, wait_s: float = 1.2) -> bool:
    """Play for a moment: does the song position move? Live with no audio device keeps its clock
    frozen, and then every take is silent (the ableton-guide skill, section 0). Plays audio."""
    before = client.run("result = song.current_song_time\nsong.start_playing()")
    time.sleep(wait_s)
    after = client.run("result = song.current_song_time\nsong.stop_playing()")
    return after > before


def memory() -> dict[str, Any]:
    """The Mac's swap, compressed and free memory, and Live's resident and full footprint, in GB.

    Live's footprint (top's MEM) counts its compressed pages, which RSS misses under pressure.
    Live's figures are None when it is not running.
    """
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    page = os.sysconf("SC_PAGE_SIZE")  # vm_stat counts kernel pages

    def pages(label: str) -> float:
        line = next(line for line in vm.splitlines() if line.startswith(label))
        return int(line.split(":")[1].strip().rstrip(".")) * page / 2**30

    out = {
        "swap_used_gb": round(float(swap.split("used = ")[1].split("M")[0]) / 1024, 2),
        "compressed_gb": round(pages("Pages occupied by compressor"), 2),
        "free_gb": round(pages("Pages free"), 2),
        "live_rss_gb": None,
        "live_mem_gb": None,
        "live_compressed_gb": None,
    }
    pid = subprocess.run(["pgrep", "-x", "Live"], capture_output=True, text=True).stdout.split()
    if pid:
        rss_kb = int(subprocess.run(["ps", "-o", "rss=", "-p", pid[0]], capture_output=True, text=True).stdout)
        top = subprocess.run(
            ["top", "-l", "1", "-pid", pid[0], "-stats", "mem,cmprs"], capture_output=True, text=True
        ).stdout
        mem, cmprs = top.strip().splitlines()[-1].split()[:2]
        out.update(live_rss_gb=round(rss_kb / 2**20, 3), live_mem_gb=_gb(mem), live_compressed_gb=_gb(cmprs))
    return out


def _gb(top_value: str) -> float:
    """top's "1234M", "5G", "512K" or "0B" (a trailing + or - allowed) in GB."""
    v = top_value.rstrip("+-")
    return round(float(v[:-1]) / {"B": 2**30, "K": 2**20, "M": 1024, "G": 1}[v[-1]], 2)


def last_lom_connection(log: Path | None = None) -> datetime | None:
    """When something last connected to the AbletonLiveMCP Remote Script, from Live's Log.txt."""
    log = log or config.rig().live_log
    if log is None or not log.exists():
        raise FileNotFoundError(f"no Live log at {log}; set live_prefs_dir in the rig config")
    with log.open("rb") as f:
        f.seek(max(0, log.stat().st_size - _LOG_TAIL_BYTES))
        tail = f.read().decode(errors="ignore")
    stamps = [line[:26] for line in tail.splitlines() if "AbletonLiveMCP: connected" in line]
    return datetime.fromisoformat(stamps[-1]) if stamps else None


def other_agent_active(quiet_s: float = 300.0, *, now: datetime | None = None, log: Path | None = None) -> bool:
    """Did anything connect to the Remote Script in the last `quiet_s` seconds?

    Call it before a run starts: our own LOM calls connect too, so during a run it sees us.
    """
    last = last_lom_connection(log)
    return last is not None and ((now or datetime.now()) - last).total_seconds() < quiet_s
