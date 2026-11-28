"""Run the persona walkthrough: a cold agent makes a track through the zpkt app only (Anthony, 27 November 2026).

Each leg is a fresh agent (`claude -p`) that has only browser_mcp.py's tools: the app in a browser, a journal, a
notebook and checkpoints. A leg can start from any checkpoint of an earlier leg, so a scenario can be run again from
the middle without starting over.

    python run.py new [--name melodic]                     # a run folder; prints its path
    python run.py leg RUN 1                                # leg 1 from nothing
    python run.py leg RUN 2 --from RUN/checkpoints/01-drums  # leg 2 from a checkpoint (a copy of the song is opened)
    python run.py legs                                     # the legs and their goals

The journal page (serve.py) shows every run as it is written.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = Path(os.environ.get("WT_RUNS", "~/Music/zpkt/walkthrough/runs")).expanduser()
SETS = Path(os.environ.get("WT_SETS", "~/Music/zpkt/sets")).expanduser()
MODEL = os.environ.get("WT_MODEL", "claude-sonnet-5-5")
PY = sys.executable

LEGS = {
    1: "Recipe steps 1 and 2: make a new song of your own (call it something you would call a track), set it up "
    "(tempo, key), and build the 8-bar drum loop. Save, notebook, checkpoint 'drums'.",
    2: "Recipe steps 3 and 4: the bass and the chords. Save, notebook, checkpoint 'bass and chords'.",
    3: "Recipe steps 5 and 6: the lead and the arrangement. Save, notebook, checkpoint 'arrangement'.",
    4: "Recipe steps 7 and 8: mix and bounce, then judge the whole evening: what you made, what the app helped with, "
    "what stopped you. Save, notebook, checkpoint 'mix', then finish with that judgement.",
}


def new_run(name: str) -> Path:
    run = RUNS / f"{time.strftime('%Y%m%d-%H%M')}-{name}"
    run.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps({"name": name, "started": time.time(), "model": MODEL, "legs": []}, indent=2)
    )
    (run / "journal.jsonl").touch()
    return run


def restore(checkpoint: Path, leg: int) -> str:
    """Copy the checkpoint's song to a new song file, put it in the app's list and open it in Live. Its name."""
    meta = json.loads((checkpoint / "checkpoint.json").read_text())
    src = checkpoint / f"{meta['song']}.als"
    name = f"{meta['song']}_r{time.strftime('%H%M%S')}"
    shutil.copy2(src, SETS / f"{name}.als")
    index = json.loads((SETS / "songs.json").read_text())
    title = next((s["title"] for s in index["songs"] if s["name"] == meta["song"]), meta["song"])
    index["songs"].append({"name": name, "title": f"{title} (from {checkpoint.name})", "desk": False})
    (SETS / "songs.json").write_text(json.dumps(index, indent=2) + "\n")
    from zpkt.app.client import AppClient

    code, body = AppClient().submit("song.open", {"name": name})
    if code != 200:
        raise SystemExit(f"could not open the restored song: {body}")
    return name


def prompt_for(run: Path, leg: int, start: str) -> str:
    notes = run / "notes.md"
    lines = [json.loads(x) for x in (run / "journal.jsonl").read_text().splitlines() if x.strip()]
    told = [f"- leg {r['leg']} {r['kind']}: {r['title']}" for r in lines if r["kind"] not in ("tool", "tool-error")]
    past = "\n".join(told[-40:]) or "(nothing yet: this is the first leg)"
    return f"""{(HERE / "persona.md").read_text()}

## This leg: {leg}

Goal: {LEGS[leg]}

Where you start: {start}

Your notebook from earlier legs (you wrote it; you remember nothing else):

{notes.read_text() if notes.exists() else "(empty)"}

The titles of your journal so far:

{past}

Begin with open_app, then look. Write a `plan` entry first.
"""


def run_leg(run: Path, leg: int, frm: Path | None, max_turns: int) -> int:
    start = "a fresh start: no song of yours exists yet."
    if frm:
        name = restore(frm, leg)
        start = f"your song as kept at checkpoint {frm.name}, opened in the app as a copy ({name})."
    mcp = {
        "mcpServers": {
            "wt": {"command": PY, "args": [str(HERE / "browser_mcp.py"), "--run", str(run), "--leg", str(leg)]}
        }
    }
    work = run / f"leg{leg}"
    work.mkdir(exist_ok=True)
    (work / "mcp.json").write_text(json.dumps(mcp))
    meta = json.loads((run / "run.json").read_text())
    meta["legs"].append({"leg": leg, "from": frm.name if frm else None, "started": time.time(), "model": MODEL})
    (run / "run.json").write_text(json.dumps(meta, indent=2))
    with (run / "journal.jsonl").open("a") as f:
        f.write(
            json.dumps(
                {
                    "at": time.time(),
                    "leg": leg,
                    "kind": "leg",
                    "title": f"Leg {leg} starts",
                    "body": f"{LEGS[leg]}\n\nStart: {start}",
                }
            )
            + "\n"
        )
    cmd = [
        "claude",
        "-p",
        prompt_for(run, leg, start),
        "--model",
        MODEL,
        "--mcp-config",
        str(work / "mcp.json"),
        "--strict-mcp-config",
        "--setting-sources",
        "project",
        "--allowedTools",
        "mcp__wt",
        "--disallowedTools",
        "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task,Agent,NotebookEdit,TodoWrite,Skill",
        "--permission-mode",
        "dontAsk",
        "--max-turns",
        str(max_turns),
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    with (work / "transcript.jsonl").open("w") as out, (work / "stderr.log").open("w") as err:
        code = subprocess.run(
            cmd, cwd=work, stdout=out, stderr=err, env={**os.environ, "WT_SETS": str(SETS)}
        ).returncode
    meta = json.loads((run / "run.json").read_text())
    meta["legs"][-1] |= {"ended": time.time(), "exit": code}
    (run / "run.json").write_text(json.dumps(meta, indent=2))
    with (run / "journal.jsonl").open("a") as f:
        f.write(
            json.dumps(
                {"at": time.time(), "leg": leg, "kind": "leg", "title": f"Leg {leg} ends (exit {code})", "body": ""}
            )
            + "\n"
        )
    return code


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--name", default="melodic")
    lg = sub.add_parser("leg")
    lg.add_argument("run", type=Path)
    lg.add_argument("leg", type=int, choices=sorted(LEGS))
    lg.add_argument("--from", dest="frm", type=Path)
    lg.add_argument("--max-turns", type=int, default=160)
    sub.add_parser("legs")
    a = ap.parse_args()
    if a.cmd == "new":
        print(new_run(a.name))
    elif a.cmd == "legs":
        for k, v in LEGS.items():
            print(f"{k}. {v}")
    else:
        raise SystemExit(run_leg(a.run.resolve(), a.leg, a.frm.resolve() if a.frm else None, a.max_turns))


if __name__ == "__main__":
    main()
