"""Records: a step's state on Anthony's word, or from a decision written down in zpkt docs. They beat the heuristic.

Two places, same shape. The central file (docs/inventory/records.toml in zpkt) keys tables by track:

    [HW002]
    note = "the Short is cut from the full track"

    [HW002.arrange]
    percent = 80
    by = "docs"
    note = "canonical shape chosen (batch 4.3 track 1); chord loop still missing"
    source = "docs/hw002/batch-4.3-4.4-decisions.md"
    date = "2026-10-06"

    [HW002.release]
    percent = 100
    url = "https://youtube.com/shorts/..."

A project folder may hold its own `zpkt-workflow.toml` with the step tables at the top level
(`[arrange]`, ...). Anthony writes that one, so it wins over the central file. Agents never write
into the library; they add to the central file, in a PR.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from hands.library import workflow
from hands.library.models import Record

PROJECT_FILE = "zpkt-workflow.toml"


def _steps(table: dict[str, Any], where: str, default_by: str) -> dict[str, Record]:
    out = {}
    for key, value in table.items():
        if key == "note":
            continue
        if key not in workflow.KEYS or not isinstance(value, dict):
            raise ValueError(f"{where}: unknown step {key!r}; steps are {', '.join(workflow.KEYS)}")
        value = {k: str(v) if k == "date" else v for k, v in value.items()}  # TOML dates are dates
        out[key] = Record.model_validate({"by": default_by, **value})
    return out


def load_central(path: str | Path | None) -> tuple[dict[str, dict[str, Record]], dict[str, str]]:
    """{track (lower case): {step: Record}} and {track: note} from the central file; empty if it is missing."""
    if path is None or not Path(path).is_file():
        return {}, {}
    data = tomllib.loads(Path(path).read_text())
    records, notes = {}, {}
    for track, table in data.items():
        if not isinstance(table, dict):
            raise ValueError(f"{path}: top-level keys are tracks, got {track!r} = {table!r}")
        records[track.lower()] = _steps(table, f"{path} [{track}]", "agent")
        if "note" in table:
            notes[track.lower()] = str(table["note"])
    return records, notes


def load_project(folder: Path | None) -> tuple[dict[str, Record], str]:
    """The step records and note in a project folder's zpkt-workflow.toml, if it has one."""
    file = folder / PROJECT_FILE if folder else None
    if file is None or not file.is_file():
        return {}, ""
    data = tomllib.loads(file.read_text())
    return _steps(data, str(file), "anthony"), str(data.get("note", ""))
