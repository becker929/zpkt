"""Preflight for a learn-tutorial run: tools, calibration, and (for practice) whether Live is safe to use.

    run preflight.py --stage scrape
    run preflight.py --stage practice                                   # read-only
    run preflight.py --stage practice --ours tut_<id>_practice --write-test --clock-test

Read-only unless the front set is the one this run created (--ours): then --write-test times one
harmless LOM write and --clock-test plays the transport for about a second. Never on someone
else's set. Each line is PASS, WARN or STOP, with the reference/recovery.md section to read.
Exit 1 on any STOP: do not start the stage.

Practice checks: Live running; LOM answering and its read latency; dialogs (an unnamed one means
take a screenshot first); the front set and whether it is ours; the two dirty signals (File > Save
Live Set enabled, the close button's AXEdited); "Audio queue timeout" in Live's Log.txt in the last
--log-minutes; another client on the Remote Script lately; system prompts that steal keys; orphaned
osascript; Live's memory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
results: list[dict] = []


def report(level: str, name: str, detail: str, see: str = "", value=None) -> None:
    results.append({"level": level, "check": name, "detail": detail, "see": see, "value": value})
    print(f"{level:4s} {name}: {detail}" + (f"  [recovery.md#{see}]" if see else ""))


def tools(stage: str) -> None:
    need = ["ffmpeg", "ffprobe", "node"] + (["say"] if stage == "practice" else [])
    missing = [t for t in need if not shutil.which(t)]
    ytdlp = shutil.which("yt-dlp") or os.path.expanduser("~/.local/bin/yt-dlp")
    if not os.path.exists(ytdlp):
        missing.append("yt-dlp")
    report("STOP" if missing else "PASS", "tools", f"missing {missing}" if missing else "ffmpeg, yt-dlp, node present")
    venvs = {"onsets.py": "numpy", "transcribe.py": "parakeet_mlx", "live_step.py": "hands"}
    bad, where = [], []
    for script, mod in venvs.items():  # the projects scripts/run would use, worktree fallback included
        proj = Path(subprocess.run([str(HERE / "run"), "--which", script], capture_output=True, text=True).stdout.strip())
        where.append(str(proj))
        if not list((proj / ".venv").glob(f"lib/python3*/site-packages/{mod}*")):
            bad.append(f"{proj} ({mod})")
    report("STOP" if bad else "PASS", "venvs", f"missing or incomplete: {bad}; set ZPKT_ROOT to a checkout with them"
           if bad else ", ".join(where))
    free = shutil.disk_usage(Path.home()).free / 2**30
    report("STOP" if free < 3 else "WARN" if free < 8 else "PASS", "disk", f"{free:.1f} GB free",
           "disk" if free < 8 else "")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "selftest.json"
        r = subprocess.run([str(HERE / "run"), "selftest.py", "--json", str(out)], capture_output=True, text=True)
        if out.exists():
            s = json.loads(out.read_text())["summary"]
            report("PASS" if s["pass"] else "STOP", "selftest",
                   f"onset bias {s['onset_bias_ms_worst']} ms, max error {s['onset_max_abs_ms']} ms, "
                   f"recall {s['onset_recall_min']}", "" if s["pass"] else "selftest", value=s)
        else:
            report("STOP", "selftest", f"did not run: {(r.stderr or r.stdout).strip()[-200:]}", "selftest")


def foreign_prompts() -> None:
    from live_step import system_prompts

    try:
        front, prompts = system_prompts()
    except Exception as exc:  # noqa: BLE001 - a failed read is a warning, not a stop
        report("WARN", "system prompts", f"could not read System Events: {exc}")
        return
    if prompts:
        report("WARN", "system prompts", f"{len(prompts)} open. LOM steps are fine; steps that type (save-as, "
               "render) refuse until Anthony answers them: " + "; ".join(p[:90] for p in prompts), "foreign-prompt")
    else:
        report("PASS", "system prompts", "none open")
    report("PASS" if front == "Live" else "WARN", "front app", front, "" if front == "Live" else "foreign-prompt")


def orphans() -> None:
    ps = subprocess.run(["ps", "-axo", "pid=,etime=,command="], capture_output=True, text=True).stdout
    old = []
    for line in ps.splitlines():
        pid, etime, cmd = line.strip().split(None, 2)
        if "osascript" in cmd and "ps -axo" not in cmd:
            parts = etime.replace("-", ":").split(":")
            secs = sum(int(p) * m for p, m in zip(reversed(parts), (1, 60, 3600, 86400)))
            if secs > 60:
                old.append(f"pid {pid} ({etime}) {cmd[:60]}")
    report("WARN" if old else "PASS", "osascript", "; ".join(old) if old else "no long-running osascript",
           "orphaned-osascript" if old else "")


def audio_log(minutes: float) -> None:
    from hands import config

    log = config.rig().live_log
    if not log or not log.exists():
        report("WARN", "Live log", f"no Log.txt at {log}")
        return
    with log.open("rb") as f:
        f.seek(max(0, log.stat().st_size - (4 << 20)))
        tail = f.read().decode(errors="ignore").splitlines()
    since = datetime.now() - timedelta(minutes=minutes)
    hits = []
    for line in tail:
        if "Audio queue timeout" in line:
            try:
                if datetime.fromisoformat(line[:26]) >= since:
                    hits.append(line[:19])
            except ValueError:
                pass
    report("STOP" if hits else "PASS", "audio queue", f"{len(hits)} timeouts in the last {minutes:g} min, latest {hits[-1]}"
           if hits else f"no 'Audio queue timeout' in the last {minutes:g} min", "audio-stall" if hits else "")


def live(a) -> None:
    from hands.live import session, ui
    from hands.live.transport import LiveClient, LiveError

    if subprocess.run(["pgrep", "-x", "Live"], capture_output=True).returncode:
        report("STOP", "Live", "not running; start it (lib/rig/start_headless.sh) and rerun", "live-down")
        return
    try:
        other = session.other_agent_active(300)
        report("WARN" if other else "PASS", "other clients", "something used the Remote Script in the last 5 min; "
               "someone may be driving Live" if other else "no Remote Script connection in the last 5 min")
    except FileNotFoundError as exc:
        report("WARN", "other clients", str(exc))
    audio_log(a.log_minutes)
    client = LiveClient(timeout=10.0, retries=1)
    try:
        t = time.monotonic()
        client.run("result = 1")
        ping = time.monotonic() - t
        t = time.monotonic()
        tempo = client.run("result = song.tempo")
        read = time.monotonic() - t
        lvl = "STOP" if read > 3 else "WARN" if read > 1.5 else "PASS"
        report(lvl, "LOM", f"answers; read {read:.2f} s (connect {ping:.2f} s), tempo {tempo}",
               "audio-stall" if lvl != "PASS" else "")
    except LiveError as exc:
        report("STOP", "LOM", f"no answer: {exc}", "live-down")
        return
    try:
        wins = ui.windows()
        front = ui.front_title()
    except ui.UiError as exc:
        report("STOP", "windows", f"cannot read Live's windows: {exc}", "live-down")
        return
    dialogs = [(n, s) for n, s in wins if s == "AXDialog"]
    unnamed = [d for d in dialogs if d[0] in ("", "missing value")]
    if dialogs:
        report("STOP", "dialogs", f"{len(dialogs)} open: {dialogs}" + (" (unnamed: take a screenshot before anything "
               "else)" if unnamed else ""), "unnamed-dialog" if unnamed else "dialog")
    else:
        report("PASS", "dialogs", f"none; {len(wins)} window(s)")
    ours = bool(a.ours) and front == a.ours
    report("PASS", "front set", f"{front!r} ({'ours: writes allowed' if ours else 'not ours: read-only'})")
    try:
        save_on = ui.menu_enabled("File", "Save Live Set")
        edited = ui.osa(f'tell application "System Events" to tell process "{ui.PROCESS}" to tell front window to '
                        'get value of attribute "AXEdited" of (value of attribute "AXCloseButton")') == "true"
    except ui.UiError as exc:
        report("WARN", "dirty", f"could not read: {exc}")
        save_on = edited = None
    if save_on or edited:
        lvl = "WARN" if ours else "STOP"
        report(lvl, "dirty", f"unsaved changes (Save Live Set enabled={save_on}, AXEdited={edited})"
               + ("" if ours else ": not our set, so never save or discard it; tell the orchestrator"), "dirty-set")
    elif save_on is not None:
        report("PASS", "dirty", "clean (Save Live Set greyed out, AXEdited false)")
    try:
        mem = session.memory()
        lm = mem.get("live_mem_gb")
        report("WARN" if lm and lm > 5 else "PASS", "memory", f"Live {lm} GB, swap {mem['swap_used_gb']} GB",
               "restart" if lm and lm > 5 else "")
    except Exception as exc:  # noqa: BLE001 - memory is informational
        report("WARN", "memory", f"could not read: {exc}")
    if a.write_test or a.clock_test:
        if not ours:
            report("WARN", "write/clock test", f"skipped: the front set is not {a.ours!r}")
        elif dialogs or (save_on is None):
            report("WARN", "write/clock test", "skipped: fix the STOPs first")
        else:
            if a.write_test:
                t = time.monotonic()
                client.run("song.tempo = float(song.tempo)\nresult = 'ok'")
                w = time.monotonic() - t
                lvl = "STOP" if w > 3 else "WARN" if w > 1.5 else "PASS"
                report(lvl, "LOM write", f"{w:.2f} s for one harmless write", "audio-stall" if lvl != "PASS" else "")
            if a.clock_test:
                ok = session.audio_clock_ok(client)
                report("PASS" if ok else "STOP", "audio clock", "song time advances while playing" if ok else
                       "song time does not move: no audio device or a stalled engine", "audio-stall" if not ok else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=["scrape", "practice"], required=True)
    ap.add_argument("--ours", help="the set name this run created; only then may a test write or play")
    ap.add_argument("--write-test", action="store_true")
    ap.add_argument("--clock-test", action="store_true")
    ap.add_argument("--log-minutes", type=float, default=15.0)
    ap.add_argument("--json", help="write the results here (run.json keeps them)")
    a = ap.parse_args()
    tools(a.stage)
    if a.stage == "practice":
        foreign_prompts()
        orphans()
        live(a)
    stops = [r for r in results if r["level"] == "STOP"]
    print(f"\npreflight {a.stage}: {'STOP' if stops else 'GO'} ({len(stops)} stop, "
          f"{sum(r['level'] == 'WARN' for r in results)} warn)")
    if a.json:
        Path(a.json).expanduser().write_text(json.dumps({"stage": a.stage, "go": not stops, "at": datetime.now().isoformat(
            timespec="seconds"), "results": results}, indent=1) + "\n")
    sys.exit(1 if stops else 0)


if __name__ == "__main__":
    main()
