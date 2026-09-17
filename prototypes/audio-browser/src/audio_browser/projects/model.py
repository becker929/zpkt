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

Nothing in this module reads a file, takes a clock, or opens a connection. The
effects live in :mod:`audio_browser.projects.store`.
"""

from __future__ import annotations

import json
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

Column = Literal["stored", "collage", "enrich"]
Placement = Literal["stored", "collage", "enrich", "released"]

COLUMNS: tuple[Column, ...] = ("stored", "collage", "enrich")
"""The board. Three columns, in order."""

PLACEMENTS: tuple[Placement, ...] = ("stored", "collage", "enrich", "released")
"""Where a project can sit: the three columns, plus off the board."""

DEFAULT_CAP = 3
"""Slots per column. Meant to be turned down; 2, or 1, are reasonable."""

SCHEMA_FILE = "project.schema.json"


def next_placement(column: Column) -> Placement:
    """Where a project goes when this column commits. ``enrich`` releases."""
    at = COLUMNS.index(column)
    return "released" if at == len(COLUMNS) - 1 else COLUMNS[at + 1]


def is_column(placement: str) -> bool:
    """True for the three columns. ``released`` is not one."""
    return placement in COLUMNS


def is_over(count: int, cap: int) -> bool:
    """Over its limit. At a cap of 0 anything at all is over it."""
    return count > cap


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


@dataclass(frozen=True, slots=True)
class Artifact:
    """The bytes a stage digests, and whether that artifact is real yet."""

    input: str
    real: bool

    @property
    def digest(self) -> str:
        return digest_of(self.input)


def commit_artifact(
    project_id: str, hashes: Sequence[str], column: Column
) -> Artifact:
    """What this column freezes.

    ``stored`` owns the sound set and its artifact is the one the specification
    fixes. ``collage`` and ``enrich`` own an arrangement and a treatment, and
    neither view exists yet, so their artifact is a placeholder: deterministic
    and different for every project, so two commits never collide, but ``real``
    is false and the interface says so rather than presenting a digest of
    nothing as a digest of something.
    """
    manifest = manifest_input(hashes)
    if column == "stored":
        return Artifact(input=manifest, real=True)
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


def _schema_issues(validator: Draft7Validator, raw: object) -> list[Issue]:
    """Schema failures, worst first, as one issue each.

    The document is a four-branch ``anyOf`` keyed on ``column``, so a single
    wrong field produces one failure per branch. Reporting all of them buries
    the real problem under three irrelevant ones, so only the branch that got
    furthest is described when the top-level failure is the union itself.
    """
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    issues: list[Issue] = []
    for error in errors:
        best = min(error.context, key=_branch_distance) if error.context else error
        issues.append(
            Issue(
                path=".".join(str(part) for part in best.absolute_path) or "(root)",
                message=best.message,
            )
        )
    return issues


def _branch_distance(error: Any) -> tuple[int, int]:
    """How far into the document a branch got before it failed.

    The branch that complains about the deepest field is the one the document
    was trying to be, so it is the one worth reporting.
    """
    return (-len(list(error.absolute_path)), len(error.message))


def stored_commit(commits: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The ``stored`` commit, if the sound set has been frozen."""
    for commit in commits:
        if commit.get("column") == "stored":
            return commit
    return None


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
    }


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
    """
    commits = cast(list[dict[str, Any]], document["commits"])
    entry = {"column": column, "at": at, "digest": artifact.digest}
    return {
        **document,
        "column": next_placement(column),
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
