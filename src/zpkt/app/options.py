"""Options: a set of Versions of the mix, made to be heard side by side. This module is the pure part.

An Option is one question asked of the mix ("what does a 4-step grid on this drive sound like?"). It holds Versions:
each is one render, with its numbers (zpkt.audio.measure), its gap to the Option's base, and, when the Version is a
set of values on the mix, the writes that make it Now. An Option is also a job on the render queue, so it is the same
JSON on disk and on the wire (lib/contracts/option.schema.json).

Four older tools made Options before the app did, and each keeps its own files. `from_mix2`, `from_spectral`,
`from_kick` and `from_panel` read what they wrote and show it as Options; nothing is copied or changed. Everything
here is plain data in and out. Reading folders, rendering and the HTTP routes are in zpkt.app.renders and zpkt.app.web.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast

from zpkt.audio import measure as audio_measure
from zpkt.audio.measure import Gap, Measure

Kind = Literal["grid", "mix2", "spectral", "kick", "panel"]
Status = Literal["queued", "rendering", "ready", "failed"]
VersionStatus = Literal["queued", "rendering", "ready", "failed", "gone"]

MAX_VERSIONS = 16  # one Option's Versions, as a panel grid's
BASE_ID = "base"
STATUSES: tuple[str, ...] = ("queued", "rendering", "ready", "failed")
KINDS: tuple[str, ...] = ("grid", "mix2", "spectral", "kick", "panel")


class Version(TypedDict):
    """One render of an Option."""

    id: str
    label: str
    status: VersionStatus
    file: str | None  # the audio file, an absolute path
    writes: list[list[Any]] | None  # [[state key, raw value], ...] that make this Version Now; None: not a mix move
    measure: Measure | None
    gap: Gap | None  # this Version's measure minus the base's
    known: NotRequired[dict[str, float]]  # numbers the tool that made the file already knew (lufs, peak_db, rms_db)
    matched_file: NotRequired[str]  # the same render at the base's loudness, when the tool made one
    error: NotRequired[str]


class Option(TypedDict):
    """One Option."""

    id: str
    kind: Kind
    title: str
    status: Status
    made: float
    done: int
    total: int
    progress: str  # "rendering 2 of 3", "ready", the reason it failed
    base: str | None  # the Version the gaps are from
    now: str | None  # the Version that was made Now
    versions: list[Version]
    note: NotRequired[str]
    error: NotRequired[str]
    range: NotRequired[dict[str, float | None]]  # a job's bars: start_beat and length_beats (None: Live's own)


class BadOption(ValueError):
    """A request for an Option that cannot be made. The message says what to change."""


# ---- text ----------------------------------------------------------------------------------------------------------


def progress_text(status: str, done: int, total: int, error: str | None = None) -> str:
    """What the page shows of a job: "rendering 2 of 3" while it works (2 is the Version it is on)."""
    if status == "rendering":
        return f"rendering {min(done + 1, total)} of {total}"
    if status == "failed":
        return error or "failed"
    return "queued" if status == "queued" else "ready"


def version_id(index: int) -> str:
    return f"v{index + 1}"


# ---- a new job -----------------------------------------------------------------------------------------------------


def _finite(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(float(x))


def parse_writes(raw: Any, where: str) -> list[list[Any]]:
    """[[state key, raw value], ...] from a request; a bad one raises BadOption naming where."""
    if not isinstance(raw, list) or not raw:
        raise BadOption(f"{where} needs 'writes', a list of [state key, raw value]")
    out: list[list[Any]] = []
    for w in raw:
        if not (isinstance(w, list | tuple) and len(w) == 2 and isinstance(w[0], str) and _finite(w[1])):
            raise BadOption(f"{where}: each write is [state key, raw value], with a finite number")
        out.append([w[0], float(w[1])])
    return out


def parse_range(raw: Any) -> dict[str, float | None]:
    """The bars a job renders: {"start_beat", "length_beats"}, both or neither (neither: Live's own range)."""
    if raw is None:
        return {"start_beat": None, "length_beats": None}
    if not isinstance(raw, Mapping) or not _finite(raw.get("start_beat")) or not _finite(raw.get("length_beats")):
        raise BadOption("'range' is {start_beat, length_beats}, both numbers, or leave it out for Live's own range")
    if float(raw["length_beats"]) <= 0 or float(raw["start_beat"]) < 0:
        raise BadOption("'range' needs a start of 0 or more and a length above 0")
    return {"start_beat": float(raw["start_beat"]), "length_beats": float(raw["length_beats"])}


def new_job(body: Mapping[str, Any]) -> dict[str, Any]:
    """The job for a request {title, versions: [{label, writes}], range?, base?}: its Versions are queued, and the
    first is the base (the mix as it stands, no writes) unless `base` is false. Not yet filed (no id or time)."""
    title = str(body.get("title") or "").strip()
    if not title:
        raise BadOption("say what the Option is for: the body needs 'title'")
    asked = body.get("versions")
    if not isinstance(asked, list) or not asked:
        raise BadOption("the body needs 'versions', a list of {label, writes}")
    versions: list[Version] = []
    if body.get("base", True):
        versions.append(_queued(BASE_ID, "Now", None))
    for k, v in enumerate(asked):
        if not isinstance(v, Mapping):
            raise BadOption(f"version {k + 1} must be {{label, writes}}")
        label = str(v.get("label") or f"Version {k + 1}")[:60]
        versions.append(_queued(version_id(k), label, parse_writes(v.get("writes"), f"version {k + 1}")))
    if len(versions) > MAX_VERSIONS:
        raise BadOption(f"an Option holds at most {MAX_VERSIONS} Versions; this has {len(versions)}")
    return {
        "kind": "grid",
        "title": title[:80],
        "done": 0,
        "total": len(versions),
        "progress": "queued",
        "base": BASE_ID if body.get("base", True) else None,
        "now": None,
        "versions": versions,
        "range": parse_range(body.get("range")),
    }


def _queued(vid: str, label: str, writes: list[list[Any]] | None) -> Version:
    return {
        "id": vid,
        "label": label,
        "status": "queued",
        "file": None,
        "writes": writes,
        "measure": None,
        "gap": None,
    }


def keys_of(option: Mapping[str, Any]) -> list[str]:
    """Every state key any Version of the Option writes."""
    seen: dict[str, None] = {}
    for v in option["versions"]:
        for key, _ in v["writes"] or []:
            seen[key] = None
    return list(seen)


# ---- numbers -------------------------------------------------------------------------------------------------------


def with_gaps(option: Option) -> Option:
    """The Option with each measured Version's gap to the base's measure (None where either is not measured)."""
    base = next((v for v in option["versions"] if v["id"] == option["base"]), None)
    base_m = base["measure"] if base else None
    versions = [
        {**v, "gap": audio_measure.gap(v["measure"], base_m) if v["measure"] and base_m else None}
        for v in option["versions"]
    ]
    return cast(Option, {**option, "versions": versions})


def loudness_of(version: Version) -> float | None:
    """A Version's loudness: its own measure's, else what the tool that made it knew."""
    if version["measure"] and version["measure"]["lufs"] is not None:
        return version["measure"]["lufs"]
    return version.get("known", {}).get("lufs")


def find_version(option: Mapping[str, Any], vid: str) -> Version:
    for v in option["versions"]:
        if v["id"] == vid:
            return cast(Version, v)
    raise BadOption(f"{option['id']} has no Version {vid!r}; it has {', '.join(v['id'] for v in option['versions'])}")


# ---- the older tools' Options --------------------------------------------------------------------------------------


def _imported(
    oid: str,
    kind: Kind,
    title: str,
    versions: list[Version],
    made: float,
    status: Status = "ready",
    extra: Mapping[str, Any] | None = None,
) -> Option:
    done = sum(1 for v in versions if v["status"] == "ready")
    option: dict[str, Any] = {
        "id": oid,
        "kind": kind,
        "title": title,
        "status": status,
        "made": made,
        "done": done,
        "total": len(versions),
        "progress": "ready" if status == "ready" else status,
        "base": versions[0]["id"] if versions else None,
        "now": None,
        **(extra or {}),
        "versions": versions,
    }
    return cast(Option, option)


def _file_version(
    vid: str, label: str, path: Path | None, known: Mapping[str, float | None] | None = None, **extra: Any
) -> Version:
    have = path is not None and path.is_file()
    version: dict[str, Any] = {
        "id": vid,
        "label": label,
        "status": "ready" if have else "gone",
        "file": str(path) if have and path else None,
        "writes": None,
        "measure": None,
        "gap": None,
        **extra,
    }
    numbers = {k: float(v) for k, v in (known or {}).items() if v is not None}
    if numbers:
        version["known"] = numbers
    return cast(Version, version)


def from_mix2(row: Mapping[str, Any], folder: Path) -> Option:
    """A mix-2 batch (a request file of <data>/mix2/requests) as an Option. Its renders are in <folder>/<id>/."""
    out = folder / str(row["id"])
    versions: list[Version] = []
    if row.get("base"):
        versions.append(_file_version(BASE_ID, "As kept", out / str(row["base"]), {"lufs": row.get("baseLufs")}))
    for p in row.get("points") or []:
        label = ", ".join(f"{k} {v}" for k, v in (p.get("values") or {}).items()) or f"Point {p.get('k', 0) + 1}"
        also = {"matched_file": str(out / p["matched"])} if p.get("matched") else {}
        versions.append(
            _file_version(f"p{int(p['k']):02d}", label, out / str(p["file"]), {"lufs": p.get("lufs")}, **also)
        )
    status: Status = cast(Status, row["status"]) if row.get("status") in STATUSES else "failed"
    total = int(row.get("total") or len(versions))
    done = int(row.get("done") or 0)
    where = f"{row.get('device', '?')} on {row.get('target', '?')}"
    extra: dict[str, Any] = {
        "done": done,
        "total": total,
        "progress": progress_text(status, done, total, row.get("error")),
    }
    if row.get("error"):
        extra["error"] = str(row["error"])
    return _imported(
        f"mix2-{row['id']}", "mix2", f"Mix 2: {where}", versions, float(row.get("made") or 0), status, extra
    )


def from_spectral(doc: Mapping[str, Any], folder: Path, made: float = 0.0) -> Option:
    """spectral.py's renders.json (the mix before, each fix alone, all fixes) as an Option."""
    versions = [
        _file_version(str(r["id"]), str(r["title"]), folder / str(r["file"]), {"lufs": r.get("lufsWhole")})
        for r in doc.get("renders", [])
    ]
    extra = {"note": str(doc["note"])} if doc.get("note") else None
    return _imported("spectral", "spectral", "Spectral fixes against the references", versions, made, extra=extra)


def from_kick(doc: Mapping[str, Any], folder: Path, made: float = 0.0) -> Option:
    """kickfuzz.py's renders.json (HW002's kick and its options) as an Option; a kick's mix render when there is one."""
    versions = []
    for o in doc.get("options", []):
        name = o.get("mix") or o.get("loop")
        versions.append(
            _file_version(
                str(o["id"]), str(o["title"]), (folder / name).resolve() if name else None, {"lufs": o.get("loopLufs")}
            )
        )
    return _imported("kick", "kick", "HW002's kick: the options", versions, made)


def from_panel(name: str, panel: Mapping[str, Any], made: float = 0.0) -> list[Option]:
    """Each grid of a panel file (`hands panel grid`) as an Option. A swept grid's Versions say their files are gone."""
    found = []
    for g in panel.get("grids") or []:
        versions = [
            _file_version(
                str(o["letter"]),
                str(o.get("label") or o["letter"]),
                Path(str(o["file"])).expanduser() if o.get("file") and not g.get("swept") else None,
                {"peak_db": o.get("peak_dbfs"), "rms_db": o.get("rms_dbfs")},
            )
            for o in g.get("options", [])
        ]
        found.append(_imported(f"panel-{name}-g{g['id']}", "panel", f"Panel {name}, grid {g['id']}", versions, made))
    return found


def ordered(options: Sequence[Option]) -> list[Option]:
    """Newest first; running jobs before ready ones."""
    rank = {"rendering": 0, "queued": 1, "failed": 3}
    return sorted(options, key=lambda o: (rank.get(o["status"], 2), -o["made"], o["id"]))
