"""The project model, as pure functions.

Zod is the source of truth for the shape of a project. ``frontend/lib/project.ts``
declares it, ``frontend/scripts/emit-schema.mjs`` emits
``audio-browser/schemas/project.schema.json`` from those declarations, and this
module validates against that generated file with ``jsonschema``. Neither
language hand-maintains a second copy of the shape.

Two rules cannot be written in JSON Schema draft 7, so they are checked here
after the schema passes, mirroring ``checkProject`` in TypeScript line for line:

1. ``sounds`` is a set, so no hash may appear twice.
2. Instants go forwards: ``updated_at`` is not before ``created_at``, each
   commit is not before the entry above it, and an abandonment is not before the
   last thing that happened.

Plus the one rule that needs two fields compared: ``abandoned.from`` is the
column ``column`` says the project is in.

The ``collage`` field carries rules of its own that the schema cannot hold
either: every region cuts from a hash in the frozen sound set, ``start_s`` is
before ``end_s``, region ids are unique, and a project still in ``stored`` has
no frozen set to cut from and so holds no collage. Those live in
:func:`collage_issues`.

Nothing in this module reads a file, takes a clock, or opens a connection. The
effects live in :mod:`audio_browser.projects.store`.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from blake3 import blake3
from jsonschema import Draft7Validator

SCHEMA_VERSION = 1
"""Bumped when the document shape changes in a way old files do not satisfy."""

MAX_PROJECT_SOUNDS = 512
"""The most sounds one project may hold.

A hard industrial techno track is assembled from tens of sounds, not thousands.
The cap stops a runaway bulk add writing a document the board then has to read
on every draw.
"""

MAX_NAME_LENGTH = 120
MAX_NOTES_LENGTH = 10_000
MAX_REASON_LENGTH = 2000

MAX_COLLAGE_REGIONS = 2000
"""The most regions one collage may hold.

Fifteen sparse sources cut into phrases is tens of regions, not thousands. The
cap bounds the document the board reads on every draw, as the sound cap does.
The number is the one the generated schema carries, so both layers refuse at
the same point.
"""

MAX_REGION_ID_LENGTH = 40
"""As the generated schema has it. An id is a handle, not a name."""

Column = Literal["stored", "collage", "enrich"]
Placement = Literal["stored", "collage", "enrich", "released"]

COLUMNS: tuple[Column, ...] = ("stored", "collage", "enrich")
"""The board as it is built. Three columns, in order.

``enrich`` is the placeholder: a column with a cap and no view, which is the
role ``collage`` held until its view was built. It exists so that a project in
``collage`` has somewhere to commit to. Nothing follows it, so the pipeline
ends there and deadlocks there, which is the behaviour the constraint is for
rather than a gap in it. Each new view pushes the placeholder one step along.
"""

PLANNED_COLUMNS: tuple[str, ...] = ("stored", "collage", "enrich")
"""The pipeline as designed.

The board needs this to name what is missing when a column has nowhere to
commit to. Every planned stage is now a column, so the last one reports that
nothing follows it rather than naming a stage that does not exist yet.
"""

PLACEMENTS: tuple[Placement, ...] = ("stored", "collage", "enrich", "released")
"""Every value ``column`` may hold in a document.

Wider than :data:`COLUMNS` on purpose. The document schema is generated from the
Zod declarations in ``frontend/lib/project.ts`` and still knows all four, so a
file naming ``enrich`` parses. It just holds no slot, because there is no such
column to hold one in.
"""

DEFAULT_CAP = 1
"""Slots per column.

One. A second uncommitted project in ``stored`` would mean choosing which
project a swiped sound goes into, and there is no such choice: one lane, one
project, one decision per sound.
"""

DEFAULT_ENCUMBRANCE = 16
"""Sounds past which a project is marked encumbered.

A hard techno track is a kick, a rumble, a few percussive textures, two or three
atmospheres and some impacts. Past sixteen you are collecting, not building.
"""

SCHEMA_FILE = "project.schema.json"


def next_placement(column: Column) -> Column | None:
    """The column a commit out of ``column`` moves the project into.

    ``None`` when the next stage is not built. The project then stays where it
    is, holding its lane: releasing it would free the lane, and a pipeline whose
    last column empties itself is not a constraint at all. Abandon is the one
    way out, and that is the price it is meant to be.
    """
    at = COLUMNS.index(column)
    if at == len(COLUMNS) - 1:
        return None
    return COLUMNS[at + 1]


def next_planned(column: Column) -> str | None:
    """The stage that follows this one in the plan, built or not.

    ``"enrich"`` after ``collage``. This is the name the board reports when it
    says why nothing can move.
    """
    at = PLANNED_COLUMNS.index(column)
    if at == len(PLANNED_COLUMNS) - 1:
        return None
    return PLANNED_COLUMNS[at + 1]


def is_column(placement: str) -> bool:
    """True for the columns that exist. ``released`` is not one."""
    return placement in COLUMNS


def is_over(count: int, cap: int) -> bool:
    """Over its limit. At a cap of 0 anything at all is over it."""
    return count > cap


def is_encumbered(sound_count: int, threshold: int = DEFAULT_ENCUMBRANCE) -> bool:
    """Whether a project is carrying more material than a track needs.

    Friction, not restriction. Nothing refuses an add because of this; the mark
    is reported every time the project is on screen, and it clears on its own as
    soon as the count comes back down.
    """
    return sound_count > threshold


def utc_now() -> str:
    """Now, as the one instant format the schema accepts: ``…Z``, to the second.

    ``db.now_iso`` writes ``+00:00``, which the schema's pattern refuses. A
    project document is validated against that pattern in both languages, so it
    needs its own clock rather than a near-miss.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------- artifacts


def manifest_input(hashes: Iterable[str]) -> str:
    """Exactly what ``stored`` hashes.

    Member hashes, deduplicated, sorted, joined by newline, no trailing newline.
    TypeScript's ``manifestInput`` produces the same bytes; both languages must
    agree byte for byte or the freeze is not checkable.
    """
    return "\n".join(sorted(set(hashes)))


def digest_of(text: str) -> str:
    """BLAKE3 of a string, as lower-case hex. The same digest a hash is."""
    return blake3(text.encode("utf-8")).hexdigest()


REGION_STRING_FIELDS: tuple[str, ...] = ("id", "hash")
REGION_INT_FIELDS: tuple[str, ...] = ("track",)
REGION_FLOAT_FIELDS: tuple[str, ...] = (
    "start_s",
    "end_s",
    "at_s",
    "rate",
    "gain",
    "fade_in_s",
    "fade_out_s",
)
REGION_FIELDS: frozenset[str] = frozenset(
    (*REGION_STRING_FIELDS, *REGION_INT_FIELDS, *REGION_FLOAT_FIELDS)
)
"""Exactly the keys a region carries. No more, no fewer."""


def _fixed(value: float) -> str:
    """A number as fixed-point text with six decimals.

    Six decimals is a microsecond, finer than any placement a hand can make
    and finer than a sample at 48 kHz. Fixed-point rather than shortest
    round-trip because both languages can print it the same way: ``toFixed(6)``
    in TypeScript and ``:.6f`` here, so ``0.1 + 0.2`` and ``0.3`` are one
    string. Negative zero is folded into zero for the same reason.
    """
    number = float(value)
    if number == 0:
        number = 0.0
    return f"{number:.6f}"


def collage_input(collage: dict[str, Any]) -> str:
    """Exactly what ``collage`` hashes: the canonical text of a description.

    The rule, in full:

    * regions are sorted by ``id``, so the order they were stamped in is not
      part of the freeze;
    * inside a region the keys are sorted;
    * ``id`` and ``hash`` are JSON strings with non-ASCII escaped;
    * ``track`` is a plain integer;
    * every other number is fixed-point with six decimals, so ``1`` and ``1.0``
      and ``1.0000000001`` are one string;
    * there is no whitespace anywhere.

    Two descriptions that mean the same thing produce the same bytes here, and
    so the same digest. TypeScript must produce these bytes too, or the freeze
    is not checkable from the other side.
    """
    regions = cast(list[dict[str, Any]], collage["regions"])
    rendered: list[str] = []
    for region in sorted(regions, key=lambda r: cast(str, r["id"])):
        fields: list[str] = []
        for key in sorted(REGION_FIELDS):
            value = region[key]
            if key in REGION_STRING_FIELDS:
                text = json.dumps(value, ensure_ascii=True)
            elif key in REGION_INT_FIELDS:
                text = str(int(value))
            else:
                text = _fixed(value)
            fields.append(f'"{key}":{text}')
        rendered.append("{" + ",".join(fields) + "}")
    return '{"regions":[' + ",".join(rendered) + "]}"


@dataclass(frozen=True, slots=True)
class Artifact:
    """The bytes a stage digests, and whether that artifact is real yet."""

    input: str
    real: bool

    @property
    def digest(self) -> str:
        return digest_of(self.input)


def commit_artifact(
    project_id: str,
    hashes: Sequence[str],
    column: Column,
    *,
    collage: dict[str, Any] | None = None,
) -> Artifact:
    """What this column freezes.

    ``stored`` owns the sound set and its artifact is the one the specification
    fixes. ``collage`` owns the description of what was cut and where it was
    put, and its artifact is the canonical text of that description; the
    caller passes it, and passing nothing is a placeholder. ``enrich`` has no
    view yet, so its artifact is a placeholder: deterministic and different for
    every project, so two commits never collide, but ``real`` is false and the
    interface says so rather than presenting a digest of nothing as a digest of
    something.
    """
    manifest = manifest_input(hashes)
    if column == "stored":
        return Artifact(input=manifest, real=True)
    if column == "collage" and collage is not None:
        return Artifact(input=collage_input(collage), real=True)
    return Artifact(input=f"{column} {project_id} {manifest}", real=False)


# -------------------------------------------------------------------- identity

# Letters that have a Latin reading but that NFKD does not take apart. Mirrors
# the table in frontend/lib/project.ts, so an id made here and an id made there
# are the same string.
_TRANSLITERATED: dict[str, str] = {
    # Cyrillic, in the reading English uses for it.
    "а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e",
    "ё": "e", "є": "ye", "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "yi",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e",
    "ю": "yu", "я": "ya",
    # Greek.
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i",
    "θ": "th", "ι": "i", "κ": "k", "λ": "l", "μ": "m", "ν": "n", "ξ": "x",
    "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t", "υ": "y",
    "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
    # Latin letters that are one character and not a letter plus a mark.
    "ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "å": "aa", "đ": "d", "ð": "d",
    "þ": "th", "ł": "l",
}


def _transliterate(name: str) -> str:
    """The name with every script this knows read into Latin letters."""
    out: list[str] = []
    for character in unicodedata.normalize("NFKD", name).lower():
        out.append(_TRANSLITERATED.get(character, character))
    return "".join(out)


def _code_point_slug(name: str) -> str:
    """A slug built from the code points of a name with no Latin reading.

    ``🔥🔥🔥`` is not transliterable, and calling it ``project`` would make the id
    say nothing about the project. This names the characters themselves.
    """
    tokens: list[str] = []
    for character in name:
        code = ord(character)
        if code <= 0x20:  # spaces and control characters name nothing
            continue
        token = f"u{code:x}"
        if token not in tokens:
            tokens.append(token)
        if len(tokens) == 4:
            break
    return "-".join(tokens)


def slugify(name: str) -> str:
    """The name reduced to slug characters.

    Three steps, each a fallback for the last: read the name into Latin letters,
    then name its characters by their code points, then give up and call it
    ``project``.
    """
    latin: list[str] = []
    for character in _transliterate(name):
        latin.append(character if character.isascii() and character.isalnum() else "-")
    collapsed = "-".join(part for part in "".join(latin).split("-") if part)
    trimmed = collapsed[:80].rstrip("-")
    if trimmed:
        return trimmed
    return _code_point_slug(name) or "project"


def project_id(name: str, created_at: str) -> str:
    """The id a new project would take: the day it was made, then its name."""
    return f"{created_at[:10]}-{slugify(name)}"


def unique_project_id(base: str, taken: Iterable[str]) -> str:
    """The first free id in the family ``base``, ``base-2``, ``base-3``, …

    Duplicate names are allowed; duplicate files are not.
    """
    used = set(taken)
    if base not in used:
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"
        if candidate not in used:
            return candidate
    raise ValueError(f"no free id in the family {base!r}")


# ------------------------------------------------------------------ validation


@dataclass(frozen=True, slots=True)
class Issue:
    """A problem with a document, in the shape ``safeParse`` reports."""

    path: str
    message: str


def load_validator(schema_dir: Path) -> Draft7Validator:
    """The validator for the generated project schema.

    The generated file is self-contained: every ``$ref`` points inside the same
    document, so nothing here resolves a URL or reaches the network.
    """
    raw = json.loads((schema_dir / SCHEMA_FILE).read_text(encoding="utf-8"))
    return Draft7Validator(raw)


COLLAGE_FIELD = "collage"


def schema_declares_collage(validator: Draft7Validator) -> bool:
    """Whether the generated schema knows the ``collage`` field yet.

    The schema is generated from the Zod declarations and lands on its own
    schedule. Until every branch declares ``collage``, Python is the authority
    for that field: the document is checked against the schema without it and
    the field is checked by :func:`collage_issues`. Once the schema carries it,
    both layers check it and must agree.
    """
    schema = cast(dict[str, Any], validator.schema)
    branches = cast(list[dict[str, Any]], schema.get("anyOf", [schema]))
    return all(
        COLLAGE_FIELD in cast(dict[str, Any], branch.get("properties", {}))
        for branch in branches
    )


def _for_schema(validator: Draft7Validator, raw: object) -> object:
    """The document as the schema is able to read it.

    Every branch closes with ``additionalProperties: false``, so a schema that
    has not learned ``collage`` would refuse every document carrying it. The
    field is taken out for the schema's benefit in that one case, and only in
    that one case. It is still checked, by :func:`collage_issues`.
    """
    if not isinstance(raw, dict) or COLLAGE_FIELD not in raw:
        return raw
    if schema_declares_collage(validator):
        return raw
    return {key: value for key, value in raw.items() if key != COLLAGE_FIELD}


def schema_accepts(validator: Draft7Validator, raw: object) -> bool:
    """Whether the generated schema alone accepts a document.

    "Alone" means without the rules only Python can check, and with the
    ``collage`` field taken out when the schema has not learned it. This is
    what a test reaches for to say "the schema lets this through, the model
    does not".
    """
    return validator.is_valid(_for_schema(validator, raw))


def _schema_issues(validator: Draft7Validator, raw: object) -> list[Issue]:
    """Schema failures, as one issue each.

    The document is a four-branch ``anyOf`` keyed on ``column``, so one wrong
    field fails all four branches. Reporting every failure buries the real
    problem under three about columns the file never claimed to be in, so the
    branch the document was trying to be is picked out and only that branch is
    described.
    """
    branch = _branch_of(raw)
    issues: list[Issue] = []
    for error in validator.iter_errors(_for_schema(validator, raw)):
        best = _best_branch(error, branch)
        issues.append(
            Issue(
                path=".".join(str(part) for part in best.absolute_path) or "(root)",
                message=best.message,
            )
        )
    return sorted(issues, key=lambda issue: issue.path)


def _branch_of(raw: object) -> int | None:
    """Which of the four branches this document is claiming to be.

    ``None`` when ``column`` is missing or is not a placement, in which case
    there is no branch to prefer and the deepest failure is reported instead.
    """
    if not isinstance(raw, dict):
        return None
    placement = raw.get("column")
    if not isinstance(placement, str) or placement not in PLACEMENTS:
        return None
    return PLACEMENTS.index(placement)


def _best_branch(error: Any, branch: int | None) -> Any:
    """The sub-error worth showing, out of one per ``anyOf`` branch."""
    if not error.context:
        return error
    candidates = [
        sub
        for sub in error.context
        if branch is not None and list(sub.schema_path)[:1] == [branch]
    ]
    return min(candidates or list(error.context), key=_branch_distance)


def _branch_distance(error: Any) -> tuple[int, int]:
    """How far into the document a branch got before it failed.

    The branch that complains about the deepest field is the one the document
    was closest to satisfying, so it is the one worth reporting.
    """
    return (-len(list(error.absolute_path)), len(error.message))


def stored_commit(commits: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The ``stored`` commit, if the sound set has been frozen."""
    return _commit_of(commits, "stored")


def collage_commit(commits: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The ``collage`` commit, if the description has been frozen."""
    return _commit_of(commits, "collage")


def _commit_of(
    commits: Sequence[dict[str, Any]], column: str
) -> dict[str, Any] | None:
    for commit in commits:
        if commit.get("column") == column:
            return commit
    return None


def collage_of(document: dict[str, Any]) -> dict[str, Any] | None:
    """The ``collage`` field, with an absent key read as null.

    Files written before the field existed do not carry the key. They mean
    the same thing as a file that says ``null``: nothing has been cut yet.
    """
    value = document.get(COLLAGE_FIELD)
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def collage_open(document: dict[str, Any]) -> bool:
    """Whether this project's description can still change.

    Three conditions, all checked, as :func:`sound_set_open` checks its three:
    it is in ``collage``, it is on the board, and no ``collage`` commit exists.
    """
    commits = document.get("commits")
    return (
        document.get("column") == "collage"
        and document.get("abandoned") is None
        and collage_commit(commits if isinstance(commits, list) else []) is None
    )


def _is_number(value: object) -> bool:
    """A JSON number. ``True`` is not one, whatever Python says."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _region_issues(
    index: int, region: object, frozen: frozenset[str]
) -> list[Issue]:
    """Everything wrong with one region. The path names the region by index."""
    at = f"collage.regions.{index}"
    if not isinstance(region, dict):
        return [Issue(path=at, message="a region is an object")]
    keys = set(region)
    if keys != REGION_FIELDS:
        missing = sorted(REGION_FIELDS - keys)
        extra = sorted(keys - REGION_FIELDS)
        parts: list[str] = []
        if missing:
            parts.append(f"missing {', '.join(missing)}")
        if extra:
            parts.append(f"unexpected {', '.join(extra)}")
        return [Issue(path=at, message="; ".join(parts))]

    issues: list[Issue] = []
    region_id = region["id"]
    if (
        not isinstance(region_id, str)
        or not region_id
        or len(region_id) > MAX_REGION_ID_LENGTH
    ):
        issues.append(
            Issue(
                path=f"{at}.id",
                message=f"an id is 1 to {MAX_REGION_ID_LENGTH} characters",
            )
        )
    source = region["hash"]
    if not isinstance(source, str) or source not in frozen:
        issues.append(
            Issue(
                path=f"{at}.hash",
                message=(
                    "a region cuts from a sound in the frozen set. Collage "
                    "cannot introduce new material: stored was committed."
                ),
            )
        )
    track = region["track"]
    if not _is_number(track) or isinstance(track, float) or track < 0:
        issues.append(Issue(path=f"{at}.track", message="track is a whole number, 0 or more"))

    numbers: dict[str, float] = {}
    for key in REGION_FLOAT_FIELDS:
        value = region[key]
        if not _is_number(value) or not math.isfinite(value):
            issues.append(Issue(path=f"{at}.{key}", message=f"{key} is a finite number"))
            continue
        numbers[key] = float(value)

    def check(key: str, ok: bool, message: str) -> None:
        if key in numbers and not ok:
            issues.append(Issue(path=f"{at}.{key}", message=message))

    check("start_s", numbers.get("start_s", 0.0) >= 0, "start_s is 0 or more")
    check("at_s", numbers.get("at_s", 0.0) >= 0, "at_s is 0 or more")
    check("rate", numbers.get("rate", 1.0) > 0, "rate is more than 0")
    check("gain", numbers.get("gain", 0.0) >= 0, "gain is 0 or more")
    check("fade_in_s", numbers.get("fade_in_s", 0.0) >= 0, "fade_in_s is 0 or more")
    check("fade_out_s", numbers.get("fade_out_s", 0.0) >= 0, "fade_out_s is 0 or more")
    if "start_s" in numbers and "end_s" in numbers and not numbers["start_s"] < numbers["end_s"]:
        issues.append(Issue(path=f"{at}.end_s", message="end_s is after start_s"))
    return issues


def collage_issues(document: dict[str, Any]) -> list[Issue]:
    """Everything wrong with a document's ``collage`` field.

    Empty when the field is null, absent, or a description every rule accepts.
    These are the rules the schema cannot carry, plus the shape itself, because
    the schema may not have learned the field yet (see
    :func:`schema_declares_collage`).
    """
    raw = document.get(COLLAGE_FIELD)
    if raw is None:
        return []
    if document.get("column") == "stored":
        return [
            Issue(
                path=COLLAGE_FIELD,
                message=(
                    "a project in stored has no frozen sound set to cut from, "
                    "so it holds no collage"
                ),
            )
        ]
    if not isinstance(raw, dict) or set(raw) != {"regions"}:
        return [Issue(path=COLLAGE_FIELD, message="a collage is an object holding regions")]
    regions = raw["regions"]
    if not isinstance(regions, list):
        return [Issue(path="collage.regions", message="regions is an array")]
    if len(regions) > MAX_COLLAGE_REGIONS:
        return [
            Issue(
                path="collage.regions",
                message=f"a collage holds at most {MAX_COLLAGE_REGIONS} regions",
            )
        ]

    sounds = document.get("sounds")
    frozen = frozenset(
        cast(str, sound["hash"])
        for sound in (sounds if isinstance(sounds, list) else [])
        if isinstance(sound, dict) and isinstance(sound.get("hash"), str)
    )
    issues: list[Issue] = []
    seen: set[str] = set()
    twice: set[str] = set()
    for index, region in enumerate(regions):
        issues.extend(_region_issues(index, region, frozen))
        if isinstance(region, dict) and isinstance(region.get("id"), str):
            if region["id"] in seen:
                twice.add(region["id"])
            seen.add(region["id"])
    if twice:
        issues.append(
            Issue(
                path="collage.regions",
                message=f"region ids are unique: {', '.join(sorted(twice))} repeat",
            )
        )
    return issues


def sound_set_open(document: dict[str, Any]) -> bool:
    """Whether this project can still gain or lose a sound.

    Three conditions, all checked: it is in ``stored``, it is on the board, and
    no ``stored`` commit exists. Any one alone would be enough in a consistent
    file; checking all three is what makes a hand-edited file fail closed.
    """
    commits = document.get("commits")
    return (
        document.get("column") == "stored"
        and document.get("abandoned") is None
        and stored_commit(commits if isinstance(commits, list) else []) is None
    )


def on_board(document: dict[str, Any]) -> bool:
    """In a column and not abandoned. This is the one test the caps use."""
    placement = document.get("column")
    return isinstance(placement, str) and is_column(placement) and document.get("abandoned") is None


def slot_holder(raw: object) -> Column | None:
    """The column an unreadable file is still holding a slot in, if any.

    A cap cannot ask the schema about a file the schema rejects, so it asks this
    instead: the one field it needs is ``column``, and that field is readable on
    its own. A file naming a column holds a slot there until somebody fixes it.

    A file that says it was abandoned is taken at its word and holds nothing.
    That is not a way round the cap: abandoning is a supported move that frees a
    slot anyway, and it is reversible.
    """
    if not isinstance(raw, dict):
        return None
    placement = raw.get("column")
    if not isinstance(placement, str) or placement not in COLUMNS:
        return None
    if raw.get("abandoned") is not None:
        return None
    return placement


def check_project(validator: Draft7Validator, raw: object) -> list[Issue]:
    """Validate a document, including the rules JSON Schema cannot carry.

    An empty list means the document is good. Every check below has a twin in
    ``checkProject`` in ``frontend/lib/project.ts``; if the two ever disagree,
    a file one language accepts is a file the other rejects, and the "one
    schema" guarantee is a lie.
    """
    issues = _schema_issues(validator, raw)
    if issues:
        return issues
    document = cast(dict[str, Any], raw)

    sounds = cast(list[dict[str, Any]], document["sounds"])
    seen: set[str] = set()
    twice: set[str] = set()
    for sound in sounds:
        if sound["hash"] in seen:
            twice.add(sound["hash"])
        seen.add(sound["hash"])
    if twice:
        plural = "" if len(twice) == 1 else "es"
        issues.append(
            Issue(
                path="sounds",
                message=(
                    f"membership is a set: {len(twice)} hash{plural} appear "
                    "more than once"
                ),
            )
        )

    if document["updated_at"] < document["created_at"]:
        issues.append(Issue(path="updated_at", message="updated_at is before created_at"))

    # The chain is append only, so its instants never go backwards and never
    # predate the project itself. ISO 8601 in UTC sorts lexically, so string
    # comparison is the right comparison and needs no date parsing.
    previous = cast(str, document["created_at"])
    for index, commit in enumerate(cast(list[dict[str, Any]], document["commits"])):
        if commit["at"] < previous:
            issues.append(
                Issue(
                    path=f"commits.{index}.at",
                    message=(
                        f"the {commit['column']} commit is dated before the "
                        "entry above it"
                    ),
                )
            )
        previous = cast(str, commit["at"])

    abandoned = document["abandoned"]
    if abandoned is not None:
        if abandoned["from"] != document["column"]:
            issues.append(
                Issue(
                    path="abandoned.from",
                    message=(
                        f"it was abandoned out of {abandoned['from']} but the "
                        f"file says it is in {document['column']}"
                    ),
                )
            )
        if abandoned["at"] < previous:
            issues.append(
                Issue(
                    path="abandoned.at",
                    message="it was abandoned before the last thing that happened to it",
                )
            )

    issues.extend(collage_issues(document))
    return issues


def describe_issues(issues: Sequence[Issue]) -> str:
    """A one-line reading of what is wrong with a file."""
    return "; ".join(f"{issue.path}: {issue.message}" for issue in issues)


# ------------------------------------------------------------------- documents


def new_document(project_id_: str, name: str, at: str) -> dict[str, Any]:
    """A project as it starts: in ``stored``, on the board, holding nothing."""
    return {
        "schema_version": SCHEMA_VERSION,
        "id": project_id_,
        "name": name,
        "column": "stored",
        "created_at": at,
        "updated_at": at,
        "notes": "",
        "abandoned": None,
        "commits": [],
        "sounds": [],
        "collage": None,
    }


def with_collage(
    document: dict[str, Any], collage: dict[str, Any], at: str
) -> dict[str, Any]:
    """The document with its description replaced whole.

    Replaced, not merged. The client sends the entire description every time,
    so a region it no longer lists is gone; there is no partial edit to reason
    about. Nothing here touches ``sounds`` or the audio behind them.
    """
    return {**document, COLLAGE_FIELD: collage, "updated_at": at}


def with_sound(document: dict[str, Any], file_hash: str, at: str) -> dict[str, Any]:
    """The document with one more sound. Adding a member twice changes nothing."""
    sounds = cast(list[dict[str, Any]], document["sounds"])
    if any(sound["hash"] == file_hash for sound in sounds):
        return document
    added = {"hash": file_hash, "added_at": at, "role": None, "note": ""}
    return {**document, "sounds": [*sounds, added], "updated_at": at}


def without_sound(document: dict[str, Any], file_hash: str, at: str) -> dict[str, Any]:
    """The document with one sound taken out. It removes no audio.

    Every path that held the bytes still holds them; this drops one entry from a
    JSON array.
    """
    sounds = cast(list[dict[str, Any]], document["sounds"])
    kept = [sound for sound in sounds if sound["hash"] != file_hash]
    if len(kept) == len(sounds):
        return document
    return {**document, "sounds": kept, "updated_at": at}


def committed(
    document: dict[str, Any], column: Column, artifact: Artifact, at: str
) -> dict[str, Any]:
    """The document one stage on: chain appended, placement advanced.

    One way. Nothing in this module or above it takes an entry back off the
    chain.

    Only a column with somewhere to go can commit. The last built column has
    nowhere, and this refuses rather than inventing a destination: a commit that
    quietly released the project would free the lane, and freeing the lane is
    what abandon is for.
    """
    destination = next_placement(column)
    if destination is None:
        raise ValueError(
            f"{column} is the last column that exists, so there is nowhere to "
            "commit it to"
        )
    commits = cast(list[dict[str, Any]], document["commits"])
    entry = {"column": column, "at": at, "digest": artifact.digest}
    return {
        **document,
        "column": destination,
        "commits": [*commits, entry],
        "updated_at": at,
    }


def abandoned_doc(
    document: dict[str, Any], column: Column, reason: str, at: str
) -> dict[str, Any]:
    """The document off the board. Appends nothing to ``commits``."""
    return {
        **document,
        "abandoned": {"at": at, "from": column, "reason": reason},
        "updated_at": at,
    }


def revived(document: dict[str, Any], at: str) -> dict[str, Any]:
    """The document back on the board, in the column it left.

    ``column`` already records where it was, so revive clears one field. Every
    commit it had it still has.
    """
    return {**document, "abandoned": None, "updated_at": at}
