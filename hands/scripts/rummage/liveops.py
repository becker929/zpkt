"""Small Live helpers for the SH001 recipe: the rig settings for this set, short LOM calls, parameters set in their
display units, preset and sample loads, and two GUI steps done without keystrokes: File > Save Live Set As and the
export.

Every LOM call here stays short (well under the Remote Script's 12 s) and never reads back what it just wrote in the
same call (that crashes Live). Callers read back in a separate call.

Why no keystrokes: hands' export script opens the Export dialog with Cmd+Shift+R and types the folder and the file
name into the Save panel. On 2026-10-14 two macOS permission prompts (which an agent must never answer) sat over
Live's dialogs and took every keystroke ("Export dialog did not open"). So these helpers do the same steps through
the menu bar and accessibility only: the range from the loop brace (hands' timeops.select, a LOM call and a menu
click), the Export dialog's controls by their descriptions, the Save panel's folder from its Where popup, the file
name as the text field's value, and the buttons by AXPress.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

SCRATCH = Path("~/_agent_scratch/rummage").expanduser()
SET_NAME = "SH001_rummage"
SET_DIR = SCRATCH / "set" / f"{SET_NAME} Project"   # Live puts a new set in "<name> Project/"
# hands' guards read the rig from the environment first: this set is "ours", and nothing goes under ~/Music.
os.environ.setdefault("ZPKT_SETS_DIR", str(SET_DIR))
os.environ.setdefault("ZPKT_SET_PREFIXES", "SH001_")
os.environ.setdefault("ZPKT_DATA_DIR", str(SCRATCH / "data"))
os.environ.setdefault("ZPKT_RENDERS_DIR", str(SCRATCH / "renders"))

from hands.live import session, timeops, ui
from hands.live.transport import LiveClient

LIVE = LiveClient()
EXPORT_DIR = SCRATCH   # where the Save panel writes; a parent of set/, so reachable from the Recent Place "set"

# Set a parameter in its display units: a binary search over str_for_value (the LOM only takes raw values).
HELPER = r'''
import re
def _num(s):
    m = re.match(r"\s*(-?inf|-?[\d.]+)\s*(k?Hz|ms|s|dB|%|st|ct)?", s)
    if not m: return None
    v = -1e9 if 'inf' in m.group(1) else float(m.group(1))
    return v * (1000 if (m.group(2) or '') in ('s', 'kHz') else 1)
def _set(d, name, want):
    ps = [p for p in d.parameters if p.name == name]
    if not ps: return name + '?'
    return _setp(ps[0], want, name)
def _setp(p, want, name=''):
    if isinstance(want, str) and p.is_quantized:
        items = list(p.value_items)
        if want not in items: return name + '=' + want + '? ' + '|'.join(items)
        p.value = float(items.index(want)); return None
    if isinstance(want, str):
        t = _num(want); lo, hi = p.min, p.max
        if _num(p.str_for_value(lo)) > _num(p.str_for_value(hi)):
            lo, hi = hi, lo
        for _ in range(40):
            mid = (lo + hi) / 2
            if _num(p.str_for_value(mid)) < t: lo = mid
            else: hi = mid
        p.value = hi; return None
    p.value = max(p.min, min(p.max, float(want))); return None
'''


def run(code: str):
    return LIVE.run(code)


def guard(where: str) -> str:
    """hands' session guard: no dialog, our set in front, the LOM answering."""
    return session.check(LIVE, where)


def setp(dev: str, params: dict) -> None:
    """Set a device's parameters (`dev` is a LOM path), 16 to a call."""
    items = list(params.items())
    for k in range(0, len(items), 16):
        code = HELPER + f"d = {dev}\nbad = []\n" + "".join(
            f"bad.append(_set(d, {n!r}, {v!r}))\n" for n, v in items[k:k + 16]) + "result = [b for b in bad if b]"
        missing = LIVE.run(code)
        if missing:
            sys.exit(f"STOP: {dev}: {missing}")


def mixer(track: str, vol_db: float | None = None, sends: tuple = (), pan: float | None = None) -> None:
    """A track's volume (dB), sends (dB, None for off) and pan (-1..1), in one call."""
    lines = [f"m = {track}.mixer_device", "bad = []"]
    if vol_db is not None:
        lines.append(f"bad.append(_setp(m.volume, '{vol_db} dB', 'volume'))")
    for k, s in enumerate(sends):
        lines.append(f"m.sends[{k}].value = 0.0" if s is None else f"bad.append(_setp(m.sends[{k}], '{s} dB', 'send'))")
    if pan is not None:
        lines.append(f"m.panning.value = {float(pan)}")
    lines.append("result = [b for b in bad if b]")
    bad = LIVE.run(HELPER + "\n".join(lines))
    if bad:
        sys.exit(f"STOP: {track} mixer: {bad}")


def params(dev: str, names: list[str] | None = None, start: int = 0, count: int = 20) -> list:
    """Read up to 20 parameters (name, display value, raw value)."""
    sel = f"[p for p in d.parameters if p.name in {names!r}]" if names else f"list(d.parameters)[{start}:{start + count}]"
    return LIVE.run(f"d = {dev}\nresult = [(p.name, p.str_for_value(p.value), round(p.value, 4)) for p in {sel}]")


def load_item(track: str, root: str, folder: str | None, name: str) -> None:
    """Load a browser item (a device, a preset or a sample) onto `track` (a LOM path). `folder` is a child of
    browser.<root> (e.g. 'Mallets' under sounds), or None for an item at the top of the root."""
    where = f"[x for x in browser.{root}.children if x.name == {folder!r}][0]" if folder else f"browser.{root}"
    select_track(track)
    LIVE.run(f"""c = {where}
it = [x for x in c.children if x.name == {name!r}]
if not it: raise ValueError('no ' + {name!r})
browser.load_item(it[0])
time.sleep(0.3)
result = 'requested'""")
    time.sleep(1.0)


def select_track(track: str) -> None:
    """Select `track` and read the selection back (setting it can silently not take, e.g. for Main right after a view
    change; a load would then land on whatever track was selected)."""
    for _ in range(4):
        LIVE.run(f"song.view.selected_track = {track}\nresult = 'ok'")
        time.sleep(0.2)
        if LIVE.run(f"result = song.view.selected_track.name == {track}.name"):
            return
        LIVE.run("song.view.selected_track = song.return_tracks[0]\nresult = 'ok'")
        time.sleep(0.2)
    sys.exit(f"STOP: could not select {track}")


def devices(track: str) -> list[str]:
    return LIVE.run(f"result = [d.name for d in {track}.devices]")


# ---- the GUI, without keystrokes --------------------------------------------------------------------------------------
_SE = 'tell application "System Events" to tell process "Live"\n{}\nend tell'
_DIALOG = 'group 1 of window "Export Audio/Video"'
_POPUP = 'first pop up button of splitter group 1 of window "Save"'
_NAME = '(first text field of (splitter group 1 of window "Save") whose description is "text field")'


def _ax(body: str, timeout: float = 30) -> str:
    return ui.osa(_SE.format(body), timeout=timeout)


def _wait_window(name: str, present: bool = True, timeout_s: float = 15) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if any(w[0] == name for w in ui.windows()) == present:
            return True
        time.sleep(0.25)
    return False


def _where_items() -> list[str]:
    """The Save panel's Where popup: its folder and the folder's parents, then Locations, Favorites, Recent Places
    (sections split by "missing value"). Opened and closed again by AX."""
    time.sleep(0.4)
    out = _ax(f'''set p to {_POPUP}
perform action "AXPress" of p
delay 0.6
set out to {{}}
repeat with i in (menu items of menu 1 of p)
  set end of out to (name of i as text)
end repeat
click menu item 1 of menu 1 of p
set AppleScript's text item delimiters to "|"
return out as text''')
    time.sleep(0.6)
    return out.split("|")


def _choose_where(index: int) -> None:
    """Click the Where popup's item `index` (1-based)."""
    for _ in range(3):
        try:
            _ax(f'''set p to {_POPUP}
perform action "AXPress" of p
delay 0.6
click menu item {index} of menu 1 of p''')
            break
        except ui.UiError:
            time.sleep(0.8)
    else:
        sys.exit(f"STOP: the Where popup would not open to choose item {index}")
    time.sleep(0.8)


def _chain(items: list[str]) -> list[str]:
    return items[:items.index("missing value")] if "missing value" in items else items


def _goto(folder: Path) -> None:
    """Put the Save panel in `folder` using only the Where popup: the folder itself, a parent of where the panel is,
    or a parent of one of the Recent Places."""
    want = list(reversed(folder.parts[1:])) + ["Macintosh HD"]   # rummage, _agent_scratch, anthonybecker, Users, disk

    def step_up(items: list[str]) -> bool:
        chain = _chain(items)
        for k in range(len(chain)):
            if chain[k:k + len(want)] == want:
                if k:
                    _choose_where(k + 1)
                return True
        return False

    for attempt in range(12):
        items = _where_items()
        if _chain(items)[:len(want)] == want:
            return
        if step_up(items):
            continue
        recent = [j for j in range(items.index("Recent Places") + 1, len(items))] if "Recent Places" in items else []
        if attempt >= len(recent):
            break
        _choose_where(recent[attempt] + 1)
    sys.exit(f"STOP: the Save panel could not reach {folder} through its Where popup")


def _save_panel(folder: Path, name: str) -> None:
    """Fill the open Save panel (folder, name) and press Save."""
    if not _wait_window("Save"):
        sys.exit("STOP: no Save panel")
    time.sleep(0.6)
    _goto(folder)
    _ax(f"set nf to {_NAME}\nset focused of nf to true\ndelay 0.2\nset value of nf to \"{name}\"")
    time.sleep(0.3)
    got = _ax(f"return value of {_NAME}")
    if got != name:
        sys.exit(f"STOP: the Save panel's name is {got!r}, not {name!r}")
    _ax('perform action "AXPress" of (first button of splitter group 1 of window "Save" whose title is "Save")')
    time.sleep(1.0)
    if any(w[0] == "Save" for w in ui.windows()) and _ax('return (exists sheet 1 of window "Save") as text') == "true":
        sys.exit("STOP: the Save panel asks to replace a file")


def save_as(folder: Path, name: str, timeout_s: float = 60) -> Path:
    """File > Save Live Set As into `folder` (Live makes "<name> Project/<name>.als"); wait for the file."""
    target = folder / f"{name} Project" / f"{name}.als"
    if not ui.menu("File", "Save Live Set As..."):
        sys.exit("STOP: File > Save Live Set As... stayed disabled")
    try:
        _save_panel(folder, name)
    except (SystemExit, Exception):
        ui.close_dialogs()
        raise
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if target.exists() and not ui.dialogs():
            return target
        time.sleep(0.5)
    sys.exit(f"STOP: {target} did not appear (windows: {ui.windows()})")


def _dialog_popup(desc: str, want: str) -> None:
    """Set an Export-dialog popup (by its description): click it, click the named item in the menu window."""
    get = f'return value of (first pop up button of {_DIALOG} whose description is "{desc}") as text'
    if _ax(get) == want:
        return
    _ax(f'click (first pop up button of {_DIALOG} whose description is "{desc}")')
    time.sleep(0.4)
    _ax(f'''set mi to missing value
repeat with w in windows
  try
    set mi to (first menu item of group 1 of group 1 of w whose name is "{want}")
    exit repeat
  end try
end repeat
if mi is missing value then error "no menu item {want}"
click mi''')
    time.sleep(0.3)
    if (got := _ax(get)) != want:
        sys.exit(f"STOP: export popup {desc} is {got!r}, wanted {want!r}")


def _dialog_check(desc: str, on: bool) -> None:
    b = f'(first button of {_DIALOG} whose description is "{desc}")'
    if (_ax(f"return value of {b} as text") == "On") != on:
        _ax(f"click {b}")
        time.sleep(0.2)
    if (_ax(f"return value of {b} as text") == "On") != on:
        sys.exit(f"STOP: export option {desc} would not turn {'on' if on else 'off'}")


def _slider(desc: str) -> float:
    return float(_ax(f'return value of (first slider of {_DIALOG} whose description is "{desc}") as text'))


def export(out: Path, start_beat: float, length_beats: float, *, bits: int = 24, timeout_s: float = 300) -> Path:
    """Render Main for [start_beat, start_beat + length_beats) to `out` (.wav). Returns `out` once written."""
    out = Path(out)
    tmp = EXPORT_DIR / out.name
    if tmp.exists() or out.exists():
        sys.exit(f"STOP: {tmp} or {out} already exists")
    guard(f"export {out.name}")
    timeops.select(LIVE, start_beat, length_beats)
    if not ui.menu("File", "Export Audio/Video..."):
        sys.exit("STOP: File > Export Audio/Video... stayed disabled")
    if not _wait_window("Export Audio/Video"):
        sys.exit("STOP: the Export dialog did not open")
    time.sleep(0.6)
    try:
        _dialog_popup("Rendered Track Chooser", "Main")
        _dialog_popup("File Type", "WAV")
        _dialog_popup("Recording Bit Depth", str(bits))
        _dialog_popup("Sample Rate", "44100")
        for desc, on in (("Render as Loop", False), ("Convert to Mono", False), ("Normalize", False),
                         ("Create Analysis File", False), ("Encode PCM", True), ("Encode MP3", False),
                         ("Create Video with Rendered Audio", False)):
            _dialog_check(desc, on)
        length = (_slider("Length of Rendered Sample (Bar)"), _slider("Length of Rendered Sample (Beat)"),
                  _slider("Length of Rendered Sample (Sixteenths)"))
        start = (_slider("Start of Rendered Sample (Bar)"), _slider("Start of Rendered Sample (Beat)"))
        if length != (length_beats // 4, length_beats % 4, 0.0) or start != (start_beat // 4 + 1, start_beat % 4 + 1):
            sys.exit(f"STOP: the dialog's range is start {start}, length {length}; wanted {start_beat}+{length_beats} beats")
        t0 = time.time()
        _ax(f'perform action "AXPress" of (first button of {_DIALOG} whose description is "Export")')
        _save_panel(EXPORT_DIR, out.name)
        while time.time() - t0 < timeout_s:
            if tmp.exists() and not ui.dialogs():
                break
            time.sleep(0.5)
        else:
            sys.exit(f"STOP: {tmp} not written in {timeout_s} s (windows {ui.windows()})")
    except (SystemExit, Exception):
        ui.close_dialogs()
        raise
    finally:
        ui.park_cursor()
    size = -1
    while tmp.stat().st_size != size:                    # let the write settle
        size = tmp.stat().st_size
        time.sleep(0.5)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.replace(out)
    return out
