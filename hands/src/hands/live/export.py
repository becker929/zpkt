"""Getting audio and sets out of Live through its dialogs: the export, by keystrokes or by the menu, and Save As.

Two ways to drive the Export dialog, one function (`export`):

- "keys" (hands.live.render.export): Cmd+Shift+R and typing into the Save panel, by export_audio.applescript. It
  renders Main, one track or every track, at any bit depth and rate.
- "menu" (`export_by_menu` here): the menu bar and accessibility only, no keystrokes. On 2026-10-14 two macOS
  permission prompts (which an agent must never answer) sat over Live's dialogs and took every keystroke ("Export
  dialog did not open"), so this way sets the dialog's controls by their descriptions, the Save panel's folder from
  its Where popup (or its Go to Folder sheet), the file name as the text field's value, and presses the buttons by
  AXPress. It renders Main. The Save panel writes into a staging folder it can reach, and the file is then moved to
  its target.

`save_as` is File > Save Live Set As through the same Save panel. The range of an export is the arrangement's time
selection, made by hands.live.timeops.select (a LOM call and a menu click). Everything that goes wrong raises
hands.live.session.Guard with what was on screen, after cancelling the dialogs it left open.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hands.live import render, session, timeops, ui
from hands.live.session import stop
from hands.live.transport import McpTransport

_IN_LIVE = 'tell application "System Events" to tell process "Live"\n{}\nend tell'
_DIALOG = 'group 1 of window "Export Audio/Video"'
_WHERE = 'first pop up button of splitter group 1 of window "Save"'
_NAME = '(first text field of (splitter group 1 of window "Save") whose description is "text field")'
_SAVE = '(first button of splitter group 1 of window "Save" whose title is "Save")'
_MAIN_OPTIONS = (
    ("Render as Loop", False),
    ("Convert to Mono", False),
    ("Normalize", False),
    ("Create Analysis File", False),
    ("Encode PCM", True),
    ("Encode MP3", False),
    ("Create Video with Rendered Audio", False),
)

Reach = Literal["where_popup", "go_to_folder"]


def ax(body: str, timeout: float = 30) -> str:
    """Run AppleScript lines against Live's process in System Events."""
    return ui.osa(_IN_LIVE.format(body), timeout=timeout)


def wait_for_window(name: str, present: bool = True, timeout_s: float = 15) -> bool:
    """Wait until Live has (or no longer has) a window called `name`; False if it does not happen in time."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if any(w[0] == name for w in ui.windows()) == present:
            return True
        time.sleep(0.25)
    return False


@dataclass(frozen=True)
class SavePanel:
    """macOS's Save panel in front of Live, driven by accessibility.

    `reach` is how it gets to a folder. "where_popup" uses only the Where popup: the folder itself, a parent of where
    the panel is, or a parent of one of its Recent Places, so the folder must be one the panel has reached before.
    "go_to_folder" types the path into the Go to Folder sheet (Cmd+Shift+G): it reaches any folder, but it needs
    keystrokes, and the mix desk needs it because the Where popup's menu does not open by accessibility on its Mac
    (2026-11-22).
    """

    reach: Reach = "where_popup"

    def folder_shown(self) -> str:
        """The name of the folder the panel is in (the Where popup's value)."""
        return ax(f"return value of {_WHERE}")

    def go_to(self, folder: Path) -> None:
        """Put the panel in `folder`. The Where popup checks the whole path; the Go to Folder sheet is skipped when the
        panel already shows a folder of that name (or of the name a link points to: Save As opens in a set's own
        folder, which may be a link)."""
        if self.reach == "where_popup":
            _go_by_where_popup(folder)
        elif self.folder_shown() not in (folder.name, folder.resolve().name):
            _go_to_folder(folder)

    def fill(self, folder: Path, name: str) -> None:
        """Fill the open panel (folder, name) and press Save."""
        if not wait_for_window("Save"):
            stop("no Save panel")
        time.sleep(0.6)
        self.go_to(folder)
        ax(f'set nf to {_NAME}\nset focused of nf to true\ndelay 0.2\nset value of nf to "{name}"')
        time.sleep(0.3)
        got = ax(f"return value of {_NAME}")
        if got != name:
            stop(f"the Save panel's name is {got!r}, not {name!r}")
        ax(f'perform action "AXPress" of {_SAVE}')
        time.sleep(1.0)
        if (
            any(w[0] == "Save" for w in ui.windows())
            and ax('return (exists sheet 1 of window "Save") as text') == "true"
        ):
            stop("the Save panel asks to replace a file")


def _where_items() -> list[str]:
    """The Where popup's items: its folder and the folder's parents, then Locations, Favorites, Recent Places
    (sections split by "missing value"). Opened and closed again by AX."""
    time.sleep(0.4)
    out = ax(f"""set p to {_WHERE}
perform action "AXPress" of p
delay 0.6
set out to {{}}
repeat with i in (menu items of menu 1 of p)
  set end of out to (name of i as text)
end repeat
click menu item 1 of menu 1 of p
set AppleScript's text item delimiters to "|"
return out as text""")
    time.sleep(0.6)
    return out.split("|")


def _choose_where(index: int) -> None:
    """Click the Where popup's item `index` (1-based)."""
    for _ in range(3):
        try:
            ax(f'set p to {_WHERE}\nperform action "AXPress" of p\ndelay 0.6\nclick menu item {index} of menu 1 of p')
            break
        except ui.UiError:
            time.sleep(0.8)
    else:
        stop(f"the Where popup would not open to choose item {index}")
    time.sleep(0.8)


def _chain(items: list[str]) -> list[str]:
    return items[: items.index("missing value")] if "missing value" in items else items


def _go_by_where_popup(folder: Path) -> None:
    want = [*reversed(folder.parts[1:]), "Macintosh HD"]  # the folder, its parents, the disk

    def step_up(items: list[str]) -> bool:
        chain = _chain(items)
        for k in range(len(chain)):
            if chain[k : k + len(want)] == want:
                if k:
                    _choose_where(k + 1)
                return True
        return False

    for attempt in range(12):
        items = _where_items()
        if _chain(items)[: len(want)] == want:
            return
        if step_up(items):
            continue
        recent = list(range(items.index("Recent Places") + 1, len(items))) if "Recent Places" in items else []
        if attempt >= len(recent):
            break
        _choose_where(recent[attempt] + 1)
    stop(f"the Save panel could not reach {folder} through its Where popup")


def _go_to_folder(folder: Path) -> None:
    ui.osa('tell application "System Events" to tell process "Live" to set frontmost to true')
    time.sleep(0.3)
    ui.osa('tell application "System Events" to keystroke "g" using {command down, shift down}')
    time.sleep(0.8)
    ui.osa('tell application "System Events" to keystroke "a" using {command down}')
    ui.osa(f'tell application "System Events" to keystroke "{folder}/"')
    time.sleep(0.8)
    ui.osa('tell application "System Events" to key code 36')
    time.sleep(1.2)
    shown = SavePanel().folder_shown()
    if shown != folder.name:
        stop(f"the Save panel is in {shown!r}, not {folder}")


# --------------------------------------------------------------------------- Save As


def save_as(
    folder: Path, name: str, *, project: bool = True, panel: SavePanel | None = None, timeout_s: float = 60
) -> Path:
    """File > Save Live Set As into `folder`; wait for the file and return it.

    With project=True Live makes a new project folder, "<folder>/<name> Project/<name>.als"; with project=False the
    folder is already inside a Live project and the set is "<folder>/<name>.als". A Save panel left open (a macOS
    prompt held it) is used as it is.
    """
    panel = panel or SavePanel()
    target = folder / f"{name} Project" / f"{name}.als" if project else folder / f"{name}.als"
    if not any(w[0] == "Save" for w in ui.windows()) and not ui.menu("File", "Save Live Set As..."):
        stop("File > Save Live Set As... stayed disabled")
    try:
        panel.fill(folder, name)
    except BaseException:
        ui.close_dialogs()
        raise
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if target.exists() and not ui.dialogs():
            return target
        time.sleep(0.5)
    stop(f"{target} did not appear (windows: {ui.windows()})")


# --------------------------------------------------------------------------- the Export dialog by the menu


def _dialog_popup(desc: str, want: str) -> None:
    """Set an Export-dialog popup (by its description): click it, click the named item in the menu window."""
    get = f'set v to value of (first pop up button of {_DIALOG} whose description is "{desc}")\nreturn v as text'
    if ax(get) == want:
        return
    ax(f'click (first pop up button of {_DIALOG} whose description is "{desc}")')
    time.sleep(0.4)
    ax(f'''set mi to missing value
repeat with w in windows
  try
    set mi to (first menu item of group 1 of group 1 of w whose name is "{want}")
    exit repeat
  end try
end repeat
if mi is missing value then error "no menu item {want}"
click mi''')
    time.sleep(0.3)
    if (got := ax(get)) != want:
        stop(f"export popup {desc} is {got!r}, wanted {want!r}")


def _dialog_check(desc: str, on: bool) -> None:
    b = f'(first button of {_DIALOG} whose description is "{desc}")'
    if (ax(f"set v to value of {b}\nreturn v as text") == "On") != on:
        ax(f"click {b}")
        time.sleep(0.2)
    if (ax(f"set v to value of {b}\nreturn v as text") == "On") != on:
        stop(f"export option {desc} would not turn {'on' if on else 'off'}")


def _slider(desc: str) -> float:
    """A range slider's value. Live 12.4 calls them "... Rendered Audio File ...", older ones "... Rendered Sample ..."."""
    error: ui.UiError | None = None
    for d in (desc, desc.replace("Rendered Sample", "Rendered Audio File")):
        try:
            return float(
                ax(f'set v to value of (first slider of {_DIALOG} whose description is "{d}")\nreturn v as text')
            )
        except ui.UiError as exc:
            error = exc
    assert error is not None
    raise error


def _check_range(start_beat: float, length_beats: float) -> None:
    """The dialog shows the range in bars, beats and sixteenths: it must be the time selection just made."""
    length = (
        _slider("Length of Rendered Sample (Bar)"),
        _slider("Length of Rendered Sample (Beat)"),
        _slider("Length of Rendered Sample (Sixteenths)"),
    )
    start = (_slider("Start of Rendered Sample (Bar)"), _slider("Start of Rendered Sample (Beat)"))
    if length != (length_beats // 4, length_beats % 4, 0.0) or start != (start_beat // 4 + 1, start_beat % 4 + 1):
        stop(f"the dialog's range is start {start}, length {length}; wanted {start_beat}+{length_beats} beats")


def _settle(path: Path) -> None:
    """Wait until Live stops writing `path` (its size holds still)."""
    size = -1
    while path.stat().st_size != size:
        size = path.stat().st_size
        time.sleep(0.5)


def export_by_menu(
    client: McpTransport,
    out: Path,
    start_beat: float,
    length_beats: float,
    *,
    staging: Path,
    bits: int = 24,
    timeout_s: float = 300,
    panel: SavePanel | None = None,
) -> Path:
    """Render Main for [start_beat, start_beat + length_beats) to `out` (.wav) by the menu and accessibility.

    The Save panel writes `staging/<out's name>` (a folder it can reach: see SavePanel), which then moves to `out`.
    Both must be new. Runs the session guard first. Returns `out` once written.
    """
    panel = panel or SavePanel()
    out = Path(out)
    staged = staging / out.name
    if staged.exists() or out.exists():
        stop(f"{staged} or {out} already exists")
    session.check(client, f"export {out.name}")
    client.run("song.loop_start = 0.0\nsong.loop_length = 4.0\nresult = 'ok'")  # else a later start can pass the end
    timeops.select(client, start_beat, length_beats)
    if not ui.menu("File", "Export Audio/Video..."):
        stop("File > Export Audio/Video... stayed disabled")
    if not wait_for_window("Export Audio/Video"):
        stop("the Export dialog did not open")
    time.sleep(0.6)
    try:
        for desc, want in (
            ("Rendered Track Chooser", "Main"),
            ("File Type", "WAV"),
            ("Recording Bit Depth", str(bits)),
            ("Sample Rate", "44100"),
        ):
            _dialog_popup(desc, want)
        for desc, on in _MAIN_OPTIONS:
            _dialog_check(desc, on)
        _check_range(start_beat, length_beats)
        t0 = time.time()
        ax(f'perform action "AXPress" of (first button of {_DIALOG} whose description is "Export")')
        panel.fill(staging, out.name)
        while time.time() - t0 < timeout_s:
            if staged.exists() and not ui.dialogs():
                break
            time.sleep(0.5)
        else:
            stop(f"{staged} not written in {timeout_s} s (windows {ui.windows()})")
    except BaseException:
        ui.close_dialogs()
        raise
    finally:
        ui.park_cursor()
    _settle(staged)
    out.parent.mkdir(parents=True, exist_ok=True)
    staged.replace(out)
    return out


# --------------------------------------------------------------------------- one function for both


def export(
    client: McpTransport,
    out: Path,
    start_beat: float | None = None,
    length_beats: float | None = None,
    *,
    method: Literal["keys", "menu"] = "keys",
    staging: Path | None = None,
    mode: str = "Main",
    bits: int = 32,
    sample_rate: int = 44100,
) -> list[Path]:
    """Render the arrangement through Live's Export dialog; return the files written.

    method="keys" is hands.live.render.export: any `mode` (Main, a track, every track), bit depth and rate, and
    without a range Live's own (the loop brace or the whole song). method="menu" is `export_by_menu`: Main at
    44.1 kHz, a range, and a `staging` folder the Save panel can reach; use it when a stray system prompt could take
    keystrokes.
    """
    if method == "keys":
        return render.export(client, out, start_beat, length_beats, mode=mode, bits=bits, sample_rate=sample_rate)
    if staging is None or start_beat is None or length_beats is None:
        raise ValueError("an export by the menu needs a range (start_beat, length_beats) and a staging folder")
    if mode != "Main" or sample_rate != 44100:
        raise ValueError("an export by the menu renders Main at 44100 Hz; use method='keys' for the rest")
    return [export_by_menu(client, out, start_beat, length_beats, staging=staging, bits=bits)]
