"""Validate a recipe.json against reference/recipe.schema.json and check its conversions.

    run recipe_check.py recipe.json                       # the scrape's private recipe
    run recipe_check.py docs/techniques/<slug>.recipe.json --public
    run recipe_check.py recipe.json --tables              # Markdown note tables for RECIPE.md

Checks:
- the schema (a small built-in validator for the keywords the schema uses);
- every note's live_position against its start_beat (loop at 1.1.1), its tutorial_position against
  global.loop.tutorial_start, and pitch_live / pitch_sci against the MIDI number (Live C3 = 60,
  scientific C4 = 60);
- --public (or "public": true): no private fields (reason, heard, quote, evidence), no quoted span
  over five words, no paths into the run's frames, crops, analysis or src.
Exit 1 on any error. Prose claims should come from these tables, not be written freehand.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import note_names, position  # noqa: E402

SCHEMA = Path(__file__).resolve().parent.parent / "reference" / "recipe.schema.json"
PRIVATE_KEYS = {"reason", "heard", "quote", "quotes", "evidence"}
QUOTE_RE = re.compile(r"[\"“]([^\"”]+)[\"”]")
PATH_RE = re.compile(r"\b(frames|crops|analysis|src)/|\.(png|jpe?g|mp4|wav|json3)\b")
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is(value, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, TYPES[t])


def validate(v, s: dict, root: dict, path: str = "$") -> list[str]:
    """The subset of JSON Schema the recipe schema uses."""
    if "$ref" in s:
        ref = s["$ref"]
        if not ref.startswith("#/"):
            raise SystemExit(f"{path}: only local $refs are supported ({ref})")
        s = root
        for part in ref[2:].split("/"):
            s = s[part]
    errs: list[str] = []
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must be {s['const']!r}")
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_is(v, t) for t in ts):
            return [f"{path}: expected {'/'.join(ts)}, got {type(v).__name__}"]
    if isinstance(v, str) and "pattern" in s and not re.search(s["pattern"], v):
        errs.append(f"{path}: {v[:40]!r} does not match {s['pattern']}")
    if _is(v, "number"):
        if "minimum" in s and v < s["minimum"]:
            errs.append(f"{path}: {v} < {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            errs.append(f"{path}: {v} > {s['maximum']}")
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            errs.append(f"{path}: {v} <= {s['exclusiveMinimum']}")
    if isinstance(v, dict):
        errs += [f"{path}: missing {k!r}" for k in s.get("required", []) if k not in v]
        for k, sub in v.items():
            if k in s.get("properties", {}):
                errs += validate(sub, s["properties"][k], root, f"{path}.{k}")
                continue
            pats = [ps for p, ps in s.get("patternProperties", {}).items() if re.search(p, k)]
            for ps in pats:
                errs += validate(sub, ps, root, f"{path}.{k}")
            extra = s.get("additionalProperties", True)
            if not pats and isinstance(extra, dict):
                errs += validate(sub, extra, root, f"{path}.{k}")
            elif not pats and extra is False:
                errs.append(f"{path}: unexpected key {k!r}")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            errs.append(f"{path}: fewer than {s['minItems']} items")
        if "items" in s:
            for i, item in enumerate(v):
                errs += validate(item, s["items"], root, f"{path}[{i}]")
    return errs


def conversions(r: dict) -> list[str]:
    errs = []
    tut = (r.get("global", {}).get("loop") or {}).get("tutorial_start")
    tut_bar = int(tut.split(".")[0]) if tut else None
    for key, notes in (r.get("notes") or {}).items():
        if not isinstance(notes, list):
            continue
        for i, n in enumerate(notes):
            if not isinstance(n, dict) or "start_beat" not in n:
                continue
            where = f"notes.{key}[{i}]"
            if "live_position" in n and n["live_position"] != position(n["start_beat"]):
                errs.append(f"{where}: live_position {n['live_position']} != {position(n['start_beat'])}")
            if "tutorial_position" in n and tut_bar and n["tutorial_position"] != position(n["start_beat"], tut_bar):
                errs.append(f"{where}: tutorial_position {n['tutorial_position']} != {position(n['start_beat'], tut_bar)}")
            if "pitch" in n:
                names = note_names(n["pitch"])
                for k, conv in (("pitch_live", "live"), ("pitch_sci", "sci")):
                    if k in n and n[k] != names[conv]:
                        errs.append(f"{where}: {k} {n[k]} != {names[conv]} (MIDI {n['pitch']})")
    return errs


def strings(v, path: str = "$"):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from strings(x, f"{path}[{i}]")


def keys(v, path: str = "$"):
    if isinstance(v, dict):
        for k, x in v.items():
            yield f"{path}.{k}", k
            yield from keys(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from keys(x, f"{path}[{i}]")


def public_errors(r: dict) -> list[str]:
    errs = [f"{p}: private field {k!r} in a public recipe" for p, k in keys(r) if k in PRIVATE_KEYS]
    for p, s in strings(r):
        for q in QUOTE_RE.findall(s):
            if len(q.split()) > 5:
                errs.append(f"{p}: quote over five words: \"{q[:60]}\"")
        if PATH_RE.search(s) and not p.startswith("$.source"):
            errs.append(f"{p}: points into the run's private files: {s[:60]!r}")
    if not r.get("technique"):
        errs.append("$: a public recipe needs 'technique' (slug, name, summary, why)")
    return errs


def tables(r: dict) -> str:
    out = []
    for key, notes in (r.get("notes") or {}).items():
        if not isinstance(notes, list) or not notes or "pitch" not in notes[0]:
            continue
        out += [f"### {key}", "", "| # | Pitch | Start beat | Length | Velocity | Position |", "|---|---|---|---|---|---|"]
        for i, n in enumerate(notes, 1):
            nm = note_names(n["pitch"])
            out.append(f"| {i} | {n['pitch']} ({nm['live']} Live / {nm['sci']} sci) | {n['start_beat']:g} | "
                       f"{n['length_beats']:g} | {n['velocity']} | {position(n['start_beat'])} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe")
    ap.add_argument("--public", action="store_true", help="apply the public-repo rules")
    ap.add_argument("--tables", action="store_true", help="print Markdown note tables")
    a = ap.parse_args()
    r = json.loads(Path(a.recipe).read_text())
    schema = json.loads(SCHEMA.read_text())
    errs = validate(r, schema, schema) + conversions(r)
    if a.public or r.get("public"):
        errs += public_errors(r)
    if a.tables:
        print(tables(r))
    n_notes = sum(len(v) for v in (r.get("notes") or {}).values() if isinstance(v, list))
    for e in errs:
        print(f"ERROR {e}")
    print(f"{a.recipe}: {len(r.get('steps', []))} steps, {n_notes} notes, {len(errs)} errors"
          f"{' (public rules)' if a.public or r.get('public') else ''}")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
