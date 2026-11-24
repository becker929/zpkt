"""Storage sweeping: delete the files hands made that nothing can need again, so renders do not fill the disk.

Three kinds of file are swept, and nothing else is ever touched:

  take        Live's own recording of a render ("Render 0001 [2026-11-18 182434].wav" and its .asd, in the
              project's Samples/Recorded). hands copies the take out and deletes it, but a render that failed, or
              an older hands, leaves it behind. Kept if any Live set in the project uses it, or the open set does.
  scratch     the hidden working copy of a take in the renders folder (.NAME.take.wav).
  superseded  renders a panel or song has moved on from: every version but its last two (the before/after
              deck), and every grid but its newest. Grid files of a panel that no longer exists count too.
              These go only once they are KEEP_DAYS old, or at once when the disk is nearly full.

The last render of everything, anything hands did not name, and anything younger than an hour stay.

  hands sweep                    what would go, and how much space it is
  hands sweep --apply            delete it
  hands sweep --project DIR      also look for takes in this Live project

Every render calls make_room first: under LOW free it sweeps, and if there is still not room for the take it
refuses, because Live crashes when it cannot write a recording.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hands.live import hold

TAKE = re.compile(r"Render \d{4} \[\d{4}-\d{2}-\d{2} \d{6}\]\.wav")
_TAKE_B = re.compile(TAKE.pattern.encode())
GRID = re.compile(r"^(?P<panel>.+)-g(?P<id>\d+)-[a-p](?:-m)?\.wav$")
KEEP_DAYS = 7.0
SETTLE = 3600.0  # seconds: nothing younger is swept (a render may be under way)
LOW = 2 * 2**30  # bytes free under which a render sweeps first
FLOOR = 300 * 2**20  # bytes that must stay free beside the take
TAKE_BYTES_PER_SECOND = 400_000  # Live records 32-bit float stereo


def free_bytes(path: Path) -> int:
    p = Path(path).resolve()
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def _memo(out_dir: Path) -> Path:
    return out_dir / ".sweep.json"


def _read(out_dir: Path) -> dict[str, Any]:
    try:
        m = json.loads(_memo(out_dir).read_text())
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(out_dir: Path, memo: dict[str, Any]) -> None:
    try:
        _memo(out_dir).write_text(json.dumps(memo))
    except OSError:
        pass


def note_takes(out_dir: Path, folder: Path) -> None:
    """Remember where Live put a take, so a later sweep looks there even when Live is closed."""
    memo = _read(out_dir)
    known = memo.setdefault("takes", [])
    if str(folder) not in known:
        known.append(str(folder))
        _write(out_dir, memo)


def _project_of(folder: Path) -> Path:
    """The Live project a Samples/Recorded folder belongs to (the folder itself if it is not laid out that way)."""
    return folder.parent.parent if folder.name == "Recorded" and folder.parent.name == "Samples" else folder


def used_by_sets(project: Path, memo: dict[str, Any]) -> set[str]:
    """The take names any Live set under the project refers to. Sets are read once and remembered by date and size."""
    seen = memo.setdefault("sets", {})
    names: set[str] = set()
    found = set()
    for als in project.rglob("*.als"):
        try:
            st = als.stat()
        except OSError:
            continue
        key, stamp = str(als), [st.st_mtime, st.st_size]
        found.add(key)
        hit = seen.get(key)
        if not hit or hit[0] != stamp:
            try:
                data = gzip.open(als).read()
            except (OSError, EOFError):
                try:
                    data = als.read_bytes()
                except OSError:
                    data = b""
            hit = seen[key] = [stamp, sorted({m.decode() for m in _TAKE_B.findall(data)})]
        names.update(hit[1])
    for gone in [k for k in seen if k.startswith(str(project)) and k not in found]:
        del seen[gone]
    return names


def _names(shown: object) -> list[str]:
    return [Path(shown).name] if isinstance(shown, str) and shown else []


def _grid_files(g: dict[str, Any]) -> list[str]:
    return [
        n for o in g.get("options") or [] if isinstance(o, dict) for k in ("file", "matched") for n in _names(o.get(k))
    ]


def plan(
    out_dir: Path,
    projects: list[Path] | None = None,
    *,
    keep_days: float = KEEP_DAYS,
    pressure: bool = False,
    in_use: set[str] | None = None,
    now: float | None = None,
    memo: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """What a sweep would delete: [{path, bytes, kind, why}], biggest first. Deletes nothing."""
    out_dir = Path(out_dir)
    now = time.time() if now is None else now
    memo = _read(out_dir) if memo is None else memo
    in_use = in_use or set()
    old = SETTLE if pressure else max(SETTLE, keep_days * 86400.0)
    items: dict[str, dict[str, Any]] = {}
    here = out_dir.is_dir()

    def add(p: Path, kind: str, why: str, age: float) -> None:
        try:
            st = p.stat()
        except OSError:
            return
        if p.is_file() and now - st.st_mtime >= age and str(p) not in items:
            items[str(p)] = {"path": str(p), "bytes": st.st_size, "kind": kind, "why": why}

    keep: set[str] = set()
    spent: list[tuple[str, str]] = []
    panels: set[str] = set()
    for f in (sorted(out_dir.glob("*.panel.json")) + sorted(out_dir.glob("*.song.json"))) if here else []:
        if f.name.endswith(".panel.json"):
            panels.add(f.name[: -len(".panel.json")])  # even if its file cannot be read: its grids are not orphans
        try:
            made = json.loads(f.read_text())
            name = str(made.get("name") or f.name.split(".")[0])
            renders = [n for r in made.get("renders") or [] for n in _names(r)]
            grids = [g for g in made.get("grids") or [] if isinstance(g, dict)]
            newest = _grid_files(grids[-1]) if grids else []
            older = [(n, f"grid {g.get('id')} of {name}, not its newest") for g in grids[:-1] for n in _grid_files(g)]
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            continue  # a damaged file: nothing it names is swept on its word
        if f.name.endswith(".panel.json"):
            panels.add(name)
        keep.update(renders[-2:])
        spent += [(n, f"an earlier version of {name}") for n in renders[:-2]]
        keep.update(newest)
        spent += older
    for name, why in spent:
        if name not in keep:
            add(out_dir / name, "superseded", why, old)
    for f in out_dir.glob("*-g*-*.wav") if here else []:
        m = GRID.match(f.name)
        if m and m["panel"] not in panels and f.name not in keep:
            add(f, "superseded", f"a grid of {m['panel']}, a panel that is gone", old)
    for f in out_dir.glob(".*.take.wav*") if here else []:
        add(f, "scratch", "the working copy of a take", SETTLE)

    folders = [Path(p) for p in memo.get("takes") or []]
    for p in projects or []:
        p = Path(p)
        folders.append(p / "Samples" / "Recorded" if (p / "Samples" / "Recorded").is_dir() else p)
    for folder in dict.fromkeys(f.resolve() for f in folders if f.is_dir()):
        used = None
        for f in sorted(folder.iterdir()):
            wav = f.name[:-4] if f.name.endswith(".asd") else f.name
            if not TAKE.fullmatch(wav):
                continue
            if used is None:
                used = used_by_sets(_project_of(folder), memo)
            if wav in used or str(folder / wav) in in_use:
                continue
            add(f, "take", "a recording of a render that no Live set uses", SETTLE)
    return sorted(items.values(), key=lambda i: -i["bytes"])


def _mark_swept(out_dir: Path, gone: set[str]) -> None:
    """A grid whose files went cannot be picked from any more; say so in the panel's file."""
    for f in out_dir.glob("*.panel.json"):
        try:
            made = json.loads(f.read_text())
            hit = False
            for g in made.get("grids") or []:
                if isinstance(g, dict) and not g.get("swept") and any(n in gone for n in _grid_files(g)):
                    g["swept"], hit = True, True
            if hit:
                hold.save_json(f, made)
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            continue


def sweep(
    out_dir: Path,
    projects: list[Path] | None = None,
    *,
    apply: bool = False,
    keep_days: float = KEEP_DAYS,
    pressure: bool = False,
    in_use: set[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Plan a sweep and, with apply, carry it out. Returns {applied, files, bytes, kinds, items, free}."""
    out_dir = Path(out_dir)
    memo = _read(out_dir)
    items = plan(out_dir, projects, keep_days=keep_days, pressure=pressure, in_use=in_use, now=now, memo=memo)
    if out_dir.is_dir():
        _write(out_dir, memo)
    done = []
    for it in items:
        if apply:
            try:
                Path(it["path"]).unlink()
            except OSError:
                continue
        done.append(it)
    if apply and done:
        _mark_swept(out_dir, {Path(i["path"]).name for i in done if Path(i["path"]).parent == out_dir})
    kinds: dict[str, dict[str, Any]] = {}
    for it in done:
        k = kinds.setdefault(it["kind"], {"files": 0, "bytes": 0})
        k["files"] += 1
        k["bytes"] += it["bytes"]
    return {
        "applied": apply,
        "files": len(done),
        "bytes": sum(i["bytes"] for i in done),
        "kinds": kinds,
        "items": done,
        "free": free_bytes(out_dir),
        "low": LOW,
    }


def size(n: float) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB" if n >= 2**20 else f"{n / 1024:.0f} KB"


def report(result: dict[str, Any], shown: int = 12) -> str:
    verb = "deleted" if result["applied"] else "would delete"
    if not result["files"]:
        return f"nothing to sweep; {size(result['free'])} free"
    lines = [
        f"{verb} {result['files']} files, {size(result['bytes'])}; {size(result['free'])} free"
        + ("" if result["applied"] else " now (run again with --apply to delete them)")
    ]
    for kind, k in sorted(result["kinds"].items(), key=lambda kv: -kv[1]["bytes"]):
        lines.append(f"  {kind}: {k['files']} files, {size(k['bytes'])}")
    for it in result["items"][:shown]:
        lines.append(f"    {size(it['bytes']):>7}  {it['path']}  ({it['why']})")
    if result["files"] > shown:
        lines.append(f"    … and {result['files'] - shown} smaller ones")
    return "\n".join(lines)


def make_room(out_dir: Path, seconds: float = 0.0, *, free: Callable[[Path], int] = free_bytes) -> None:
    """Before a recording of `seconds`: sweep if the disk is low, refuse if there is still not room for the take."""
    from hands.live.panel import PanelError

    out_dir = Path(out_dir)
    need = FLOOR + int(seconds * TAKE_BYTES_PER_SECOND) * 2  # Live's take, and the copy hands cuts from
    have = free(out_dir)
    if have >= max(LOW, need):
        return
    result = sweep(out_dir, apply=True, pressure=True)
    have = free(out_dir)
    if have < need:
        raise PanelError(
            f"not rendering: only {size(have)} is free on this disk"
            + (f" after sweeping {size(result['bytes'])} of old renders" if result["bytes"] else "")
            + f", and this take needs {size(need)}. Live crashes when it cannot write a recording. "
            "Free some space and render again (`hands sweep --project DIR` shows what hands can delete)"
        )
