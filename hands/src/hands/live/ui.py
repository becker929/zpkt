"""Live's GUI through AppleScript: menus, windows, dialogs, and the pointer.

Only what the LOM cannot do goes through the GUI: Edit-menu time edits, saving, the Export dialog,
and reading which set is in front. Every call runs osascript against System Events, which needs
the Accessibility grant. That grant belongs to the program that runs osascript, and Claude Code's
path changes with each update, so direct calls can start failing (-1728, "not allowed assistive
access"). Hammerspoon holds a grant at a stable path, so `osa` then reruns the script as a child
of Hammerspoon (`hs -c`), as the skill's osa.sh did.
"""

from __future__ import annotations

import ctypes
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

PROCESS = "Live"  # System Events' name for Live's process, whatever the edition
REAP_SCRIPT = Path(__file__).with_name("reap_modals.applescript")

_NO_ACCESS = re.compile(r"-1728|-1719|-25211|not allowed assistive access")
_HS_FAIL = "__OSA_FAIL__"
_direct_works = False  # once a direct call succeeded, a -1728 is a real error, not a missing grant


class UiError(RuntimeError):
    """osascript failed: Live is not running, there is no Accessibility grant, or the script erred."""


def osa(script: str, *, timeout: float = 30) -> str:
    """Run AppleScript source; return its output, stripped. Raise UiError if it fails."""
    return _osascript(["-e", script], timeout)


def osa_file(path: str | os.PathLike, *args: str, timeout: float = 900) -> str:
    """Run an AppleScript file with arguments; return its output, stripped. Raise UiError if it fails."""
    return _osascript([os.fspath(path), *args], timeout)


def _osascript(argv: list[str], timeout: float) -> str:
    global _direct_works
    run = subprocess.run(["osascript", *argv], capture_output=True, text=True, timeout=timeout)
    if run.returncode == 0:
        _direct_works = True
    elif not _direct_works and _NO_ACCESS.search(run.stderr) and shutil.which("hs"):
        run = _via_hammerspoon(argv, timeout)
    if run.returncode != 0:
        raise UiError((run.stderr or run.stdout).strip()[-400:] or f"osascript exited {run.returncode}")
    return run.stdout.strip()


def _via_hammerspoon(argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run osascript as a child of Hammerspoon, which inherits its Accessibility grant."""
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as f:
        f.write("#!/bin/bash\nexec osascript " + " ".join(map(shlex.quote, argv)) + " 2>&1\n")
    os.chmod(f.name, 0o700)
    try:
        lua = f"local out, ok = hs.execute([[{f.name}]]); return (out or '') .. (ok and '' or '\\n{_HS_FAIL}')"
        hs = subprocess.run(["hs", "-c", lua], capture_output=True, text=True, timeout=timeout)
    finally:
        os.unlink(f.name)
    lines = [line for line in hs.stdout.splitlines() if not line.startswith("-- Loading extension")]
    failed = hs.returncode != 0 or _HS_FAIL in lines
    out = "\n".join(line for line in lines if line != _HS_FAIL)
    return subprocess.CompletedProcess(hs.args, int(failed), "" if failed else out, out if failed else "")


def _q(text: str) -> str:
    """An AppleScript string literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def menu_enabled(menu: str, item: str) -> bool:
    return osa(f"tell application \"System Events\" to tell process {_q(PROCESS)} to get enabled of "
               f"menu item {_q(item)} of menu {_q(menu)} of menu bar 1") == "true"


def menu(menu: str, item: str, tries: int = 6, wait_s: float = 0.4) -> bool:
    """Click Menu > Item once it is enabled. False if it stays disabled: Live greys items out while
    it is busy, and some (Delete Time) until a time selection exists."""
    for _ in range(tries):
        if menu_enabled(menu, item):
            osa(f"tell application \"System Events\" to tell process {_q(PROCESS)} to click "
                f"menu item {_q(item)} of menu {_q(menu)} of menu bar 1")
            return True
        time.sleep(wait_s)
    return False


def front_title() -> str:
    """The front window's title, which is the open set's name. UiError if Live shows no window."""
    return osa(f"tell application \"System Events\" to get name of front window of process {_q(PROCESS)}")


_WINDOWS = f"""tell application "System Events" to tell process {_q(PROCESS)}
  set out to {{}}
  repeat with w in every window
    try
      set end of out to ((name of w) as text) & "|" & ((subrole of w) as text)
    end try
  end repeat
  set AppleScript's text item delimiters to linefeed
  return out as text
end tell"""


def windows() -> list[tuple[str, str]]:
    """(name, subrole) of every Live window; dialogs have the subrole "AXDialog"."""
    pairs = (line.rsplit("|", 1) for line in osa(_WINDOWS).splitlines() if "|" in line)
    return [(name, subrole) for name, subrole in pairs]


def dialogs() -> int:
    """How many dialog windows Live has open (an Export dialog, a Save panel, a prompt)."""
    return sum(subrole == "AXDialog" for _, subrole in windows())


_CLOSE_DIALOGS = f"""tell application "System Events" to tell process {_q(PROCESS)}
  try
    perform action "AXPress" of (first button of splitter group 1 of window "Save" whose title is "Cancel")
  end try
  delay 0.5
  try
    perform action "AXPress" of (first button of group 1 of window "Export Audio/Video" whose description is "Cancel")
  end try
end tell"""


def close_dialogs() -> None:
    """Cancel a leftover Save panel and Export dialog (an interrupted export leaves both open)."""
    osa(_CLOSE_DIALOGS)
    time.sleep(0.5)


def reap_modals(reap: bool = False) -> str:
    """Report Live's modal dialogs ("CLEAN" if none); with reap, press their safe button.

    Only Cancel, Don't Save, No, Close or OK (or Escape on a Save/Open/Export panel); never Save,
    Replace, Yes or Delete. A modal with only destructive buttons is reported as "ABORT | ...".
    """
    return osa_file(REAP_SCRIPT, "reap" if reap else "check", timeout=30)


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [("origin", _Point), ("size", _Point)]


def park_cursor() -> None:
    """Put the pointer in the middle of the main display (the one with the menu bar).

    The export script clicks the Save panel's name field with cliclick, which moves the real
    pointer; parking it afterwards hands it back where Anthony expects it. Best effort: a failure
    here must not hide the export's own result.
    """
    try:
        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        cg.CGDisplayBounds.restype = _Rect
        cg.CGWarpMouseCursorPosition.argtypes = [_Point]
        b = cg.CGDisplayBounds(cg.CGMainDisplayID())
        cg.CGWarpMouseCursorPosition(_Point(b.origin.x + b.size.x / 2, b.origin.y + b.size.y / 2))
    except (OSError, AttributeError):
        pass
