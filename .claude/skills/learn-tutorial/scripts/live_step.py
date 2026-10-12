"""One supervised Live step at a time: check, act once, log, stop on any surprise.

    run live_step.py --log W/practice/live_steps.jsonl pre  --expect SET
    run live_step.py --log ... read    --expect SET "result = [t.name for t in song.tracks]"
    run live_step.py --log ... exec    --expect SET @W/practice/snippets/bass_a.py
    run live_step.py --log ... save    --expect SET --path "W/practice/SET Project/SET.als"
    run live_step.py --log ... new                       # File > New Live Set, if the front set is clean
    run live_step.py --log ... save-as --dir W/practice --name SET
    run live_step.py --log ... open    --path ".../SomeSet.als"   # only when the front set is clean
    run live_step.py edited                              # front set, AXEdited, Save enabled (read-only)
    run live_step.py dialog                              # the open dialog's buttons and geometry (read-only)
    run live_step.py --log ... press --index 2 --expect-pos 812,604   # press that button, if it is still there

Every Live command first checks: one Live window, no dialog, the expected set in front, the LOM
answering. Then it does one thing, logs it with its time, and exits 2 on anything odd (a dialog,
another set in front, a call that took over 8 s: Live may be stalled). Nothing is chained: the
agent reads each result before the next step. Rules from hands/skills/ableton-live-control: never
read a property in the call that wrote it (write in exec, check in a separate read); at most 20
parameters of one device per call; time.sleep(0.3) between browser loads; keep calls well under
the Remote Script's 12 s.

save presses File > Save Live Set through accessibility (no keys) and waits for the file to change.
save-as drives File > Save Live Set As... (scripts/save_as.applescript): Go-to-folder, the name set
through accessibility, an AX press on Save; it never presses Replace. It types the folder path, so
it refuses while a system prompt is open (the keys could answer Anthony's prompt) or Live is not
the front app. Use it once to give a new Untitled set (Live-native, never an old template) its name.

dialog and press are for Live's own alerts, which expose no text: take a screenshot, run dialog to
list the buttons with their positions and sizes, match them to the screenshot, then press the
non-destructive one by index with its position as a guard (press refuses if it moved or changed).

Give the Bash tool a long timeout for open, save-as and new (300000 ms): a timeout outside the
script would leave osascript running (recovery.md#orphaned-osascript).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from hands.live import ui
from hands.live.transport import LiveClient, LiveError

HERE = Path(__file__).resolve().parent
LOG: Path = Path("live_steps.jsonl")
MAX_S = 8.0


def log(entry: dict) -> None:
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def stop(msg: str) -> None:
    print(f"STOP: {msg}")
    log({"stop": msg})
    sys.exit(2)


PROMPT_AGENTS = ["UserNotificationCenter", "CoreServicesUIAgent", "SecurityAgent", "universalAccessAuthWarn"]


def system_prompts() -> tuple[str, list[str]]:
    """(front app, open system prompts as 'agent|text'): read-only System Events query."""
    names = "{" + ", ".join(f'"{n}"' for n in PROMPT_AGENTS) + "}"
    out = ui.osa(f"""tell application "System Events"
  set out to {{"front=" & (name of first process whose frontmost is true)}}
  repeat with nm in {names}
    if exists process (nm as text) then
      repeat with w in (windows of process (nm as text))
        set t to ""
        try
          set t to (value of static texts of w) as text
        end try
        set end of out to (nm as text) & "|" & t
      end repeat
    end if
  end repeat
  set AppleScript's text item delimiters to linefeed
  return out as text
end tell""", timeout=20)
    lines = out.splitlines()
    return lines[0].removeprefix("front="), [ln for ln in lines[1:] if ln.strip()]


def keys_safe(what: str) -> None:
    """Stop before a step that types: a system prompt could take the keys, and Return or Escape
    would answer a prompt that is Anthony's to answer."""
    front, prompts = system_prompts()
    if prompts:
        stop(f"{what} types keys, and {len(prompts)} system prompt(s) are open: "
             + "; ".join(p[:80] for p in prompts) + ". Ask Anthony to answer them first (recovery.md#foreign-prompt)")
    if front != "Live":
        stop(f"{what} types keys, and the front app is {front!r}, not Live")


def edited() -> bool:
    return ui.osa(f'tell application "System Events" to tell process "{ui.PROCESS}" to tell front window to '
                  'get value of attribute "AXEdited" of (value of attribute "AXCloseButton")') == "true"


def dirty() -> bool:
    return edited() or ui.menu_enabled("File", "Save Live Set")


def pre(expect: str | None, client: LiveClient) -> str:
    try:
        wins = ui.windows()
        front = ui.front_title()
    except ui.UiError as exc:
        stop(f"cannot read Live's windows: {exc}")
    dialogs = [w for w in wins if w[1] == "AXDialog"]
    if dialogs:
        stop(f"dialog open: {dialogs} (an unnamed one: take a screenshot and read it before pressing anything)")
    if len(wins) != 1:
        stop(f"expected one Live window, found {wins}")
    if expect and front != expect:
        stop(f"front set is {front!r}, expected {expect!r}")
    t = time.monotonic()
    try:
        client.run("result = 1")
    except LiveError as exc:
        stop(f"LOM does not answer: {exc}")
    print(f"pre ok: {front!r}, 1 window, no dialog, LOM {1000 * (time.monotonic() - t):.0f} ms")
    return front


def call(client: LiveClient, code: str, what: str) -> object:
    t = time.monotonic()
    res = client.execute(code)
    dt = time.monotonic() - t
    entry = {"what": what, "code": code[:400], "elapsed_s": round(dt, 3), "status": res.status}
    if res.status != "ok":
        entry["error"] = str(res.error)[:400]
        log(entry)
        stop(f"LOM error after {dt:.2f} s: {res.error} (warning: {res.warning})")
    log(entry)
    if dt > MAX_S:
        stop(f"the call took {dt:.1f} s (> {MAX_S} s): Live may be stalled; run preflight.py")
    print(f"{what} ok in {dt:.2f} s")
    return res.result


def save(path: Path) -> None:
    before = path.stat().st_mtime_ns if path.exists() else None
    if not ui.menu_enabled("File", "Save Live Set"):
        print("Save Live Set is greyed out: nothing to save")
        return
    t = time.monotonic()
    if not ui.menu("File", "Save Live Set"):
        stop("File > Save Live Set stayed disabled")
    while time.monotonic() - t < 30:
        try:
            if path.stat().st_mtime_ns != before:
                break
        except FileNotFoundError:
            pass  # Live replaces the file, so it is missing for a moment
        time.sleep(0.05)
    else:
        stop(f"{path.name} was not rewritten in 30 s (a dialog? take a screenshot)")
    time.sleep(0.5)
    if ui.dialogs():
        stop("a dialog is open after saving (an older-version set asks to Save As: recovery.md#old-template)")
    log({"what": "save", "path": str(path), "elapsed_s": round(time.monotonic() - t, 3)})
    print(f"saved {path.name} in {time.monotonic() - t:.2f} s")


def save_as(folder: Path, name: str) -> None:
    keys_safe("save-as")
    folder.mkdir(parents=True, exist_ok=True)
    t = time.monotonic()
    out = ui.osa_file(HERE / "save_as.applescript", str(folder.resolve()), name, timeout=60)
    log({"what": "save_as", "dir": str(folder), "name": name, "result": out, "elapsed_s": round(time.monotonic() - t, 2)})
    if out != "PRESSED_SAVE":
        stop(f"save-as: {out} (take a screenshot; never press Replace)")
    want = folder / f"{name} Project" / f"{name}.als"
    while time.monotonic() - t < 30 and not want.exists():
        time.sleep(0.2)
    if not want.exists():
        stop(f"save-as pressed Save but {want} does not exist: Live used its last-used folder. Find it "
             f"(mdfind -name '{name}.als'), tell the orchestrator, and work from there (recovery.md#export-folder)")
    print(f"save-as: {out}; {want} exists")


def new_set(client: LiveClient) -> None:
    """File > New Live Set: a Live-native Untitled set (never an old template). Only from a clean
    front set; prints the set it replaced and its file, to reopen at the end of the practice."""
    from hands import config

    front = pre(None, client)
    if dirty():
        stop(f"{front!r} has unsaved changes: New Live Set would ask to save it (recovery.md#dirty-set)")
    if front == "Untitled":
        log({"what": "new", "previous_front": front, "note": "a clean Untitled set was already in front"})
        print("a clean Untitled set is already in front: using it (nothing to reopen at the end)")
        return
    known = config.rig().set_path(front)
    t = time.monotonic()
    if not ui.menu("File", "New Live Set"):
        stop("File > New Live Set stayed disabled")
    while time.monotonic() - t < 30:
        try:
            if ui.dialogs():
                stop("a dialog appeared after New Live Set (take a screenshot)")
            if ui.front_title() == "Untitled":
                break
        except ui.UiError:
            pass
        time.sleep(0.2)
    else:
        stop("no Untitled set after 30 s")
    client.run("result = 1")
    log({"what": "new", "previous_front": front, "previous_path": str(known) if known.exists() else None,
         "elapsed_s": round(time.monotonic() - t, 2)})
    print(f"Untitled in front; it replaced {front!r} ({known if known.exists() else 'file not in sets_dir: ask'})")


def open_set(path: Path, client: LiveClient, app: str) -> None:
    if not path.exists():
        stop(f"no set at {path}")
    if dirty():
        stop("the front set has unsaved changes; opening another would raise 'Save changes?' (recovery.md#dirty-set)")
    t = time.monotonic()
    r = subprocess.run(["open", "-a", app, str(path)], capture_output=True, text=True)
    if r.returncode:
        stop(f"open failed: {r.stderr.strip()}")
    while time.monotonic() - t < 120:
        try:
            if ui.dialogs():
                stop("a dialog appeared while opening (take a screenshot)")
            if ui.front_title() == path.stem:
                break
        except ui.UiError:
            pass
        time.sleep(0.2)
    else:
        stop(f"{path.stem} not in front after 120 s")
    while time.monotonic() - t < 120:
        try:
            client.run("result = 1")
            break
        except LiveError:
            time.sleep(0.3)
    time.sleep(1.0)
    if ui.dialogs():
        stop("a dialog is open after the set loaded (take a screenshot)")
    log({"what": "open", "path": str(path), "elapsed_s": round(time.monotonic() - t, 2)})
    print(f"opened {path.stem} in {time.monotonic() - t:.1f} s")


_BUTTONS = f"""tell application "System Events" to tell process "{ui.PROCESS}"
  set out to {{}}
  set ds to (every window whose subrole is "AXDialog")
  if (count of ds) is 0 then return "NO_DIALOG"
  set w to item 1 of ds
  set p to position of w
  set z to size of w
  set end of out to "window|" & (name of w as text) & "|" & (item 1 of p) & "," & (item 2 of p) & "|" & (item 1 of z) & "," & (item 2 of z)
  set bs to (every UI element of (entire contents of w) whose role is "AXButton")
  repeat with b in bs
    set t to ""
    set d to ""
    try
      set t to (title of b) as text
    end try
    try
      set d to (description of b) as text
    end try
    set p to position of b
    set z to size of b
    set end of out to "button|" & t & "|" & d & "|" & (item 1 of p) & "," & (item 2 of p) & "|" & (item 1 of z) & "," & (item 2 of z)
  end repeat
  set AppleScript's text item delimiters to linefeed
  return out as text
end tell"""


def dialog_buttons() -> tuple[str, list[dict]]:
    out = ui.osa(_BUTTONS, timeout=20)
    if out == "NO_DIALOG":
        return out, []
    lines = out.splitlines()
    buttons = []
    for i, ln in enumerate(lines[1:], 1):
        _, title, desc, pos, size = ln.split("|")
        x, y = (int(float(v)) for v in pos.split(","))
        w, h = (int(float(v)) for v in size.split(","))
        buttons.append({"index": i, "title": title, "description": desc, "x": x, "y": y, "w": w, "h": h})
    return lines[0], buttons


def press(index: int, expect_pos: str) -> None:
    """Press button `index` of the open dialog, only if it is still at the position given."""
    head, buttons = dialog_buttons()
    if not buttons:
        stop("no dialog with buttons is open")
    b = next((b for b in buttons if b["index"] == index), None)
    ex, ey = (int(v) for v in expect_pos.split(","))
    if b is None or abs(b["x"] - ex) > 3 or abs(b["y"] - ey) > 3:
        stop(f"button {index} is not at {expect_pos} any more: {b}; run dialog again and re-check the screenshot")
    if b["title"] in ("Save", "Replace", "Overwrite", "Delete", "Yes", "Remove", "Don't Restore"):
        stop(f"button {index} is titled {b['title']!r}: a destructive button is never pressed by this tool")
    ui.osa(f'tell application "System Events" to tell process "{ui.PROCESS}" to perform action "AXPress" of '
           f'(item {index} of (every UI element of (entire contents of (item 1 of (every window whose subrole is '
           f'"AXDialog"))) whose role is "AXButton"))', timeout=20)
    log({"what": "press", "dialog": head, "button": b})
    time.sleep(0.8)
    print(f"pressed button {index} {b}; dialogs now open: {ui.dialogs()}")


def main() -> None:
    global LOG
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", default="live_steps.jsonl", help="JSONL step log (the run's practice/live_steps.jsonl)")
    ap.add_argument("--app", default="Ableton Live 12 Suite")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("edited")
    sub.add_parser("new")
    sub.add_parser("dialog")
    p = sub.add_parser("press")
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--expect-pos", required=True, help="X,Y of the button as dialog printed it")
    p = sub.add_parser("pre")
    p.add_argument("--expect", required=True)
    for name in ("exec", "read"):
        p = sub.add_parser(name)
        p.add_argument("--expect", required=True)
        p.add_argument("code", help="Python for the Remote Script, or @FILE")
    p = sub.add_parser("save")
    p.add_argument("--expect", required=True)
    p.add_argument("--path", required=True, help="the set's .als, to watch")
    p = sub.add_parser("save-as")
    p.add_argument("--dir", required=True)
    p.add_argument("--name", required=True)
    p = sub.add_parser("open")
    p.add_argument("--path", required=True)
    a = ap.parse_args()
    LOG = Path(a.log).expanduser()

    if a.cmd == "edited":
        print(json.dumps({"front": ui.front_title(), "edited": edited(),
                          "save_enabled": ui.menu_enabled("File", "Save Live Set"), "dialogs": ui.dialogs()}))
        return
    if a.cmd == "dialog":
        head, buttons = dialog_buttons()
        print(head)
        for b in buttons:
            print(json.dumps(b))
        return
    if a.cmd == "press":
        press(a.index, a.expect_pos)
        return
    client = LiveClient(timeout=12.0)
    if a.cmd == "new":
        new_set(client)
        return
    if a.cmd == "open":
        pre(None, client)
        open_set(Path(a.path).expanduser(), client, a.app)
        return
    if a.cmd == "save-as":
        front = pre(None, client)
        if front != "Untitled" and not front.startswith("tut_"):
            stop(f"save-as is for a new set this run made; the front set is {front!r}")
        save_as(Path(a.dir).expanduser(), a.name)
        return
    pre(a.expect, client)
    if a.cmd in ("exec", "read"):
        code = Path(a.code[1:]).read_text() if a.code.startswith("@") else a.code
        print(json.dumps(call(client, code, a.cmd), default=str))
    elif a.cmd == "save":
        save(Path(a.path).expanduser())


if __name__ == "__main__":
    main()
