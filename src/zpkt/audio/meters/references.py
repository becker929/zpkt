"""References: the finished tracks a mix is measured against, and how mlab identifies each one.

Two forms reach mlab, and each is read here and nowhere else:

- A refs.json (written by the arranger, contrib/arranger/refs.py): {"refs": [{"id", "file", "drop", "barSeconds",
  "title"?, "bpm"?, "set"?}]}. `id` names the reference in every report; `drop` (s) and `barSeconds` place its build
  and drop windows; `set` groups references for one track (e.g. "hw002"). `target` and `eqfit` read it.
- A folder of audio files. Each file is a reference, named by its file name without the extension, cut to the width
  each report sets. `refs` and `review` read it.
"""

from __future__ import annotations

import glob
import json
import os
from pathlib import Path
from typing import Any, TypedDict, cast

AUDIO_EXTENSIONS = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".m4a")
REQUIRED = ("file", "drop", "barSeconds")


class _ReferenceFields(TypedDict):
    file: str
    drop: float
    barSeconds: float  # the refs.json key, kept as written
    path: str  # file, joined to the folder it is relative to
    bar_s: float  # barSeconds as a float


class Reference(_ReferenceFields, total=False):
    """One refs.json entry as mlab uses it. Keys it does not know are kept as they are."""

    id: str
    title: str
    bpm: float
    set: str


def parse_refs(data: Any, source: str, set_name: str | None = None, base_dir: str = "") -> list[Reference]:
    """The entries of a refs.json document (only those whose set is set_name, when given), each with `path` (file
    joined to base_dir), `drop` and `bar_s` as floats. Raises ValueError naming the entry when one cannot be used."""
    if not isinstance(data, dict):
        raise ValueError(f'{source}: expected {{"refs": [...]}}, got {type(data).__name__}')
    out: list[Reference] = []
    for i, entry in enumerate(data.get("refs", [])):
        if not isinstance(entry, dict):
            raise ValueError(f"{source}: reference {i} is a {type(entry).__name__}, not an object")
        if set_name and entry.get("set") != set_name:
            continue
        name = entry.get("id", i)
        missing = [key for key in REQUIRED if key not in entry]
        if missing:
            raise ValueError(
                f"{source}: reference {name} has no {', '.join(missing)}; each needs file, drop, barSeconds"
            )
        try:
            drop, bar_s = float(entry["drop"]), float(entry["barSeconds"])
        except (TypeError, ValueError):
            raise ValueError(
                f"{source}: reference {name}: drop and barSeconds must be seconds, got "
                f"{entry['drop']!r} and {entry['barSeconds']!r}"
            ) from None
        path = os.path.join(base_dir, entry["file"])
        out.append(cast(Reference, {**entry, "path": path, "drop": drop, "bar_s": bar_s}))
    return out


def load_refs(path: str, set_name: str | None = None, base_dir: str | None = None) -> list[Reference]:
    """parse_refs() of a refs.json file. `file` is relative to the JSON's folder unless base_dir is given."""
    with open(path) as fh:
        data = json.load(fh)
    return parse_refs(data, path, set_name, base_dir or os.path.dirname(os.path.abspath(path)))


def reference_files(folder: str) -> list[str]:
    """The audio files directly in a folder of references, sorted by path; nothing when the folder is missing."""
    return [
        p for p in sorted(glob.glob(os.path.join(folder, "*"))) if os.path.splitext(p)[1].lower() in AUDIO_EXTENSIONS
    ]


def reference_name(path: str, width: int) -> str:
    """A reference's name in a report: its file name without the extension, cut to `width` characters."""
    return Path(path).stem[:width]
