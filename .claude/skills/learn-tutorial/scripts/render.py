"""Render the practice set's arrangement through hands' offline export, opening the Export dialog by
a menu press instead of Cmd+Shift+R, and check the file.

    run render.py practice/renders/A_raw.wav --expect tut_<id>_practice --start 8 --length 65 \\
        --log practice/live_steps.jsonl
    run render.py --print-script          # write the patched AppleScript to a temp file and show the diff

Defaults: Main, 32-bit float, 44.1 kHz. --start/--length are song beats (2 bars of lead-in = start 8;
16 bars plus a 1-beat tail = 65). --mode takes a track name for a stem: Live then writes
"<name> <track>.wav".

The patch (two lines of hands/src/hands/live/export_audio.applescript, applied at run time so hands'
fixes carry over): the dialog opens through File > Export Audio/Video... and the file name is set
through accessibility, not cliclick. A system prompt holding the key focus swallowed Cmd+Shift+R
in run 1. The export still types (Go-to-folder, Return, Escape), so it refuses while a system prompt
is open or Live is not the front app: those keys could answer Anthony's prompt
(recovery.md#foreign-prompt). Always export into the same renders/ folder; if the file is not where
asked, look in Live's last-used folder (recovery.md#export-folder).

Run it with the Bash tool's run_in_background (or a 600000 ms timeout), never inside another
timeout: a killed Python leaves osascript running (recovery.md#orphaned-osascript). hands' own
900 s timeout is the guard.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
import tempfile
import time
from pathlib import Path

from hands.live import render, ui
from hands.live.transport import LiveClient

from hands import audio

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import live_step

PATCH = [
    ("set cliclickPath to my resolveCliclick()",
     'set cliclickPath to "" -- learn-tutorial: the Save-panel name is set through accessibility'),
    ('keystroke "r" using {command down, shift down}',
     'click menu item "Export Audio/Video..." of menu "File" of menu bar 1 -- learn-tutorial: a menu press, not keys'),
]


def patched_script() -> Path:
    src = Path(render.SCRIPT).read_text()
    for old, new in PATCH:
        if src.count(old) != 1:
            raise SystemExit(f"hands' export script changed ({old!r} found {src.count(old)} times): review PATCH")
        src = src.replace(old, new)
    out = Path(tempfile.gettempdir()) / "learn_tutorial_export_menu.applescript"
    out.write_text(src)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", help="the WAV to write (must not exist)")
    ap.add_argument("--expect", help="the practice set that must be in front")
    ap.add_argument("--start", type=float, default=8.0, help="first song beat")
    ap.add_argument("--length", type=float, default=65.0, help="beats")
    ap.add_argument("--mode", default="Main")
    ap.add_argument("--log", default="live_steps.jsonl")
    ap.add_argument("--print-script", action="store_true", help="show the patch and exit (no Live)")
    a = ap.parse_args()

    script = patched_script()
    if a.print_script:
        diff = difflib.unified_diff(Path(render.SCRIPT).read_text().splitlines(), script.read_text().splitlines(),
                                    "export_audio.applescript", script.name, lineterm="", n=0)
        print("\n".join(diff))
        print(f"-> {script}")
        return
    if not (a.out and a.expect):
        ap.error("give OUT and --expect")
    out = Path(a.out).expanduser().absolute()
    live_step.LOG = Path(a.log).expanduser()
    if out.exists():
        sys.exit(f"{out} exists: export over a file makes Live trash and rename; pick a new name")
    if ui.dialogs():
        sys.exit("a dialog is open: take a screenshot first")
    if ui.front_title() != a.expect:
        sys.exit(f"front set is {ui.front_title()!r}, expected {a.expect!r}")
    live_step.keys_safe("render")
    client = LiveClient(timeout=12)
    tempo = client.run("result = song.tempo")
    render.SCRIPT = script
    t = time.monotonic()
    files = render.export(client, out, start_beat=a.start, length_beats=a.length, mode=a.mode, bits=32,
                          sample_rate=44100)
    dt = time.monotonic() - t
    stats = audio.check_audio(files[0], seconds=a.length * 60 / tempo, tol_s=0.05)
    result = {"files": [str(f) for f in files], "export_s": round(dt, 1), "stats": stats,
              "dialogs_after": ui.dialogs(), "front": ui.front_title()}
    print(json.dumps(result, indent=1, default=str))
    with live_step.LOG.open("a") as f:
        f.write(json.dumps({"what": "export", "out": str(out), "start": a.start, "length": a.length,
                            "elapsed_s": round(dt, 1), "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")


if __name__ == "__main__":
    main()
