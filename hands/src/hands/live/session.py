"""Live sessions: the guard every step runs, and opening, saving, restarting Live.

Before and after each Live step, `check` makes sure Live is where the step expects it: no dialog
open, one of our sets in front (config.set_prefixes: anything else means someone else is using
Live), the expected set if one is named, and the LOM answering. A Guard means stop: never chain the
next step past a surprise (docs/probe-packing-findings.md, section 7). Each Guard is also reported
to the studio as a major step, so there is a screenshot of what went wrong.

Sets live in config.sets_dir and are named without ".als".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import NoReturn

from hands import config, steps
from hands.live import ui
from hands.live.transport import LiveError, McpTransport

_LOG_TAIL_BYTES = 4 << 20  # Log.txt grows by megabytes a day; the last connections are at its end


class Guard(RuntimeError):
    """Live is not in the state a step expects. Stop; do not continue the run."""


def stop(message: str) -> NoReturn:
    """Report the surprise to the studio (a screenshot of it), then raise Guard."""
    steps.report(f"guard: {message}", "major")
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
    about unsaved changes. Live does not reload a set that is already open, so asking for the front
    set again would keep its old state (for a batch rewritten offline: render the old batch); that
    is a Guard. Raises Guard if the window or the LOM does not come up in time.
    """
    rig = config.rig()
    path = rig.set_path(name)
    if not path.exists():
        stop(f"open: no set {path}")
    front = _front()
    if front == name:
        stop(f"open: {name} is already open, and Live would not reload it; open another set first")
    if save_current and front and rig.set_path(front).exists():
        save(front)
    steps.report(f"opening {name}", "minor")
    t0 = time.monotonic()
    opened = subprocess.run(["open", "-a", rig.live_app, str(path)], capture_output=True, text=True)
    if opened.returncode:
        stop(f"open: `open` failed: {opened.stderr.strip()[-200:]}")
    deadline = t0 + timeout_s
    while _front() != name:
        if time.monotonic() > deadline:
            stop(f"open: Live did not show {name} in {timeout_s:g} s; front window is {_front()!r}")
        time.sleep(0.1)
    while not _answers(client):
        if time.monotonic() > deadline:
            stop(f"open: {name} is in front but the LOM did not answer in {timeout_s:g} s")
        time.sleep(0.1)
    seconds = time.monotonic() - t0
    steps.report(f"opened {name} in {seconds:.1f} s", "major")
    return seconds


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
                steps.report(f"saved {name}", "minor")
                return True
        except FileNotFoundError:
            pass  # Live replaces the file, so it is missing for a moment
        time.sleep(0.05)
    stop(f"save: {path.name} was not rewritten in {timeout_s:g} s")


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
        save(front)
    if ui.dialogs():
        stop("restart: a dialog is open; quitting would stop at it")
    steps.report("quitting Live", "major")
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
            steps.report("Live is back", "major")
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


def memory() -> dict:
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

    out = {"swap_used_gb": round(float(swap.split("used = ")[1].split("M")[0]) / 1024, 2),
           "compressed_gb": round(pages("Pages occupied by compressor"), 2),
           "free_gb": round(pages("Pages free"), 2),
           "live_rss_gb": None, "live_mem_gb": None, "live_compressed_gb": None}
    pid = subprocess.run(["pgrep", "-x", "Live"], capture_output=True, text=True).stdout.split()
    if pid:
        rss_kb = int(subprocess.run(["ps", "-o", "rss=", "-p", pid[0]], capture_output=True, text=True).stdout)
        top = subprocess.run(["top", "-l", "1", "-pid", pid[0], "-stats", "mem,cmprs"],
                             capture_output=True, text=True).stdout
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
