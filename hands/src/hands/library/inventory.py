"""Scan a library of Live projects and score each track's seven steps. Read-only: it lists folders, reads
.als files and, with measure=True, decodes at most a few master candidates.

A project is a folder directly under a root that holds a .als somewhere inside (Backup/ and Samples/
are skipped). The track is the folder's name without Live's " Project" suffix. Its sets are scored
newest first; the newest one's facts score every step except arrange, which takes the best set
(a Short is often cut in a set of its own).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from pathlib import Path
from typing import cast

from hands.library import records, score, workflow
from hands.library.facts import read_set
from hands.library.models import Inventory, StepKey, StepScore, TrackReport
from hands.library.score import Export, Project

ZPKT = Path(__file__).resolve().parents[4]
CENTRAL_RECORDS = ZPKT / "docs" / "inventory" / "records.toml"
BROWSER_PROJECTS = ZPKT / "prototypes" / "audio-browser" / "projects"
PRUNE = {"Backup", "Samples", "Ableton Project Info", ".git", "__MACOSX"}
SKIP_SET = re.compile(r"^(debug|ref|test|tmp|scratch)([_\- .]|$)", re.I)
AUDIO = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a", ".ogg", ".opus"}
VIDEO = {".mp4", ".mov", ".m4v", ".webm"}
EXPORT_WORDS = re.compile(r"master|mix|final|bounce|export|render|premaster|youtube|release|demo", re.I)
MASTER_WORDS = re.compile(r"(?<!pre)master|limited|lufs", re.I)
RELEASE_WORDS = re.compile(r"final|release|youtube|yt[_\- ]?short|upload", re.I)
MIX_WORDS = re.compile(r"mix|premaster|bounce|stem|full|demo", re.I)
MAX_MEASURED = 3

Measure = Callable[[Path], "dict | None"]


def track_name(folder: Path) -> str:
    return re.sub(r"\s+Project$", "", folder.name)


def token(name: str) -> re.Pattern:
    """Matches the track's name inside a file name, not inside a longer id (HW002 is not HW0021)."""
    return re.compile(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![0-9])")


def walk(folder: Path, depth: int = 6) -> Iterable[Path]:
    """Files under folder, skipping hidden files and Live's Backup/, Samples/ and Project Info folders."""
    base = len(folder.parts)
    for here, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in PRUNE and not d.startswith(".") and len(Path(here).parts) - base < depth]
        for f in files:
            if not f.startswith("."):
                yield Path(here) / f


def export_kind(path: Path) -> str:
    name = path.stem
    if path.suffix.lower() in VIDEO or RELEASE_WORDS.search(name):
        return "release"
    if MASTER_WORDS.search(name):
        return "master"
    if MIX_WORDS.search(name):
        return "mix"
    return "render"


def find_exports(name: str, folder: Path | None, set_stems: set[str], used: set[str], extra: Iterable[Path]) -> list[Export]:
    """Audio and video that look like renders of the track: in its folder, files that carry the track's name, a
    set's name or an export word and are not a sample a set plays; in the extra folders, files that carry the
    track's name."""
    tok = token(name)
    found: dict[Path, Export] = {}

    def add(f: Path) -> None:
        st = f.stat()
        found[f] = Export(f, st.st_size, st.st_mtime, export_kind(f))

    for f in walk(folder) if folder else ():
        if f.suffix.lower() not in AUDIO | VIDEO or f.name in used:
            continue
        if tok.search(f.stem.lower()) or f.stem in set_stems or EXPORT_WORDS.search(f.stem):
            add(f)
    for d in extra:
        for f in walk(d, depth=2) if d.is_dir() else ():
            if f.suffix.lower() in AUDIO | VIDEO and tok.search(f.stem.lower()):
                add(f)
    return sorted(found.values(), key=lambda e: -e.mtime)


def measure_mlab(path: Path) -> dict | None:
    """Integrated loudness, true peak and length of one file with ears/mlab's calibrated meter (a subprocess, so
    hands does not depend on mlab). None when mlab or uv is not there."""
    code = ("import json,sys;from mlab import io,loudness as L;a=io.load(sys.argv[1]);r=L.analyze(a.x,a.sr);"
            "print(json.dumps({'lufs':r.integrated,'true_peak':r.true_peak,'seconds':a.duration}))")
    mlab = ZPKT / "ears" / "mlab"
    if not mlab.is_dir():
        return None
    try:
        out = subprocess.run(["uv", "run", "--quiet", "--project", str(mlab), "python", "-c", code, str(path)],
                             capture_output=True, text=True, timeout=600, check=True)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def browser_projects(folder: Path | None) -> dict[str, dict]:
    """audio-browser project documents by name (lower case)."""
    out = {}
    for f in sorted(folder.glob("*.json")) if folder and folder.is_dir() else []:
        try:
            doc = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("name"):
            out[str(doc["name"]).lower()] = doc
    return out


def load_project(folder: Path, others: set[str], skipped: list[str]) -> Project:
    p = Project(track_name(folder), folder)
    sets = [f for f in walk(folder) if f.suffix == ".als"]
    for f in sorted(sets, key=lambda f: -f.stat().st_mtime):
        if SKIP_SET.search(f.stem):
            skipped.append(f"{p.name}/{f.name}: a debug or reference set")
            continue
        try:
            p.sets.append(read_set(f))
        except (ValueError, OSError, EOFError) as exc:
            skipped.append(f"{p.name}/{f.name}: unreadable ({exc.__class__.__name__})")
    if p.current is not None:
        for t in p.current.tracks:
            for path in [c.sample for c in t.clips] + t.rack_samples:
                parts = set(path.replace("\\", "/").split("/"))
                for other in parts & others:
                    p.forked_from[track_name(Path(other))] = p.forked_from.get(track_name(Path(other)), 0) + 1
    return p


def score_project(p: Project, central: dict, notes: dict) -> TrackReport:
    recs = dict(central.get(p.name.lower(), {}))
    own, own_note = records.load_project(p.folder)
    recs.update(own)
    steps = []
    for s in workflow.STEPS:
        heuristic, ev = score.SCORERS[s.key](p)
        rec = recs.get(s.key)
        if rec is not None:
            line = f"record ({rec.by}{', ' + rec.date if rec.date else ''}): {rec.note or 'no note'}"
            line += f" [{rec.source}]" if rec.source else ""
            line += f" {rec.url}" if rec.url else ""
            ev = [line] + [f"heuristic {heuristic}%: " + "; ".join(ev)]
        steps.append(StepScore(step=cast(StepKey, s.key), numeral=s.numeral, percent=rec.percent if rec else heuristic,
                               heuristic=heuristic, record=rec, evidence=ev))
    percents: dict[str, int] = {x.step: x.percent for x in steps}
    track_notes = [n for n in (notes.get(p.name.lower()), own_note) if n]
    if p.forked_from:
        track_notes.append("plays samples from another project's folder ("
                           + ", ".join(f"{k}: {v}" for k, v in p.forked_from.items()) + "): likely a copy of it")
    cur = p.current
    return TrackReport(
        track=p.name, folder=str(p.folder) if p.folder else None, set=cur.path.name if cur else None,
        sets=len(p.sets), last_saved=date.fromtimestamp(cur.mtime).isoformat() if cur else None,
        lowest_incomplete=cast("StepKey | None", workflow.lowest_incomplete(percents)),
        overall=round(sum(percents.values()) / len(percents)), steps=steps, notes=track_notes)


def sort_key(t: TrackReport) -> tuple:
    """Most advanced first: by lowest incomplete step, then by how far along that step is, then overall."""
    idx = workflow.KEYS.index(t.lowest_incomplete) if t.lowest_incomplete else len(workflow.KEYS)
    at = next((s.percent for s in t.steps if s.step == t.lowest_incomplete), 100)
    return (-idx, -at, -t.overall, t.track.lower())


def inventory(roots: Iterable[Path], *, exports: Iterable[Path] = (), records_file: Path | None = CENTRAL_RECORDS,
              browser: Path | None = BROWSER_PROJECTS, measure: Measure | None = None) -> Inventory:
    """Scan every root, score every project, apply records. measure (e.g. measure_mlab) reads loudness of up to
    three master candidates per track."""
    roots = [Path(r).expanduser() for r in roots]
    exports = [Path(e).expanduser() for e in exports]
    central, notes, statuses = records.load_central(records_file)
    docs = browser_projects(browser)
    skipped: list[str] = []
    projects: list[Project] = []
    for root in roots:
        if not root.is_dir():
            skipped.append(f"{root}: not a folder")
            continue
        folders = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))
        names = {d.name for d in folders}
        for d in folders:
            if not any(f.suffix == ".als" for f in walk(d)):
                skipped.append(f"{root.name}/{d.name}: no Live set")
                continue
            projects.append(load_project(d, names - {d.name}, skipped))
    live = []
    for p in projects:                      # a canceled track is out of the inventory (the project file wins)
        status = records.project_status(p.folder) or statuses.get(p.name.lower(), "")
        if status == "canceled":
            note = notes.get(p.name.lower(), "")
            skipped.append(f"{p.name}: canceled" + (f" ({note})" if note else ""))
        else:
            live.append(p)
    projects = live
    known = {p.name.lower() for p in projects} | set(statuses)
    for p in projects:
        p.browser = docs.get(p.name.lower())
    for name, doc in docs.items():
        if name not in known and not doc.get("abandoned"):
            projects.append(Project(str(doc["name"]), None, browser=doc))
    for p in projects:
        used = {Path(x).name for s in p.sets for t in s.tracks for x in [c.sample for c in t.clips] + t.rack_samples}
        p.exports = find_exports(p.name, p.folder, {s.path.stem for s in p.sets}, used, exports)
        if measure is not None:
            cands = [e for e in p.exports if e.kind in ("master", "release") and e.path.suffix.lower() in AUDIO]
            for e in cands[:MAX_MEASURED]:
                if m := measure(e.path):
                    e.lufs, e.true_peak, e.seconds = m.get("lufs"), m.get("true_peak"), m.get("seconds")
    reports = sorted((score_project(p, central, notes) for p in projects), key=sort_key)
    return Inventory(generated=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     roots=[str(r) for r in roots], tracks=reports, skipped=skipped)


def step_label(key: str | None) -> str:
    if key is None:
        return "released"
    s = workflow.BY_KEY[key]
    return f"{s.numeral}. {s.name}"


def markdown(inv: Inventory, evidence: bool = True) -> str:
    """The inventory as a Markdown table, then each track's evidence."""
    head = "| Track | Lowest incomplete | " + " | ".join(s.numeral for s in workflow.STEPS) + " | Set |"
    rule = "|---|---|" + "---:|" * len(workflow.STEPS) + "---|"
    rows = []
    for t in inv.tracks:
        cells = [f"{x.percent}{'*' if x.record else ''}" for x in t.steps]
        rows.append(f"| {t.track} | {step_label(t.lowest_incomplete)} | " + " | ".join(cells)
                    + f" | {t.set or '—'} |")
    out = [head, rule, *rows, "", "`*` = set by a record (records.toml), not the heuristic."]
    if evidence:
        for t in inv.tracks:
            out += ["", f"### {t.track}", ""]
            meta = f"{t.sets} sets, newest `{t.set}` saved {t.last_saved}." if t.set else "No Live set."
            out.append(f"Lowest incomplete: **{step_label(t.lowest_incomplete)}**. Overall {t.overall} %. {meta}")
            for n in t.notes:
                out.append(f"\n> {n}")
            out.append("")
            for x in t.steps:
                out.append(f"- **{x.numeral}. {workflow.BY_KEY[x.step].name} {x.percent} %**: " + "; ".join(x.evidence))
    if inv.skipped:
        out += ["", "Not scored:", ""] + [f"- {s}" for s in inv.skipped]
    return "\n".join(out) + "\n"
